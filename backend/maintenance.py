from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import select, delete
from .config import ROOT, DATA, config, today, now
from .db import engine, Session, WRITE_LOCK
from . import models as m
from .service import fail

SCHEMA_HEAD = '009'


def checksum(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def migrate():
    database = DATA / 'project.db'
    recovery = None
    if database.exists():
        with closing(sqlite3.connect(database)) as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone()
            version = db.execute('SELECT version_num FROM alembic_version').fetchone() if exists else None
        if version and version[0] == SCHEMA_HEAD:
            return
        recovery = DATA / ('pre-migration-' + m.uid() + '.db')
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(recovery)) as target:
            source.backup(target)
    try:
        command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    except Exception:
        engine.dispose()
        if recovery:
            for suffix in ('-wal', '-shm'):
                Path(str(database) + suffix).unlink(missing_ok=True)
            shutil.copy2(recovery, database)
        raise


def make_backup(label='manual'):
    with WRITE_LOCK, tempfile.TemporaryDirectory(dir=DATA) as tmp:
        copy = Path(tmp) / 'project.db'
        with closing(sqlite3.connect(DATA / 'project.db')) as source, closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        # Temporary uploads are intentionally excluded from both the database and archive.
        with closing(sqlite3.connect(copy)) as db:
            db.execute('DELETE FROM attachments WHERE project_id IS NULL')
            rows = db.execute('SELECT path, sha256 FROM attachments').fetchall()
            count = db.execute('SELECT count(*) FROM projects').fetchone()[0]
            version = db.execute('SELECT version_num FROM alembic_version').fetchone()[0]
            db.commit()
        manifest = {'created_at': now(), 'schema': version, 'projects': count, 'label': label,
                    'files': {path: sha for path, sha in rows}, 'database_sha256': checksum(copy)}
        name = now().replace(':', '').replace('+', '_') + '-' + label + '-' + m.uid()[:6] + '.zip'
        target_path = DATA / 'backups' / name
        pending = target_path.with_suffix('.partial')
        try:
            with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(copy, 'project.db')
                for path, sha in rows:
                    source = DATA / path
                    if not source.is_file() or checksum(source) != sha:
                        fail('附件缺失或校验失败，备份未完成：' + path, 409)
                    archive.write(source, path)
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            pending.replace(target_path)
        finally:
            pending.unlink(missing_ok=True)
        if label == 'auto':
            archives = sorted((DATA / 'backups').glob('*-auto-*.zip'), reverse=True)
            for old in archives[int(config()['backup_keep']):]:
                old.unlink()
        return {'name': name, **manifest}


def auto_backup():
    marker = DATA / '.auto-backup-day'
    with WRITE_LOCK:
        if marker.exists() and marker.read_text() == today():
            return
        clean_staging()
        make_backup('auto')
        marker.write_text(today())


def backup_path(name):
    if Path(name).name != name or not name.endswith('.zip'):
        fail('无效备份文件名')
    path = DATA / 'backups' / name
    if not path.is_file():
        fail('备份文件不存在', 404)
    return path


def inspect_backup(name, destination=None):
    path = backup_path(name)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            if manifest['schema'] not in ('001', '002', '003', '004', '005', '006', '007', '008', SCHEMA_HEAD):
                fail('备份数据库版本不兼容')
            expected = {'project.db', 'manifest.json', *manifest['files'].keys()}
            if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                fail('备份内容与清单不一致')
            for key, sha in {'project.db': manifest['database_sha256'], **manifest['files']}.items():
                if key != 'project.db' and (not key.startswith('files/') or '..' in key or '\\' in key or ':' in key):
                    fail('备份包含非法路径')
                digest = hashlib.sha256()
                output = None
                if destination:
                    target = destination / key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output = target.open('wb')
                try:
                    with archive.open(key) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                            if output:
                                output.write(chunk)
                finally:
                    if output:
                        output.close()
                if digest.hexdigest() != sha:
                    fail('备份完整性校验失败：' + key)
            if destination:
                with closing(sqlite3.connect(destination / 'project.db')) as db:
                    if db.execute('SELECT version_num FROM alembic_version').fetchone()[0] != manifest['schema']:
                        fail('备份数据库版本与清单不一致')
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                        fail('备份数据库完整性检查失败')
                    actual = dict(db.execute('SELECT path, sha256 FROM attachments').fetchall())
                    if actual != manifest['files']:
                        fail('备份附件清单与数据库不符')
            return {'name': name, **manifest, 'files_checked': len(manifest['files']), 'valid': True}
    except (zipfile.BadZipFile, KeyError, ValueError):
        fail('备份格式无效')


def restore_backup(name):
    with WRITE_LOCK, tempfile.TemporaryDirectory(dir=DATA) as tmp:
        staged = Path(tmp)
        preview = inspect_backup(name, staged)
        with Session() as session:
            if session.scalar(select(m.Job.id).where(m.Job.status.in_(['等待中', '生成中']))):
                fail('请等待简报生成结束后再恢复备份', 409)
        safety = make_backup('before-restore')
        engine.dispose()
        rollback = staged / 'rollback'
        rollback.mkdir()
        for name_part in ('project.db', 'project.db-wal', 'project.db-shm', 'files'):
            current = DATA / name_part
            if current.exists():
                current.replace(rollback / name_part)
        try:
            shutil.copy2(staged / 'project.db', DATA / 'project.db')
            shutil.copytree(staged / 'files', DATA / 'files') if (staged / 'files').exists() else (DATA / 'files').mkdir()
            migrate()
            with engine.begin() as connection:
                connection.exec_driver_sql("UPDATE generation_jobs SET status='失败', error='备份恢复中断了生成，请重试', retryable=1 WHERE status IN ('等待中','生成中')")
            # Downloads must be rebuilt from restored versions, not stale caches.
            for file in (DATA / 'exports').glob('*'):
                if file.is_file():
                    file.unlink()
            (DATA / '.auto-backup-day').unlink(missing_ok=True)
        except Exception:
            engine.dispose()
            for item in ('project.db', 'project.db-wal', 'project.db-shm', 'files'):
                target = DATA / item
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                if (rollback / item).exists():
                    (rollback / item).replace(target)
            raise
        return {'restored': preview, 'safety_backup': safety['name']}


def clean_staging():
    from datetime import datetime, timedelta
    cutoff = (datetime.fromisoformat(now()) - timedelta(hours=24)).isoformat()
    with WRITE_LOCK, Session.begin() as session:
        stale = list(session.scalars(select(m.Attachment).where(m.Attachment.project_id == None, m.Attachment.created_at < cutoff)))
        for item in stale:
            (DATA / item.path).unlink(missing_ok=True)
            session.delete(item)

