import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('PM_DATA_DIR', ROOT / 'data')).resolve()
LOCAL = ROOT / 'local'
TZ = timezone(timedelta(hours=8))


def today():
    return datetime.now(TZ).date().isoformat()


def now():
    return datetime.now(TZ).isoformat(timespec='microseconds')


def config():
    defaults = {'model': 'gpt-4.1-mini', 'max_file_mb': 50, 'backup_keep': 14,
                'extensions': '.doc,.docx,.xls,.xlsx,.ppt,.pptx,.pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.md,.csv,.zip,.7z,.rar',
                'soffice': '', 'batch_chars': 45000}
    path = LOCAL / 'settings.json'
    if path.exists():
        defaults.update(json.loads(path.read_text('utf-8')))
    return defaults


def soffice_path():
    local = LOCAL / 'tools' / 'libreoffice' / 'program' / 'soffice.exe'
    return config()['soffice'] or os.environ.get('PM_SOFFICE', '') or (str(local) if local.is_file() else '') or shutil.which('soffice') or ''


def ensure_dirs():
    for path in [DATA, DATA / 'files', DATA / 'staging', DATA / 'backups', DATA / 'exports', LOCAL]:
        path.mkdir(parents=True, exist_ok=True)
