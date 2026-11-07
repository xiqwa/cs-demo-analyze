import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

API_ROOT = Path(__file__).resolve().parents[1]


def invoke(settings, *args):
    env = {**os.environ, 'PYTHONPATH':str(API_ROOT), 'ROUNDMIND_DATA_DIR':str(settings.data_dir)}
    return subprocess.run([sys.executable, '-m', 'roundmind.manage', *args], env=env,
                          text=True, capture_output=True, timeout=20)


def test_cli_upgrade_current_downgrade_and_export(settings, tmp_path):
    for args in [('db','upgrade'), ('db','upgrade'), ('db','current')]:
        result = invoke(settings, *args)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['data']['schema_revision'] == '0001_initial'
    blocked = invoke(settings, 'db', 'downgrade', 'base')
    assert blocked.returncode == 2
    assert '--allow-data-loss' in blocked.stderr
    from fastapi.testclient import TestClient
    from app import create_app
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/health').status_code == 200
    archive = tmp_path / 'diagnostics.zip'
    result = invoke(settings, 'diagnostics', 'export', '--output', str(archive))
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(archive) as bundle:
        assert json.loads(bundle.read('manifest.json'))['record_count'] >= 2
    result = invoke(settings, 'diagnostics', 'export', '--output', str(archive))
    assert result.returncode == 1
    assert json.loads(result.stdout)['error']['code'] == 'output_exists'
    assert str(tmp_path) not in result.stdout + result.stderr
    result = invoke(settings, 'db', 'downgrade', 'base', '--allow-data-loss')
    assert result.returncode == 0
    assert json.loads(result.stdout)['data']['schema_revision'] is None
    assert invoke(settings, 'db', 'upgrade').returncode == 0


def test_current_missing_database_is_read_only(settings):
    result = invoke(settings, 'db', 'current')
    assert result.returncode == 1
    assert not settings.database_path.exists()
    assert str(settings.data_dir) not in result.stdout + result.stderr


def test_cli_invalid_data_directory_does_not_leak(tmp_path):
    env = {**os.environ, 'PYTHONPATH':str(API_ROOT), 'ROUNDMIND_DATA_DIR':'relative-private-path'}
    result = subprocess.run([sys.executable,'-m','roundmind.manage','db','upgrade'],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert 'relative-private-path' not in result.stdout + result.stderr
