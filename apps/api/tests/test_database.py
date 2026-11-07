import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from roundmind.database import Database, MigrationError
from roundmind.config import Settings


def test_paths_are_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv('ROUNDMIND_DATA_DIR', str(tmp_path / 'custom'))
    settings = Settings.from_env()
    monkeypatch.chdir(tmp_path)
    assert Settings.from_env().database_path == settings.database_path
    monkeypatch.setenv('ROUNDMIND_DATA_DIR', 'relative')
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.setenv('ROUNDMIND_MIGRATION_MODE', 'force')
    with pytest.raises(ValueError):
        Settings.from_env()


def test_default_linux_path(monkeypatch, tmp_path):
    monkeypatch.delenv('ROUNDMIND_DATA_DIR', raising=False)
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    assert Settings.from_env(platform='linux').data_dir == tmp_path / 'RoundMind'


def test_upgrade_idempotent_and_pragmas(settings):
    db = Database(settings)
    try:
        db.upgrade()
        with db.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO demo_files (id, sha256, path, size) VALUES ('d1', ?, 'test.dem', 1)", ('a' * 64,))
        db.upgrade()
        assert db.current_revision() == '0001_initial'
        for _ in range(2):
            with db.engine.connect() as conn:
                assert conn.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
                assert conn.exec_driver_sql('PRAGMA journal_mode').scalar() == 'wal'
                assert conn.exec_driver_sql('PRAGMA busy_timeout').scalar() == 5000
                assert conn.exec_driver_sql('PRAGMA synchronous').scalar() == 1
                assert conn.exec_driver_sql('SELECT COUNT(*) FROM demo_files').scalar() == 1
                assert {'demo_files','matches','rounds','events'} <= set(inspect(conn).get_table_names())
        with pytest.raises(IntegrityError):
            with db.engine.begin() as conn:
                conn.exec_driver_sql("INSERT INTO matches (id, demo_id, map) VALUES ('m', 'missing', 'de_mirage')")
        with pytest.raises(IntegrityError):
            with db.engine.begin() as conn:
                conn.exec_driver_sql("INSERT INTO demo_files (id, sha256, path, size) VALUES ('d2', ?, 'other.dem', 1)", ('a' * 64,))
    finally:
        db.close()


def test_downgrade_and_upgrade(settings):
    db = Database(settings)
    db.upgrade()
    db.downgrade('base')
    assert db.current_revision() is None
    with db.engine.connect() as conn:
        assert not {'demo_files','matches','rounds','events'} & set(inspect(conn).get_table_names())
    db.upgrade()
    assert db.current_revision() == '0001_initial'
    db.close()


def test_failed_migration_rolls_back_ddl_data_and_version(settings, tmp_path):
    db = Database(settings)
    db.upgrade()
    scripts = tmp_path / 'migrations'
    shutil.copytree(db.script_location, scripts)
    (scripts / 'versions' / '0002_failure.py').write_text('''from alembic import op
revision = '0002_failure'
down_revision = '0001_initial'
def upgrade():
    op.execute('CREATE TABLE should_rollback (id INTEGER)')
    op.execute("INSERT INTO demo_files (id, sha256, path, size) VALUES ('rollback', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'fixture.dem', 1)")
    raise RuntimeError('deliberate test failure')
def downgrade():
    pass
''')
    db.script_location = scripts
    with pytest.raises(MigrationError, match='migration_failed'):
        db.upgrade()
    assert db.current_revision() == '0001_initial'
    with db.engine.connect() as conn:
        assert 'should_rollback' not in inspect(conn).get_table_names()
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM demo_files').scalar() == 0
    db.close()


def test_unknown_and_unmanaged_schema_not_overwritten(settings):
    db = Database(settings)
    db.prepare()
    with db.engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE valuable (id INTEGER)')
    with pytest.raises(MigrationError, match='unmanaged_database'):
        db.upgrade()
    with db.engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE valuable')
    db.upgrade()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num='future_version'")
    with pytest.raises(MigrationError):
        db.upgrade()
    assert db.current_revision() == 'future_version'
    db.close()


def test_parallel_upgrade_serializes(settings):
    def upgrade(_):
        db = Database(settings)
        try:
            db.upgrade()
            return db.current_revision()
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(upgrade, range(2))) == ['0001_initial'] * 2


def test_check_mode_does_not_upgrade(settings):
    db = Database(replace(settings, migration_mode='check'))
    with pytest.raises(MigrationError, match='schema_mismatch'):
        db.initialize()
    assert not settings.database_path.exists()
    db.close()


def test_failed_initial_migration_leaves_no_tables(settings, tmp_path):
    db = Database(settings)
    scripts = tmp_path / 'initial_failure'
    shutil.copytree(db.script_location, scripts)
    path = scripts / 'versions' / '0001_initial.py'
    path.write_text(path.read_text().replace("    op.create_index('ix_demo_files_status'", "    raise RuntimeError('initial failure')\n    op.create_index('ix_demo_files_status'"))
    db.script_location = scripts
    with pytest.raises(MigrationError, match='migration_failed'):
        db.upgrade()
    assert db.current_revision() is None
    with db.engine.connect() as conn:
        assert inspect(conn).get_table_names() == []
    db.close()


def test_failed_downgrade_restores_tables_and_revision(settings, tmp_path):
    db = Database(settings)
    db.upgrade()
    scripts = tmp_path / 'downgrade_failure'
    shutil.copytree(db.script_location, scripts)
    path = scripts / 'versions' / '0001_initial.py'
    path.write_text(path.read_text().replace("    op.drop_table('rounds')", "    raise RuntimeError('downgrade failure')\n    op.drop_table('rounds')"))
    db.script_location = scripts
    with pytest.raises(MigrationError, match='migration_failed'):
        db.downgrade('base')
    assert db.current_revision() == '0001_initial'
    with db.engine.connect() as conn:
        assert {'demo_files','matches','rounds','events'} <= set(inspect(conn).get_table_names())
    db.close()


def test_posix_new_files_are_private(settings):
    import os
    import stat
    if os.name != 'posix':
        pytest.skip('Windows permissions use ACLs')
    db = Database(settings)
    db.upgrade()
    assert stat.S_IMODE(settings.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(settings.database_path.stat().st_mode) == 0o600
    db.close()


def test_defaults_windows_macos(monkeypatch, tmp_path):
    monkeypatch.delenv('ROUNDMIND_DATA_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    assert Settings.from_env(platform='win32').data_dir == tmp_path / 'local' / 'RoundMind'
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    assert Settings.from_env(platform='darwin').data_dir == tmp_path / 'Library' / 'Application Support' / 'RoundMind'


def test_missing_version_row_does_not_adopt_existing_tables(settings):
    db = Database(settings)
    db.upgrade()
    with db.engine.begin() as conn:
        conn.exec_driver_sql('DELETE FROM alembic_version')
    with pytest.raises(MigrationError, match='unmanaged_database'):
        db.upgrade()
    db.close()
