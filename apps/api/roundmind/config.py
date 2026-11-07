from dataclasses import dataclass
import os
from pathlib import Path
import sys

VERSION = '0.1.0'
HEAD_REVISION = '0001_initial'


def absolute_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('data_dir_must_be_absolute')
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    migration_mode: str = 'auto'
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 3

    def __post_init__(self):
        object.__setattr__(self, 'data_dir', absolute_path(self.data_dir))
        if self.migration_mode not in {'auto', 'check'}:
            raise ValueError('invalid_migration_mode')
        if self.log_max_bytes < 512 or not 1 <= self.log_backup_count <= 3:
            raise ValueError('invalid_log_rotation')

    @property
    def database_path(self) -> Path:
        return self.data_dir / 'db' / 'roundmind.sqlite3'

    @property
    def log_path(self) -> Path:
        return self.data_dir / 'logs' / 'roundmind.jsonl'

    @classmethod
    def from_env(cls, *, platform: str | None = None):
        platform = platform or sys.platform
        override = os.environ.get('ROUNDMIND_DATA_DIR')
        if override is not None:
            if not override.strip():
                raise ValueError('data_dir_must_be_absolute')
            directory = absolute_path(override)
        elif platform == 'win32':
            local = os.environ.get('LOCALAPPDATA')
            if not local:
                raise ValueError('local_app_data_unavailable')
            directory = absolute_path(local) / 'RoundMind'
        elif platform == 'darwin':
            directory = Path.home() / 'Library' / 'Application Support' / 'RoundMind'
        else:
            directory = absolute_path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'RoundMind'
        return cls(directory, migration_mode=os.environ.get('ROUNDMIND_MIGRATION_MODE', 'auto'))


def private_directory(path: Path):
    # mkdir's mode affects only new directories, never chmod an existing parent.
    if not path.exists():
        private_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise ValueError('invalid_data_directory')


def private_file(path: Path):
    private_directory(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid_data_file')
    else:
        os.close(fd)
