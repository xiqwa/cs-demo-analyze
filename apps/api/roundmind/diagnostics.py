from collections import deque
import json
import os
from pathlib import Path
import zipfile
from .config import Settings, VERSION
from .logging import safe_record, utc_now

TAIL_BYTES = 1024 * 1024
MAX_RECORDS = 1000


def export_diagnostics(settings: Settings, output: Path) -> dict:
    if not output.is_absolute() or output.suffix.lower() != '.zip':
        raise ValueError('diagnostics_output_must_be_absolute_zip')
    records = deque(maxlen=MAX_RECORDS)
    skipped = 0
    # Oldest rotated file first, latest current file last. Never scan directories.
    paths = [settings.log_path.with_name(settings.log_path.name + f'.{i}') for i in range(settings.log_backup_count, 0, -1)]
    paths.append(settings.log_path)
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open('rb') as source:
                size = source.seek(0, 2)
                start = max(0, size - TAIL_BYTES)
                source.seek(start)
                # One bounded snapshot read even if the writer is appending.
                content = source.read(size - start)
            if start:
                _, _, content = content.partition(b'\n')
                skipped += 1
        except FileNotFoundError:
            # A rotation may rename the file between inspection and open.
            continue
        for line in content.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                skipped += 1
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not {'timestamp','level','event','request_id'} <= row.keys():
                    raise ValueError('invalid_log_record')
                records.append(safe_record(row))
            except (ValueError, TypeError, RecursionError):
                skipped += 1
    manifest = {'format_version':1, 'app_version':VERSION, 'created_at':utc_now(),
                'record_count':len(records), 'skipped_lines':skipped,
                'max_records':MAX_RECORDS, 'max_source_bytes_per_file':TAIL_BYTES}
    # Exclusive creation, 0600 on POSIX; do not overwrite existing user output.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                bundle.writestr('logs.jsonl', ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in records))
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return manifest
