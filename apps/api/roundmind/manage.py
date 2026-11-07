"""Run from repo root with PYTHONPATH=apps/api python -m roundmind.manage."""
import argparse
import json
import logging
from pathlib import Path
from .config import Settings, HEAD_REVISION
from .database import Database, MigrationError
from .diagnostics import export_diagnostics
from .logging import LogSession


def parser():
    cli = argparse.ArgumentParser(description='RoundMind local database and diagnostics')
    commands = cli.add_subparsers(dest='command', required=True)
    db = commands.add_parser('db').add_subparsers(dest='action', required=True)
    db.add_parser('upgrade')
    db.add_parser('current')
    down = db.add_parser('downgrade')
    down.add_argument('revision', choices=['base'])
    down.add_argument('--allow-data-loss', action='store_true')
    diag = commands.add_parser('diagnostics').add_subparsers(dest='action', required=True)
    export = diag.add_parser('export')
    export.add_argument('--output', type=Path, required=True)
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command == 'db' and args.action == 'downgrade' and not args.allow_data_loss:
        cli.error('downgrade requires --allow-data-loss')
    logs = None
    db = None
    try:
        settings = Settings.from_env()
        logs = LogSession(settings, console_only=True)
        if args.command == 'diagnostics':
            manifest = export_diagnostics(settings, args.output)
            logs.emit('diagnostics_exported', details={'record_count':manifest['record_count']})
            result = {'status':'exported', 'record_count':manifest['record_count']}
        else:
            db = Database(settings)
            if args.action == 'upgrade':
                db.upgrade()
            elif args.action == 'downgrade':
                db.downgrade(args.revision)
            revision = db.current_revision()
            safe_revision = revision if revision == HEAD_REVISION else None
            if args.action != 'current':
                logs.emit('migration_completed', revision=safe_revision, details={'direction':args.action})
            result = {'schema_revision':safe_revision, 'expected_revision':HEAD_REVISION,
                      'status':'ready' if revision == HEAD_REVISION else 'schema_mismatch'}
        print(json.dumps({'data':result}))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, MigrationError) else (
            'output_exists' if isinstance(exc, FileExistsError) else 'operation_failed')
        if logs is not None:
            logs.emit('migration_failed' if args.command == 'db' else 'external_log',
                      level=logging.ERROR, error_code=code)
        print(json.dumps({'error':{'code':code,'message':'Local operation failed','retryable':False}}))
        return 1
    finally:
        if db is not None:
            db.close()
        if logs is not None:
            logs.close()


if __name__ == '__main__':
    raise SystemExit(main())
