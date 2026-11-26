import hashlib
from contextlib import closing
import json
import sqlite3
import zipfile

import pytest

from backend.config import DATA
from tests.conftest import create_record, task_data


def upload(client, pid=None, name='材料.pdf', acceptance=False):
    params = {'is_acceptance': acceptance}
    if pid:
        params['project_id'] = pid
    result = client.post('/api/attachments/upload', params=params,
                         files={'file': (name, b'acceptance fixture', 'application/octet-stream')})
    assert result.status_code == 200, result.text
    return result.json()


def mark(client, file, value):
    return client.put('/api/attachments/' + file['id'] + '/acceptance',
                      json={'version': file['version'], 'is_acceptance': value})


def materials(client, pid):
    return client.get('/api/projects/' + pid + '/attachments?acceptance_only=true').json()


def test_shared_attachment_flag_preserves_identity_and_business_links(client, setup_project):
    p, person, _ = setup_project('验收共享')
    other, _, _ = setup_project('验收隔离')
    file = upload(client, p['id'])
    assert file['is_acceptance'] is False
    task = create_record(client, p, 'tasks', task_data(person, attachment_ids=[file['id']])).json()
    paths = set((DATA / 'files').iterdir())
    assert materials(client, p['id']) == []
    response = mark(client, file, True)
    assert response.status_code == 200, response.text
    marked = response.json()
    selected = materials(client, p['id'])
    assert len(selected) == 1 and selected[0]['id'] == file['id']
    assert selected[0]['path'] == file['path'] and selected[0]['sha256'] == file['sha256']
    assert selected[0]['references'][0]['entity_id'] == task['id']
    assert materials(client, other['id']) == []
    assert set((DATA / 'files').iterdir()) == paths
    assert mark(client, file, False).status_code == 409
    # Legacy description/removal payloads must not silently clear the new flag.
    updated = client.put('/api/attachments/' + file['id'], json={
        'version': marked['version'], 'description': '签字原件', 'removed': False}).json()
    assert updated['is_acceptance'] is True
    cleared = mark(client, updated, False)
    assert cleared.status_code == 200 and materials(client, p['id']) == []
    assert client.get('/api/attachments/' + file['id'] + '/download').content == b'acceptance fixture'
    assert client.get('/api/records/tasks?project_id=' + p['id']).json()['items'][0]['attachment_ids'] == [file['id']]
    assert set((DATA / 'files').iterdir()) == paths


@pytest.mark.parametrize('extension', ['png', 'jpg', 'webp', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv'])
def test_direct_material_upload_supported_formats(client, setup_project, extension):
    p, _, _ = setup_project('材料格式-' + extension)
    file = upload(client, p['id'], name='验收材料.' + extension, acceptance=True)
    assert file['is_acceptance'] is True
    assert [x['id'] for x in materials(client, p['id'])] == [file['id']]
    assert [x['id'] for x in client.get('/api/projects/' + p['id'] + '/attachments').json()] == [file['id']]


def test_staged_material_binding_cancellation_and_cross_project_reference(client, setup_project):
    file = upload(client)
    marked = mark(client, file, True).json()
    project = client.post('/api/projects', json={'name': '暂存验收材料', 'scope': '材料绑定', 'attachment_ids': [file['id']]}).json()
    assert materials(client, project['id'])[0]['id'] == file['id']
    assert materials(client, project['id'])[0]['path'] == marked['path']
    other, person, _ = setup_project('不能跨项目引用')
    assert create_record(client, other, 'tasks', task_data(person, attachment_ids=[file['id']])).status_code == 422
    canceled = upload(client, acceptance=True)
    assert client.delete('/api/attachments/staged/' + canceled['id']).status_code == 200
    assert not (DATA / canceled['path']).exists()


def test_removed_and_archived_materials(client, setup_project):
    p, _, _ = setup_project('归档验收材料')
    file = upload(client, p['id'], acceptance=True)
    removed = client.put('/api/attachments/' + file['id'], json={'version': file['version'], 'removed': True}).json()
    assert materials(client, p['id']) == [] and removed['is_acceptance'] is True
    assert mark(client, removed, True).status_code == 409
    restored = client.put('/api/attachments/' + file['id'], json={'version': removed['version'], 'removed': False}).json()
    assert materials(client, p['id'])[0]['id'] == file['id']
    archive = client.post('/api/projects/' + p['id'] + '/archive', json={'version': p['version'], 'archived': True})
    assert archive.status_code == 200, archive.text
    assert mark(client, restored, False).status_code == 409
    assert client.post('/api/attachments/upload', params={'project_id': p['id'], 'is_acceptance': True}, files={'file': ('拒绝.pdf', b'x')}).status_code == 409
    assert materials(client, p['id'])[0]['is_acceptance'] is True


def test_current_and_legacy_backups_preserve_files_and_upgrade_flags(client, setup_project, tmp_path):
    p, _, _ = setup_project('验收材料备份')
    file = upload(client, p['id'], acceptance=True)
    backup = client.post('/api/backups').json()
    assert backup['schema'] == '009'
    assert client.get('/api/backups/' + backup['name'] + '/preview').status_code == 200
    assert mark(client, file, False).status_code == 200
    result = client.post('/api/backups/' + backup['name'] + '/restore', json={'confirmation': '替换当前业务数据'})
    assert result.status_code == 200, result.text
    assert materials(client, p['id'])[0]['id'] == file['id']

    # Make a real version-001 archive, with consistent database and file hashes.
    legacy = DATA / 'backups' / 'legacy-acceptance-test.zip'
    with zipfile.ZipFile(DATA / 'backups' / backup['name']) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    database = tmp_path / 'legacy.db'
    database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('DROP TABLE project_costs')
        db.execute("DELETE FROM entity_revisions WHERE kind='costs'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='costs'")
        db.execute('DROP TABLE project_configurations')
        db.execute("DELETE FROM entity_revisions WHERE kind='configurations'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='configurations'")
        db.execute('DROP TABLE communications')
        db.execute('ALTER TABLE attachments DROP COLUMN is_acceptance')
        for column in ('name', 'team', 'notes', 'enabled', 'version', 'created_at', 'updated_at'):
            db.execute('ALTER TABLE project_members DROP COLUMN ' + column)
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='001'")
        db.commit()
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    entries['project.db'] = database.read_bytes()
    manifest = json.loads(entries['manifest.json'])
    manifest['schema'] = '001'
    manifest['database_sha256'] = hashlib.sha256(entries['project.db']).hexdigest()
    entries['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(legacy, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    preview = client.get('/api/backups/' + legacy.name + '/preview')
    assert preview.status_code == 200, preview.text
    result = client.post('/api/backups/' + legacy.name + '/restore', json={'confirmation': '替换当前业务数据'})
    assert result.status_code == 200, result.text
    files = client.get('/api/projects/' + p['id'] + '/attachments').json()
    assert files[0]['id'] == file['id'] and files[0]['is_acceptance'] is False
    assert files[0]['path'] == file['path'] and files[0]['sha256'] == file['sha256']
    assert materials(client, p['id']) == []
    assert client.get('/api/attachments/' + file['id'] + '/download').content == b'acceptance fixture'
    with sqlite3.connect(DATA / 'project.db') as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '009'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
