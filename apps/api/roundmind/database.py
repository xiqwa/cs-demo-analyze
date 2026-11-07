from contextlib import closing
from pathlib import Path
import sqlite3
from time import monotonic, sleep
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.pool import NullPool
from .config import Settings, HEAD_REVISION, private_file


class MigrationError(RuntimeError):
    """Stable public code; never include underlying SQL or filesystem paths."""


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.script_location = Path(__file__).resolve().parents[1] / 'migrations'
        self.engine = create_engine('sqlite://', creator=self._connect, poolclass=NullPool)
        event.listen(self.engine, 'begin', self._begin)

    def _connect(self):
        conn = sqlite3.connect(self.settings.database_path, timeout=5, isolation_level=None)
        try:
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('PRAGMA foreign_keys=ON')
            # Initial WAL promotion can report SQLITE_BUSY without honoring
            # busy_timeout when two processes open an empty database together.
            deadline = monotonic() + 5
            while True:
                try:
                    if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                        raise MigrationError('wal_unavailable')
                    break
                except sqlite3.OperationalError as exc:
                    if (getattr(exc, 'sqlite_errorcode', 0) & 0xff) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or monotonic() >= deadline:
                        raise
                    sleep(0.02)
            conn.execute('PRAGMA synchronous=NORMAL')
            return conn
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def _begin(conn):
        # sqlite3 legacy defaults don't enclose DDL in a transaction. Explicit
        # BEGIN is essential: Alembic's version and every DDL change roll back.
        conn.exec_driver_sql('BEGIN IMMEDIATE' if conn.info.get('migration') else 'BEGIN')

    def prepare(self):
        private_file(self.settings.database_path)

    def current_revision(self) -> str | None:
        # mode=ro prevents a deleted/missing DB from being silently recreated.
        uri = self.settings.database_path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('SELECT 1').fetchone()
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone():
                return None
            rows = conn.execute('SELECT version_num FROM alembic_version').fetchall()
            if len(rows) > 1:
                raise MigrationError('schema_mismatch')
            return rows[0][0] if rows else None

    def health(self) -> dict:
        try:
            revision = self.current_revision()
        except Exception:
            return {'status':'unavailable', 'schema_revision':None, 'expected_revision':HEAD_REVISION}
        ready = revision == HEAD_REVISION
        return {'status':'ready' if ready else 'schema_mismatch',
                'schema_revision':HEAD_REVISION if ready else None, 'expected_revision':HEAD_REVISION}

    def initialize(self):
        if self.settings.migration_mode == 'auto':
            self.upgrade()
        if self.health()['status'] != 'ready':
            raise MigrationError('schema_mismatch')

    def _migrate(self, direction: str, revision: str):
        try:
            self.prepare()
            with self.engine.connect() as conn:
                conn.info['migration'] = True
                with conn.begin():
                    tables = set(inspect(conn).get_table_names())
                    versioned = 'alembic_version' in tables and conn.exec_driver_sql('SELECT version_num FROM alembic_version').first() is not None
                    if tables - {'alembic_version'} and not versioned:
                        raise MigrationError('unmanaged_database')
                    config = Config()
                    config.set_main_option('script_location', str(self.script_location).replace('%', '%%'))
                    config.attributes['connection'] = conn
                    if direction == 'upgrade':
                        command.upgrade(config, revision)
                    else:
                        command.downgrade(config, revision)
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError('migration_failed') from exc

    def upgrade(self):
        self._migrate('upgrade', 'head')

    def downgrade(self, revision: str):
        if revision != 'base':
            raise MigrationError('unsupported_downgrade_target')
        self._migrate('downgrade', revision)

    def close(self):
        self.engine.dispose()
