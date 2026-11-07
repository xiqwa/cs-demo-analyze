import time
from fastapi.testclient import TestClient
from app import create_app
from roundmind.aim import AnalysisError


def test_invalid_demo_never_enqueued(client):
    response=client.post('/api/v1/demos/import', content=b'not-a-demo', headers={'X-Demo-Filename':'test.dem'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'invalid_demo'
    assert client.get('/api/v1/demos').json()['data']['items'] == []


def test_untrusted_origin_cannot_submit(client):
    response=client.post('/api/v1/demos/import', content=b'PBDEMS2\0'+b'\0'*16,
                         headers={'Origin':'https://evil.example','X-Demo-Filename':'test.dem'})
    assert response.status_code == 403


def test_extension_and_empty_files_rejected(client):
    assert client.post('/api/v1/demos/import',content=b'PBDEMS2\0'+b'\0'*16,
                       headers={'X-Demo-Filename':'fake.zip'}).status_code == 422
    assert client.post('/api/v1/demos/import',content=b'',headers={'X-Demo-Filename':'empty.dem'}).status_code == 422


def test_duplicate_hash_failure_retry_and_no_fake_report(settings,monkeypatch):
    from roundmind.imports import DemoService
    def fail(self, demo_id, source, output, **kwargs):
        raise AnalysisError('unsupported_or_corrupt_demo')
    monkeypatch.setattr(DemoService,'parse_subprocess',fail)
    with TestClient(create_app(settings)) as client:
        def upload(name):
            return client.post('/api/v1/demos/import', content=b'PBDEMS2\0'+b'\0'*32,headers={'X-Demo-Filename':name})
        first=upload('synthetic-test.dem')
        assert first.status_code == 202
        demo_id=first.json()['data']['demo_id']
        duplicate=upload('renamed-test.dem')
        assert duplicate.json()['data']['duplicate'] is True
        assert duplicate.json()['data']['demo_id'] == demo_id
        for _ in range(100):
            job=client.get('/api/v1/jobs/'+demo_id).json()['data']
            if job['status']=='failed': break
            time.sleep(.01)
        assert job['status']=='failed'
        assert job['error_code']=='unsupported_or_corrupt_demo'
        assert client.get('/api/v1/matches/'+demo_id+'/aim').status_code == 409
        assert len(client.get('/api/v1/demos').json()['data']['items']) == 1
        assert client.post('/api/v1/jobs/'+demo_id+'/retry').status_code == 202


def test_golden_demo_optional(tmp_path):
    import json,os,pytest
    from pathlib import Path
    from roundmind.parser import parse_demo
    path=os.environ.get('ROUNDMIND_GOLDEN_DEMO')
    if not path:
        pytest.skip('No authorized real golden Demo supplied; synthetic fixtures do not prove parser accuracy')
    import hashlib
    with Path(path).open('rb') as stream:
        sha256=hashlib.file_digest(stream,'sha256').hexdigest()
    report=parse_demo(Path(path),'golden-id',sha256)
    assert report['players'] and report['rounds']
    baseline=os.environ.get('ROUNDMIND_GOLDEN_BASELINE')
    if baseline:
        expected=json.loads(Path(baseline).read_text())
        for player_id,metrics in expected['players'].items():
            actual=next(p for p in report['players'] if p['player_id']==player_id)
            for key,value in metrics.items(): assert actual[key] == value


def test_complete_flow_indexes_report_and_paginated_evidence(settings,monkeypatch):
    from roundmind.imports import DemoService
    from roundmind.aim import build_report
    from test_aim import fixture_events
    def fixture_parser(self,demo_id,source,output,**kwargs):
        # Isolated test fake; not installed in the application or shipped as a Demo.
        raw=fixture_events()
        report=build_report(demo_id,'a'*64,{'map_name':'de_mirage'},raw,[])
        report['data_origin']='synthetic_fixture'
        return report
    monkeypatch.setattr(DemoService,'parse_subprocess',fixture_parser)
    with TestClient(create_app(settings)) as client:
        imported=client.post('/api/v1/demos/import',content=b'PBDEMS2\0'+b'\0'*32,headers={'X-Demo-Filename':'synthetic-unit-fixture.dem'}).json()['data']
        for _ in range(100):
            job=client.get('/api/v1/jobs/'+imported['job_id']).json()['data']
            if job['status'] in {'complete','failed'}:break
            time.sleep(.01)
        assert job['status']=='complete',job
        response=client.get('/api/v1/matches/'+imported['demo_id']+'/aim')
        assert response.status_code==200
        report=response.json()['data']
        assert report['data_origin']=='synthetic_fixture'
        assert 'events' not in report  # Report doesn't transfer full event data.
        shots=client.get(f"/api/v1/matches/{imported['demo_id']}/shots?player_id=111&limit=1").json()['data']
        assert len(shots['items'])==1
        first_shot=shots['items'][0]
        assert first_shot['tick']==120 and first_shot['same_tick_damage']==80
        assert first_shot['hit_verdict']=='unknown'
        assert first_shot['aim_error_degrees'] is None and first_shot['reaction_time_ms'] is None
        second_page=client.get(f"/api/v1/matches/{imported['demo_id']}/shots?player_id=111&from_tick={shots['next_tick']}&cursor={shots['next_cursor']}&limit=1").json()['data']
        assert second_page['items'][0]['tick']==140
        assert second_page['items'][0]['speed'] is None
        assert second_page['items'][0]['same_tick_damage'] is None
        assert second_page['items'][0]['hit_verdict']=='unknown'
        all_shots=client.get(f"/api/v1/matches/{imported['demo_id']}/shots?player_id=111").json()['data']['items']
        assert [s['tick'] for s in all_shots]==[120,140,160]

        finding=report['players'][0]['findings'][0]
        ref=finding['evidence_refs'][0]
        page=client.get(f"/api/v1/rounds/{ref['round_id']}/events?from_tick={ref['start_tick']}&limit=1").json()['data']
        assert len(page['items'])==1 and page['items'][0]['tick']==120
        assert page['next_tick']==120
        second=client.get(f"/api/v1/rounds/{ref['round_id']}/events?from_tick={page['next_tick']}&cursor={page['next_cursor']}&limit=1").json()['data']
        assert second['items'][0]['id'] != page['items'][0]['id']
        ids=set()
        while page['items']:
            for row in page['items']:
                assert row['id'] not in ids
                ids.add(row['id'])
            if page['next_tick'] is None:break
            page=client.get(f"/api/v1/rounds/{ref['round_id']}/events?from_tick={page['next_tick']}&cursor={page['next_cursor']}&limit=1").json()['data']
        assert len(ids)==6
        assert ref['event_id'] in ids
        assert client.get(f"/api/v1/rounds/{ref['round_id']}/events?limit=501").status_code==422
        assert client.get('/api/v1/rounds/unknown/events').status_code==404
        assert client.post('/api/v1/jobs/'+imported['demo_id']+'/retry').status_code==409


def test_real_native_parser_rejects_corrupt_header_in_subprocess(settings):
    with TestClient(create_app(settings)) as client:
        response=client.post('/api/v1/demos/import',content=b'PBDEMS2\0'+b'\0'*64,
                             headers={'X-Demo-Filename':'deliberately-corrupt.dem'})
        demo_id=response.json()['data']['demo_id']
        for _ in range(200):
            job=client.get('/api/v1/jobs/'+demo_id).json()['data']
            if job['status']=='failed':break
            time.sleep(.05)
        assert job['status']=='failed'
        assert job['error_code'] in {'unsupported_or_corrupt_demo','parser_process_failed'}
        assert client.get('/api/v1/matches/'+demo_id+'/aim').status_code==409


def test_same_tick_multiple_fires_do_not_force_damage_attribution(settings,monkeypatch):
    from roundmind.imports import DemoService
    from roundmind.aim import build_report
    from test_aim import fixture_events
    def fixture_parser(self,demo_id,source,output,**kwargs):
        raw=fixture_events()
        raw['weapon_fire'].append(dict(raw['weapon_fire'][0]))
        return build_report(demo_id,'a'*64,{},raw,[])
    monkeypatch.setattr(DemoService,'parse_subprocess',fixture_parser)
    with TestClient(create_app(settings)) as client:
        demo_id=client.post('/api/v1/demos/import',content=b'PBDEMS2\0'+b'\0'*32,
                            headers={'X-Demo-Filename':'synthetic-ambiguous.dem'}).json()['data']['demo_id']
        for _ in range(100):
            if client.get('/api/v1/jobs/'+demo_id).json()['data']['status']=='complete':break
            time.sleep(.01)
        rows=client.get(f'/api/v1/matches/{demo_id}/shots?player_id=111').json()['data']['items']
        assert len(rows)==4
        ambiguous=[s for s in rows if s['tick']==120]
        assert len(ambiguous)==2
        assert all(s['correlation']=='ambiguous_multiple_fires' and s['same_tick_damage'] is None and s['damage_events']==[] for s in ambiguous)
