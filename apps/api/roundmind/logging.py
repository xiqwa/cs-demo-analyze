"""Bounded structured records only; never persist raw request/exception text."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import sys
from pathlib import Path
from uuid import uuid4
from .config import Settings, private_file

request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)
EVENTS = frozenset({'request_completed', 'startup_ready', 'startup_failed', 'shutdown',
                    'migration_completed', 'migration_failed', 'diagnostics_exported', 'external_log', 'log_write_failed'})
FIELDS = frozenset({'method', 'route', 'status_code', 'duration_ms', 'error_code', 'revision', 'details'})
PUBLIC_ROUTES = frozenset({'/api/v1/health', '/api/v1/demos', '/api/v1/demos/import', '/api/v1/jobs/{demo_id}', '/api/v1/jobs/{demo_id}/retry', '/api/v1/jobs/{demo_id}/cancel', '/api/v1/matches/{demo_id}/aim', '/api/v1/matches/{demo_id}/shots', '/api/v1/rounds/{round_id}/events', '/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json', '<unmatched>'})
SENSITIVE_KEY = re.compile(r'token|secret|password|passwd|cookie|authorization|credential|apikey', re.I)
URL = re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s<>"\']+', re.I)
BEARER = re.compile(r'\b(?:Bearer|Basic)\s+[^\s,;"\']+', re.I)
API_KEY = re.compile(r'\bsk-[A-Za-z0-9_-]{8,}\b')
ASSIGNMENT = re.compile(r'''(?ix)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)[\"']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;&]+)''')
PATH = re.compile(r'''(?ix)(?:[a-z]:[\\/][^\s"'<>|,;]*|\\\\[^\s"'<>|,;]+|(?<![\w:])/(?:[^\s"'<>|,;]+))''')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def redact(value, *, depth=0):
    if depth > 6:
        return '[TRUNCATED]'
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:50]:
            key = str(key)
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            safe_key = redact(key, depth=depth + 1)
            result[safe_key] = '[REDACTED]' if SENSITIVE_KEY.search(normalized) else redact(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        value = BEARER.sub('Bearer [REDACTED]', value)
        value = ASSIGNMENT.sub('[REDACTED_CREDENTIAL]', value)
        value = API_KEY.sub('[REDACTED_KEY]', value)
        value = URL.sub('[REDACTED_URL]', value)
        if re.match(r'^(?:/|[A-Za-z]:[\\/]|\\\\)', value):
            return '[REDACTED_PATH]'
        value = PATH.sub('[REDACTED_PATH]', value)
        return value[:1024]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float('inf') else None
    return '[UNSUPPORTED]'


def safe_record(row: dict) -> dict:
    """Reconstruct the allowlisted schema, also used for legacy log export."""
    event = row.get('event')
    result = {'timestamp': redact(row.get('timestamp')),
              'level': row.get('level') if row.get('level') in {'INFO','WARNING','ERROR','DEBUG','CRITICAL'} else 'INFO',
              'event': event if isinstance(event, str) and event in EVENTS else 'external_log',
              'request_id': None}
    try:
        from uuid import UUID
        if row.get('request_id') is not None:
            result['request_id'] = str(UUID(str(row['request_id'])))
    except (ValueError, TypeError, AttributeError):
        pass
    for key in FIELDS:
        if key in row:
            if key == 'route':
                result[key] = row[key] if isinstance(row[key], str) and row[key] in PUBLIC_ROUTES else '<unmatched>'
            else:
                result[key] = redact(row[key])
    return result


class JsonFormatter(logging.Formatter):
    def __init__(self, max_record_bytes=16384):
        super().__init__()
        self.max_record_bytes = max_record_bytes

    def format(self, record):
        event = getattr(record, 'rm_event', 'external_log')
        row = {'timestamp': utc_now(), 'level': record.levelname, 'event':event,
               'request_id': request_id_var.get()}
        row.update({key:value for key, value in getattr(record, 'rm_fields', {}).items() if key in FIELDS})
        # Ignore getMessage(), exc_info and stack_info, even for third-party logs.
        safe = safe_record(row)
        encoded = json.dumps(safe, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if len((encoded + '\n').encode('utf-8')) > self.max_record_bytes:
            # Keep essential correlation, discard oversized optional context.
            safe = {key:value for key, value in safe.items() if key in {'timestamp','level','event','request_id'}}
            safe['details'] = {'truncated':True}
            encoded = json.dumps(safe, ensure_ascii=False, separators=(',', ':'))
        return encoded


class PrivateRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # logging's default fallback prints raw record arguments and traceback.
        # A failed disk write must never fall back to dumping sensitive context.
        sys.stderr.write(json.dumps({'timestamp':utc_now(), 'level':'ERROR', 'event':'log_write_failed',
                                     'request_id':request_id_var.get()}) + '\n')

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        if self.maxBytes <= 0:
            return False
        self.stream.seek(0, 2)
        size = self.stream.tell()
        # stdlib counts characters for the new record, which undercounts UTF-8.
        encoded_size = len((self.format(record) + '\n').encode('utf-8'))
        return size > 0 and size + encoded_size > self.maxBytes

    def _open(self):
        private_file(Path(self.baseFilename))
        return super()._open()


class LogSession:
    def __init__(self, settings: Settings, *, console_only=False):
        if not console_only:
            private_file(settings.log_path)
        self.logger = logging.getLogger('roundmind.session.' + uuid4().hex)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = logging.StreamHandler(sys.stderr) if console_only else PrivateRotatingHandler(
            settings.log_path, maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count, encoding='utf-8')
        self.handler.setFormatter(JsonFormatter(max_record_bytes=min(16384, settings.log_max_bytes - 1)))
        self.logger.addHandler(self.handler)

    def emit(self, event: str, *, level=logging.INFO, **fields):
        if event not in EVENTS:
            raise ValueError('unknown_log_event')
        self.logger.log(level, '', extra={'rm_event':event, 'rm_fields':fields})

    def close(self):
        self.handler.flush()
        self.handler.close()
        self.logger.removeHandler(self.handler)
