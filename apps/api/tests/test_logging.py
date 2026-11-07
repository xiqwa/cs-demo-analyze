import json
import logging
import zipfile
from dataclasses import replace
from uuid import uuid4
from roundmind.logging import JsonFormatter, LogSession, redact, request_id_var
from roundmind.diagnostics import export_diagnostics


def test_recursive_redaction():
    value = {'API_KEY': 'secret-one', 'nested': {'access_token':'secret-two', 'Authorization':'Bearer secret-three'},
             'items':[{'password':'secret-four'}, 'Bearer secret-five', 'api_key=secret-six',
                      '/home/alice/demo.dem', r'C:\Users\alice\demo.dem', r'\\server\alice\demo.dem',
                      'https://host.example/api?token=secret-seven', 'sk-proj-abcdefghijk']}
    result = json.dumps(redact(value))
    for secret in ['secret-one','secret-two','secret-three','secret-four','secret-five','secret-six','secret-seven','alice','abcdefghijk']:
        assert secret not in result


def test_json_formatter_no_raw_exception_or_newline():
    record = logging.LogRecord('external', logging.ERROR, '/home/private/source.py', 1,
                               'token=private-value\ninjected', (), None)
    record.exc_info = (RuntimeError, RuntimeError('secret'), None)
    result = json.loads(JsonFormatter().format(record))
    assert result['event'] == 'external_log'
    assert 'private-value' not in json.dumps(result)
    assert result['request_id'] is None
    assert 'timestamp' in result


def test_rotation_and_context_reset(settings):
    settings = replace(settings, log_max_bytes=700, log_backup_count=2)
    session = LogSession(settings)
    token = request_id_var.set(str(uuid4()))
    try:
        session.emit('request_completed', status_code=200, details={'api_key':'never-visible'})
    finally:
        request_id_var.reset(token)
    for _ in range(35):
        session.emit('startup_ready', details={'note':'x'*40})
    session.close()
    files = list(settings.log_path.parent.glob('roundmind.jsonl*'))
    assert 1 <= len(files) <= 3
    assert settings.log_path.with_name('roundmind.jsonl.1').exists()
    for path in files:
        assert path.stat().st_size <= 700
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert row['request_id'] is None
            assert 'never-visible' not in line


def test_diagnostics_re_redacts_and_excludes_database(settings, tmp_path):
    settings.log_path.parent.mkdir(parents=True)
    settings.log_path.write_text(json.dumps({'timestamp':'2026-11-07T00:00:00Z','level':'ERROR','event':'request_completed',
        'request_id':None,'details':{'api_key':'old-secret','path':'/home/private/demo.dem'},'raw_body':'do-not-export'})+'\ninvalid\n{"unfinished":')
    settings.database_path.parent.mkdir(parents=True)
    settings.database_path.write_bytes(b'private database data')
    archive = tmp_path / 'diagnostics.zip'
    export_diagnostics(settings, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {'manifest.json','logs.jsonl'}
        logs = bundle.read('logs.jsonl').decode()
        assert 'old-secret' not in logs and '/home/private' not in logs
        assert 'do-not-export' not in logs
        manifest = json.loads(bundle.read('manifest.json'))
        assert manifest['record_count'] == 1
        assert manifest['skipped_lines'] >= 1
    import pytest
    with pytest.raises(FileExistsError):
        export_diagnostics(settings, archive)


def test_diagnostics_does_not_follow_symlinks(settings, tmp_path):
    import os
    import pytest
    target = tmp_path / 'private.txt'
    target.write_text('{"event":"private"}\n')
    settings.log_path.parent.mkdir(parents=True)
    try:
        os.symlink(target, settings.log_path)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks unavailable on this platform')
    archive = tmp_path / 'diag.zip'
    export_diagnostics(settings, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read('logs.jsonl') == b''


def test_oversized_log_remains_bounded_json(settings):
    session = LogSession(replace(settings, log_max_bytes=700))
    session.emit('request_completed', details={'huge':['中' * 1024] * 50})
    session.close()
    raw = settings.log_path.read_bytes()
    assert len(raw) <= 700
    assert json.loads(raw)['details']['truncated'] is True


def test_export_record_count_is_bounded(settings, tmp_path):
    settings.log_path.parent.mkdir(parents=True)
    row = json.dumps({'timestamp':'2026-11-07T00:00:00Z','level':'INFO','event':'startup_ready','request_id':None})
    settings.log_path.write_text((row + '\n') * 1200)
    archive = tmp_path / 'bounded.zip'
    manifest = export_diagnostics(settings, archive)
    assert manifest['record_count'] == 1000


def test_embedded_json_credentials_and_basic_auth_are_redacted():
    result = redact('context {"api_key": "embedded-private", "password": "two words"} Basic cHJpdmF0ZQ==')
    assert 'embedded-private' not in result
    assert 'two words' not in result
    assert 'cHJpdmF0ZQ==' not in result


def test_logging_io_failure_does_not_dump_raw_record(settings, monkeypatch, capsys):
    session = LogSession(settings)
    def failed_rollover(record):
        raise OSError('/home/private api_key=raw-secret')
    monkeypatch.setattr(session.handler, 'shouldRollover', failed_rollover)
    session.emit('request_completed', details={'api_key':'record-secret'})
    session.close()
    stderr = capsys.readouterr().err
    assert json.loads(stderr)['event'] == 'log_write_failed'
    assert 'raw-secret' not in stderr and 'record-secret' not in stderr and '/home/private' not in stderr


def test_unicode_rotation_respects_byte_limit(settings):
    session = LogSession(replace(settings, log_max_bytes=700))
    for _ in range(20):
        session.emit('startup_ready', details={'note':'中' * 55})
    session.close()
    for path in settings.log_path.parent.glob('roundmind.jsonl*'):
        assert path.stat().st_size <= 700
