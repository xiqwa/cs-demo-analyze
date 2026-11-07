from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import unquote
from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .aim import AnalysisError, PARSER_VERSION
from .config import private_directory, VERSION

MAX_DEMO_BYTES = 1024 ** 3
TRUSTED_ORIGINS = {'http://localhost:5173','http://127.0.0.1:5173','tauri://localhost','http://tauri.localhost'}


@dataclass
class ParseAttempt:
    id: str = field(default_factory=lambda: str(uuid4()))
    canceled: threading.Event = field(default_factory=threading.Event)
    future: object = None
    process: object = None


class DemoService:
    def __init__(self, settings, database):
        self.settings = settings
        self.database = database
        self.root = settings.data_dir
        for name in ['imports', 'jobs', 'reports']:
            private_directory(self.root / name)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='roundmind-parser')
        self.lock = threading.RLock()
        self.attempts = {}
        self.stopping = False
        with database.engine.begin() as conn:
            interrupted = conn.execute(text("SELECT id FROM demo_files WHERE status IN ('queued','validating','parsing','indexing')")).scalars().all()
            conn.execute(text("UPDATE demo_files SET status='failed' WHERE status IN ('queued','validating','parsing','indexing')"))
        for demo_id in interrupted:
            self.write_job(demo_id, 'failed', error_code='interrupted')

    def atomic_json(self, path, data):
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read_job(self, demo_id):
        path = self.root / 'jobs' / f'{demo_id}.json'
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            return {'job_id': demo_id, 'demo_id': demo_id, 'status': 'failed',
                    'error_code': 'job_state_missing', 'filename': 'Demo',
                    'attempt': 0, 'attempt_id': None}

    def write_job(self, demo_id, status, **fields):
        state = self.read_job(demo_id)
        if status != 'complete':
            state.pop('match_id', None)
        state.update({'job_id': demo_id, 'demo_id': demo_id, 'status': status, 'error_code': None, **fields})
        self.atomic_json(self.root / 'jobs' / f'{demo_id}.json', state)

    def get_demo(self, demo_id):
        with self.database.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM demo_files WHERE id=:id'), {'id': demo_id}).mappings().first()
            return dict(row) if row else None

    def snapshot(self, demo_id):
        with self.lock:
            demo = self.get_demo(demo_id)
            if demo is None:
                return None
            state = self.read_job(demo_id)
            state['status'] = demo['status']
            if demo['status'] == 'canceled':
                state['error_code'] = None
            return state

    def enqueue(self, demo_id):
        # Caller holds lock: worker cannot start before attempt/future are published.
        attempt = ParseAttempt()
        self.attempts[demo_id] = attempt
        count = self.read_job(demo_id).get('attempt', 0) + 1
        self.set_status(demo_id, 'queued', attempt=count, attempt_id=attempt.id)
        attempt.future = self.executor.submit(self.run_job, demo_id, attempt)

    def register(self, temporary, sha256, size, filename):
        with self.lock:
            if self.stopping:
                raise AnalysisError('interrupted')
            with self.database.engine.begin() as conn:
                existing = conn.execute(text('SELECT id FROM demo_files WHERE sha256=:sha'), {'sha': sha256}).scalar()
                if existing:
                    return existing, True
                demo_id = str(uuid4())
                destination = self.root / 'imports' / f'{sha256}.dem'
                os.replace(temporary, destination)
                conn.execute(text("INSERT INTO demo_files (id,sha256,path,size,status,parser_version) VALUES (:id,:sha,:path,:size,'queued',:parser)"),
                             {'id': demo_id, 'sha': sha256, 'path': str(destination), 'size': size, 'parser': PARSER_VERSION})
            self.write_job(demo_id, 'queued', filename=filename)
            self.enqueue(demo_id)
            return demo_id, False

    def retry(self, demo_id):
        with self.lock:
            demo = self.get_demo(demo_id)
            if not demo:
                return False
            if self.stopping or demo['status'] not in {'failed', 'canceled'}:
                raise AnalysisError('job_not_retryable')
            self.enqueue(demo_id)
            return True

    def cancel(self, demo_id):
        with self.lock:
            demo = self.get_demo(demo_id)
            if demo is None:
                return False
            if demo['status'] == 'canceled':
                return True
            if demo['status'] not in {'queued', 'parsing'}:
                raise AnalysisError('job_not_cancelable')
            attempt = self.attempts.get(demo_id)
            if attempt is not None:
                attempt.canceled.set()
                if attempt.future is not None:
                    attempt.future.cancel()
                self.kill_child(attempt)
            self.set_status(demo_id, 'canceled')
            return True

    @staticmethod
    def kill_child(attempt):
        process = attempt.process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # Natural exit raced with cancellation.

    def set_status(self, demo_id, status, **fields):
        # Every writer follows lock -> SQLite ordering; indexing cannot deadlock
        # against a cancellation that is waiting to change its status.
        with self.lock:
            with self.database.engine.begin() as conn:
                conn.execute(text('UPDATE demo_files SET status=:status WHERE id=:id'), {'id': demo_id, 'status': status})
            self.write_job(demo_id, status, **fields)

    def current(self, demo_id, attempt):
        return self.attempts.get(demo_id) is attempt and not attempt.canceled.is_set()

    def parse_subprocess(self, demo_id, source, output, *, attempt):
        demo = self.get_demo(demo_id)
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'RAYON_NUM_THREADS': '2'}
        with self.lock:
            if self.stopping or not self.current(demo_id, attempt):
                raise AnalysisError('interrupted')
            process = subprocess.Popen([sys.executable, '-m', 'roundmind.parse_worker', str(source), str(output), demo_id, demo['sha256']],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            attempt.process = process
        try:
            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                self.kill_child(attempt)
                process.wait()
                raise AnalysisError('parse_timeout') from None
            with self.lock:
                if self.stopping or not self.current(demo_id, attempt):
                    raise AnalysisError('interrupted')
            if not output.exists():
                raise AnalysisError('parser_process_failed')
            payload = json.loads(output.read_text(encoding='utf-8'))
            if process.returncode != 0 or 'report' not in payload:
                code = payload.get('error_code')
                raise AnalysisError(code if code in {'no_confirmed_rounds', 'unsupported_or_corrupt_demo'} else 'parser_process_failed')
            return payload['report']
        finally:
            with self.lock:
                attempt.process = None

    def run_job(self, demo_id, attempt):
        output = self.root / 'reports' / f'{demo_id}.{attempt.id}.worker.tmp'
        try:
            with self.lock:
                if not self.current(demo_id, attempt):
                    return
                if self.stopping:
                    raise AnalysisError('interrupted')
                self.set_status(demo_id, 'parsing')
            demo = self.get_demo(demo_id)
            report = self.parse_subprocess(demo_id, Path(demo['path']), output, attempt=attempt)
            # Commit is not interruptible: cancellation either wins before this
            # critical section or observes an already completed transaction.
            with self.lock:
                if not self.current(demo_id, attempt):
                    return
                if self.stopping:
                    raise AnalysisError('interrupted')
                self.set_status(demo_id, 'indexing')
                with self.database.engine.begin() as conn:
                    conn.execute(text('DELETE FROM matches WHERE id=:id'), {'id': demo_id})
                    conn.execute(text('INSERT INTO matches (id,demo_id,map) VALUES (:id,:id,:map)'), {'id': demo_id, 'map': report['map']})
                    for r in report['rounds']:
                        conn.execute(text('INSERT INTO rounds (id,match_id,round_no,start_tick,end_tick) VALUES (:id,:match_id,:round_no,:start_tick,:end_tick)'), {**r, 'match_id': demo_id})
                    rows = [{**e, 'payload': json.dumps(e, ensure_ascii=False)} for e in report['events']]
                    if rows:
                        conn.execute(text('INSERT INTO events (id,round_id,tick,type,actor,target,payload) VALUES (:id,:round_id,:tick,:type,:actor,:target,:payload)'), rows)
                    public = {key: value for key, value in report.items() if key != 'events'}
                    self.atomic_json(self.root / 'reports' / f'{demo_id}.json', public)
                    conn.execute(text("UPDATE demo_files SET status='complete' WHERE id=:id"), {'id': demo_id})
                self.write_job(demo_id, 'complete', match_id=demo_id)
        except Exception as exc:
            with self.lock:
                if self.current(demo_id, attempt):
                    code = str(exc) if isinstance(exc, AnalysisError) else 'analysis_failed'
                    self.set_status(demo_id, 'failed', error_code=code)
        finally:
            output.unlink(missing_ok=True)

    def close(self):
        with self.lock:
            self.stopping = True
            for attempt in self.attempts.values():
                if attempt.future is not None:
                    attempt.future.cancel()
                self.kill_child(attempt)
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for demo_id in self.attempts:
                demo = self.get_demo(demo_id)
                if demo and demo['status'] in {'queued', 'parsing', 'indexing'}:
                    self.set_status(demo_id, 'failed', error_code='interrupted')

def envelope(request,data,status=200):
    return JSONResponse(status_code=status,content={'data':data,'meta':{'request_id':request.state.request_id,'version':VERSION}})


def failure(request,code,status):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':code,'details':{},'retryable':code in {'parse_timeout','interrupted'}},'request_id':request.state.request_id})


router=APIRouter(prefix='/api/v1')

@router.post('/demos/import',openapi_extra={'requestBody':{'required':True,'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}})
async def import_demo(request:Request):
    if request.headers.get('origin') and request.headers['origin'] not in TRUSTED_ORIGINS:
        return failure(request,'untrusted_origin',403)
    filename=unquote(request.headers.get('x-demo-filename',''))
    if not filename.lower().endswith('.dem') or '/' in filename or '\\' in filename or len(filename)>200 or any(ord(c)<32 for c in filename):
        return failure(request,'invalid_filename',422)
    if request.headers.get('content-type','').split(';')[0] != 'application/octet-stream':
        # Raw bytes remain accepted for local API tests/CLI without a type.
        if request.headers.get('content-type'):
            return failure(request,'unsupported_content_type',415)
    service=request.app.state.demos
    fd,name=tempfile.mkstemp(dir=service.root/'imports',suffix='.upload')
    temporary=Path(name)
    size=0
    digest=hashlib.sha256()
    header=b''
    try:
        with os.fdopen(fd,'wb') as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_DEMO_BYTES: return failure(request,'demo_too_large',413)
                if len(header)<8: header=(header+chunk)[:8]
                stream.write(chunk)
                digest.update(chunk)
        if size < 16 or header != b'PBDEMS2\0': return failure(request,'invalid_demo',422)
        from starlette.concurrency import run_in_threadpool
        demo_id,duplicate=await run_in_threadpool(service.register,temporary,digest.hexdigest(),size,filename)
        return envelope(request,{'job_id':demo_id,'demo_id':demo_id,'duplicate':duplicate},202)
    finally:
        temporary.unlink(missing_ok=True)

@router.get('/demos')
def demos(request:Request):
    service=request.app.state.demos
    with service.database.engine.connect() as conn:
        rows=conn.execute(text('SELECT id,sha256,size,status,created_at FROM demo_files ORDER BY created_at DESC,id DESC LIMIT 100')).mappings().all()
    items=[{**dict(r),'filename':service.read_job(r['id']).get('filename','Demo')} for r in rows]
    return envelope(request,{'items':items})

@router.get('/jobs/{demo_id}')
def job(request:Request,demo_id:str):
    service=request.app.state.demos
    state=service.snapshot(demo_id)
    if state is None: return failure(request,'not_found',404)
    return envelope(request,state)

@router.post('/jobs/{demo_id}/retry')
def retry(request:Request,demo_id:str):
    if request.headers.get('origin') and request.headers['origin'] not in TRUSTED_ORIGINS:
        return failure(request,'untrusted_origin',403)
    try:
        if not request.app.state.demos.retry(demo_id): return failure(request,'not_found',404)
    except AnalysisError:
        return failure(request,'job_not_retryable',409)
    return envelope(request,{'job_id':demo_id},202)

@router.post('/jobs/{demo_id}/cancel')
def cancel(request:Request,demo_id:str):
    if request.headers.get('origin') and request.headers['origin'] not in TRUSTED_ORIGINS:
        return failure(request,'untrusted_origin',403)
    try:
        if not request.app.state.demos.cancel(demo_id):
            return failure(request,'not_found',404)
    except AnalysisError:
        return failure(request,'job_not_cancelable',409)
    return envelope(request,{'job_id':demo_id,'status':'canceled'})

@router.get('/matches/{demo_id}/aim')
def report(request:Request,demo_id:str):
    service=request.app.state.demos
    demo=service.get_demo(demo_id)
    if not demo: return failure(request,'not_found',404)
    if demo['status'] != 'complete': return failure(request,'report_not_ready',409)
    try:
        payload=json.loads((service.root/'reports'/f'{demo_id}.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return failure(request,'report_cache_missing',409)
    return envelope(request,payload)

@router.get('/rounds/{round_id}/events')
def events(request:Request,round_id:str,from_tick:int=0,to_tick:int=2147483647,limit:int=200,cursor:str=''):
    if from_tick<0 or to_tick<from_tick or not 1<=limit<=500 or len(cursor)>100:
        return failure(request,'invalid_tick_range',422)
    db=request.app.state.database
    with db.engine.connect() as conn:
        if not conn.execute(text('SELECT id FROM rounds WHERE id=:id'),{'id':round_id}).first():
            return failure(request,'not_found',404)
        rows=conn.execute(text('SELECT payload FROM events WHERE round_id=:id AND tick BETWEEN :start AND :end AND (tick>:start OR id>:cursor) ORDER BY tick,id LIMIT :limit'),
                          {'id':round_id,'start':from_tick,'end':to_tick,'cursor':cursor,'limit':limit+1}).scalars().all()
    parsed=[json.loads(row) for row in rows[:limit]]
    next_row=parsed[-1] if len(rows)>limit else None
    return envelope(request,{'items':parsed,'next_tick':next_row['tick'] if next_row else None,'next_cursor':next_row['id'] if next_row else None})

@router.get('/matches/{demo_id}/shots')
def shots(request:Request,demo_id:str,player_id:str,round_id:str='',from_tick:int=0,cursor:str='',limit:int=50):
    """Every recorded gun fire, with explicitly limited same-Tick correlations."""
    service=request.app.state.demos
    demo=service.get_demo(demo_id)
    if not demo:return failure(request,'not_found',404)
    if demo['status']!='complete':return failure(request,'report_not_ready',409)
    if from_tick<0 or not 1<=limit<=200 or len(cursor)>100 or len(player_id)>20:
        return failure(request,'invalid_shot_query',422)
    with service.database.engine.connect() as conn:
        params={'demo':demo_id,'player':player_id,'round':round_id,'tick':from_tick,'cursor':cursor,'limit':limit+1}
        rows=conn.execute(text("""SELECT e.payload FROM events e JOIN rounds r ON r.id=e.round_id
            WHERE r.match_id=:demo AND e.actor=:player AND e.type='weapon_fire'
              AND (:round='' OR e.round_id=:round) AND (e.tick>:tick OR (e.tick=:tick AND e.id>:cursor))
            ORDER BY e.tick,e.id LIMIT :limit"""),params).scalars().all()
        selected=[json.loads(row) for row in rows[:limit]]
        context=[]
        if selected:
            context=conn.execute(text("""SELECT e.payload FROM events e JOIN rounds r ON r.id=e.round_id
                WHERE r.match_id=:demo AND e.actor=:player AND e.tick BETWEEN :start AND :end
                AND e.type IN ('weapon_fire','player_hurt','player_death','bullet_impact') ORDER BY e.tick,e.id"""),
                {'demo':demo_id,'player':player_id,'start':selected[0]['tick'],'end':selected[-1]['tick']}).scalars().all()
    from collections import defaultdict
    grouped=defaultdict(list)
    for row in context:
        event=json.loads(row)
        grouped[(event['round_id'],event['tick'])].append(event)
    result=[]
    for shot in selected:
        related=grouped[(shot['round_id'],shot['tick'])]
        fire_count=sum(e['type']=='weapon_fire' for e in related)
        damage=[e for e in related if e['type']=='player_hurt' and e['weapon']==shot['weapon']]
        impacts=[e for e in related if e['type']=='bullet_impact']
        result.append({**shot,'correlation':'same_tick_only' if fire_count==1 else 'ambiguous_multiple_fires',
            'same_tick_damage':sum(e['damage'] for e in damage) if fire_count==1 and damage else None,
            'damage_events':damage if fire_count==1 else [],'impact_events':impacts if fire_count==1 else [],
            'moving_observation':None if shot['speed'] is None else shot['speed']>34,
            'hit_verdict':'unknown','aim_error_degrees':None,'reaction_time_ms':None,
            'limitations':['同Tick相关事件不是已校验的弹道归因；无伤害事件不等于未命中',
                           '多次开火在同Tick时不将伤害或弹着点强行分配给某一枪']})
    last=selected[-1] if len(rows)>limit else None
    return envelope(request,{'items':result,'next_tick':last['tick'] if last else None,'next_cursor':last['id'] if last else None,
                             'granularity':'weapon_fire_event','rule_version':'shot-evidence-v1'})
