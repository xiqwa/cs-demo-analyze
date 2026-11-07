from concurrent.futures import ThreadPoolExecutor
import json
from fastapi.testclient import TestClient
from app import create_app
from roundmind.schemas import HealthResponse
from roundmind.database import Database


def test_health_contract(client):
    response = client.get('/api/v1/health')
    assert response.status_code == 200
    body = HealthResponse.model_validate(response.json())
    assert body.data.status == 'ok'
    assert body.data.database.status == 'ready'
    assert body.data.database.schema_revision == '0001_initial'
    assert str(body.meta.request_id) == response.headers['x-request-id']
    assert body.meta.request_id.version == 4


def test_error_contract(client):
    response = client.get('/api/v1/not-implemented')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'not_found'
    assert response.json()['request_id'] == response.headers['x-request-id']


def test_untrusted_origin_denied(client):
    response = client.options('/api/v1/health', headers={'Origin':'https://untrusted.example', 'Access-Control-Request-Method':'GET'})
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers


def test_local_origin_allowed(client):
    response = client.get('/api/v1/health', headers={'Origin':'http://localhost:5173'})
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'


def test_health_no_recreate_deleted_database(client, settings):
    settings.database_path.unlink()
    response = client.get('/api/v1/health')
    assert response.status_code == 503
    assert response.json()['data']['database']['status'] == 'unavailable'
    assert not settings.database_path.exists()


def test_health_unknown_revision_is_not_exposed(client, settings):
    with Database(settings).engine.begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num = 'private-secret-version'")
    response = client.get('/api/v1/health')
    assert response.status_code == 503
    assert response.json()['data']['database']['status'] == 'schema_mismatch'
    assert response.json()['data']['database']['schema_revision'] is None
    assert 'private-secret' not in response.text


def test_startup_check_fails_before_serving(settings):
    import pytest
    from dataclasses import replace
    with pytest.raises(RuntimeError, match='schema_mismatch'):
        with TestClient(create_app(replace(settings, migration_mode='check'))):
            pass
    assert not settings.database_path.exists()


def test_request_ids_and_logs_are_isolated(client, settings):
    def request(_):
        return client.get('/api/v1/health', headers={'X-Request-ID':'untrusted-injected'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(request, range(8)))
    ids = [response.headers['x-request-id'] for response in responses]
    assert len(set(ids)) == 8
    rows = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    completed = [row for row in rows if row['event'] == 'request_completed']
    assert {row['request_id'] for row in completed} == set(ids)
    assert 'untrusted-injected' not in settings.log_path.read_text()


def test_unhandled_error_is_redacted_and_correlated(settings):
    app = create_app(settings)
    @app.get('/explode')
    def explode():
        raise RuntimeError('api_key=private-value /home/private/demo.dem')
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/explode?token=query-private')
    assert response.status_code == 500
    assert response.headers['x-request-id'] == response.json()['request_id']
    assert response.json()['error']['code'] == 'internal_error'
    logs = settings.log_path.read_text()
    assert 'private-value' not in logs and 'query-private' not in logs and '/home/private' not in logs
    assert response.headers['x-request-id'] in logs


def test_openapi_and_committed_health_schema_match(client):
    from pathlib import Path
    expected = json.loads((Path(__file__).resolve().parents[3] / 'docs' / 'health-response.schema.json').read_text())
    assert expected == HealthResponse.model_json_schema()
    schema = client.get('/openapi.json').json()
    responses = schema['paths']['/api/v1/health']['get']['responses']
    assert responses['200']['content']['application/json']['schema']['$ref'].endswith('/HealthResponse')
    assert responses['503']['content']['application/json']['schema']['$ref'].endswith('/HealthResponse')


def test_query_headers_and_unknown_paths_are_not_logged(client, settings):
    client.get('/private-demo-path.dem?api_key=query-secret', headers={
        'Authorization':'Bearer header-secret', 'Cookie':'session=cookie-secret'})
    logs = settings.log_path.read_text()
    assert 'private-demo-path' not in logs
    assert 'query-secret' not in logs and 'header-secret' not in logs and 'cookie-secret' not in logs
    assert '<unmatched>' in logs
