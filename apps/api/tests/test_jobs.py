"""Task lifecycle fixtures, not real Demo/metric validation."""
from threading import Event
import subprocess
import sys
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app import create_app
from roundmind.aim import AnalysisError, build_report
from roundmind.imports import DemoService


def upload(client, suffix=b'A'):
    response=client.post('/api/v1/demos/import',content=b'PBDEMS2\0'+suffix*32,
                         headers={'X-Demo-Filename':'synthetic-lifecycle.dem'})
    assert response.status_code==202
    return response.json()['data']['job_id']


def wait_for(client,job_id,status):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=client.get('/api/v1/jobs/'+job_id).json()['data']
        if state['status']==status:return state
        time.sleep(.01)
    pytest.fail(f'Expected {status}, got {state}')


def fixture_report(demo_id):
    from test_aim import fixture_events
    report=build_report(demo_id,'a'*64,{},fixture_events(),[])
    report['data_origin']='synthetic_fixture'
    return report


def test_queued_cancel_is_idempotent_and_never_parses(settings,monkeypatch):
    started=Event(); release=Event(); calls=[]
    def controlled(self,demo_id,source,output,**kwargs):
        calls.append(demo_id);started.set()
        assert release.wait(5)
        raise AnalysisError('unsupported_or_corrupt_demo')
    monkeypatch.setattr(DemoService,'parse_subprocess',controlled)
    with TestClient(create_app(settings)) as client:
        first=upload(client,b'A')
        assert started.wait(5)
        second=upload(client,b'B')
        try:
            for _ in range(2):
                response=client.post('/api/v1/jobs/'+second+'/cancel')
                assert response.status_code==200
                assert response.json()['data']['status']=='canceled'
            assert wait_for(client,second,'canceled')['attempt']==1
            assert second not in calls
            assert client.get('/api/v1/matches/'+second+'/aim').status_code==409
        finally:release.set()
        wait_for(client,first,'failed')
        assert client.post('/api/v1/jobs/'+first+'/cancel').status_code==409
    assert calls==[first]


def test_cancel_retry_old_attempt_cannot_overwrite_new_result(settings,monkeypatch):
    started=Event(); release=Event(); calls=[]
    def controlled(self,demo_id,source,output,**kwargs):
        calls.append(kwargs['attempt'].id)
        if len(calls)==1:
            started.set()
            assert release.wait(5)
        # A late successful parser result from a canceled attempt must be ignored.
        return fixture_report(demo_id)
    monkeypatch.setattr(DemoService,'parse_subprocess',controlled)
    with TestClient(create_app(settings)) as client:
        job_id=upload(client)
        assert started.wait(5)
        original=client.get('/api/v1/jobs/'+job_id).json()['data']
        try:
            assert client.post('/api/v1/jobs/'+job_id+'/cancel').status_code==200
            assert client.post('/api/v1/jobs/'+job_id+'/retry').status_code==202
            newer=client.get('/api/v1/jobs/'+job_id).json()['data']
            assert newer['attempt']==2 and newer['attempt_id']!=original['attempt_id']
            assert newer['status']=='queued'
        finally:release.set()
        done=wait_for(client,job_id,'complete')
        assert done['attempt_id']==newer['attempt_id']
        assert len(calls)==2
        with client.app.state.database.engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM matches')).scalar()==1
        assert client.post('/api/v1/jobs/'+job_id+'/cancel').status_code==409


def test_cancel_terminates_real_child(settings,monkeypatch):
    import roundmind.imports as jobs
    real_popen=subprocess.Popen
    started=Event(); children=[]
    def controlled_popen(*args,**kwargs):
        child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        children.append(child);started.set();return child
    monkeypatch.setattr(jobs.subprocess,'Popen',controlled_popen)
    with TestClient(create_app(settings)) as client:
        job_id=upload(client)
        assert started.wait(5)
        assert client.post('/api/v1/jobs/'+job_id+'/cancel').status_code==200
        assert children[0].wait(timeout=5)!=0
        assert wait_for(client,job_id,'canceled')['error_code'] is None
    assert children[0].poll() is not None


def test_cancel_access_and_terminal_conflicts(client):
    assert client.post('/api/v1/jobs/unknown/cancel').status_code==404
    response=client.post('/api/v1/jobs/unknown/cancel',headers={'Origin':'https://untrusted.example'})
    assert response.status_code==403


def test_restart_keeps_canceled_state_and_retry_count(settings,monkeypatch):
    started=Event();release=Event()
    def controlled(self,demo_id,source,output,**kwargs):
        started.set();assert release.wait(5)
        raise AnalysisError('unsupported_or_corrupt_demo')
    monkeypatch.setattr(DemoService,'parse_subprocess',controlled)
    with TestClient(create_app(settings)) as client:
        first=upload(client,b'A');assert started.wait(5)
        canceled=upload(client,b'B')
        try:
            assert client.post('/api/v1/jobs/'+canceled+'/cancel').status_code==200
            before=wait_for(client,canceled,'canceled')
        finally:release.set()
        wait_for(client,first,'failed')
    with TestClient(create_app(settings)) as client:
        assert wait_for(client,canceled,'canceled')['attempt_id']==before['attempt_id']
        assert client.post('/api/v1/jobs/'+canceled+'/retry').status_code==202
        state=client.get('/api/v1/jobs/'+canceled).json()['data']
        assert state['attempt']==2 and state['attempt_id']!=before['attempt_id']
        assert len(client.get('/api/v1/demos').json()['data']['items'])==2


def test_commit_wins_over_late_cancel_without_partial_report(settings,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    committing=Event();release=Event()
    original=DemoService.atomic_json
    def fixture_parser(self,demo_id,source,output,**kwargs):return fixture_report(demo_id)
    def controlled_save(self,path,data):
        if path.parent.name=='reports' and path.suffix=='.json':
            committing.set();assert release.wait(5)
        return original(self,path,data)
    monkeypatch.setattr(DemoService,'parse_subprocess',fixture_parser)
    monkeypatch.setattr(DemoService,'atomic_json',controlled_save)
    with TestClient(create_app(settings)) as client:
        job_id=upload(client)
        assert committing.wait(5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            late=pool.submit(client.post,'/api/v1/jobs/'+job_id+'/cancel')
            release.set()
            assert late.result(timeout=5).status_code==409
        assert wait_for(client,job_id,'complete')['status']=='complete'
        assert client.get('/api/v1/matches/'+job_id+'/aim').status_code==200


def test_shutdown_reaps_child_and_marks_queued_interrupted(settings,monkeypatch):
    import roundmind.imports as jobs
    from roundmind.database import Database
    real_popen=subprocess.Popen
    started=Event();children=[]
    def controlled_popen(*args,**kwargs):
        child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        children.append(child);started.set();return child
    monkeypatch.setattr(jobs.subprocess,'Popen',controlled_popen)
    with TestClient(create_app(settings)) as client:
        first=upload(client,b'A');assert started.wait(5)
        second=upload(client,b'B')
    assert len(children)==1 and children[0].poll() is not None
    db=Database(settings)
    try:
        with db.engine.connect() as conn:
            statuses=conn.execute(text('SELECT status FROM demo_files WHERE id IN (:first,:second)'),{'first':first,'second':second}).scalars().all()
        assert statuses==['failed','failed']
    finally:db.close()
    import json
    for job_id in [first,second]:
        job=json.loads((settings.data_dir/'jobs'/f'{job_id}.json').read_text())
        assert job['error_code']=='interrupted'
