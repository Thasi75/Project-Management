import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from backend import models as m
from backend.config import DATA, today
from backend.db import Session, transaction
from .conftest import create_record


def data(module, **changes):
    return {'work_date': today(), 'module_id': module['id'], 'feature': '人员同步功能',
            'work_content': '## 接口开发\n\n完成**字段映射**。\n保留重试记录。',
            'duration_minutes': 90, 'extra_time_notes': '外部接口联调额外耗时。', **changes}


def path(p, row=None):
    return f'/api/projects/{p["id"]}/records/coding' + ('/' + row['id'] if row else '')


def metric(client, p):
    response = client.get('/api/metrics', params={'project_id': p['id']})
    assert response.status_code == 200, response.text
    return response.json()


def test_coding_crud_required_fields_refs_versions_and_archive(client, setup_project):
    p, _, module = setup_project('代码编写登记')
    other, _, other_module = setup_project('代码编写隔离')
    for field in ['work_date', 'module_id', 'feature', 'work_content', 'duration_minutes']:
        missing = data(module); missing.pop(field)
        assert create_record(client, p, 'coding', missing).status_code == 422
        assert create_record(client, p, 'coding', data(module, **{field: None})).status_code == 422
    for field in ['feature', 'work_content', 'module_id']:
        assert create_record(client, p, 'coding', data(module, **{field: '   '})).status_code == 422
    for minutes in [0, -1, 1.5, 1.0, '60', True, False, 2147483648]:
        assert create_record(client, p, 'coding', data(module, duration_minutes=minutes)).status_code == 422
    for day in ['2026-02-30', '2026-1-1', (date.fromisoformat(today()) + timedelta(days=1)).isoformat()]:
        assert create_record(client, p, 'coding', data(module, work_date=day)).status_code == 422
    assert create_record(client, p, 'coding', data(module, feature='长' * 201)).status_code == 422
    assert create_record(client, p, 'coding', data(other_module)).status_code == 422
    assert create_record(client, p, 'coding', data(module, project_id=other['id'])).status_code == 422
    key = 'coding-idempotency-key'
    response = create_record(client, p, 'coding', data(module), key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row['code'].startswith('CODE-') and row['work_content'] == data(module)['work_content']
    assert create_record(client, p, 'coding', data(module), key).json()['id'] == row['id']
    assert create_record(client, p, 'coding', data(module, duration_minutes=60), key).status_code == 409
    assert client.get(path(other, row)).status_code == 422
    assert client.put(path(other, row), json=data(other_module, version=row['version'])).status_code == 422
    assert client.post(path(other, row) + '/remove', json={'version': row['version'], 'reason': '移除'}).status_code == 422
    response = client.put(path(p, row), json=data(module, version=row['version'], duration_minutes=120, extra_time_notes=''))
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['version'] == row['version'] + 1 and updated['duration_minutes'] == 120
    assert client.put(path(p, row), json=data(module, version=row['version'])).status_code == 409
    history = client.get(f'/api/projects/{p["id"]}/history/coding/{row["id"]}').json()
    assert history[0]['before']['duration_minutes'] == 90 and history[0]['after']['duration_minutes'] == 120
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert client.get(path(p, row)).json() == updated
    assert create_record(client, p, 'coding', data(module)).status_code == 409
    assert client.put(path(p, row), json=data(module, version=updated['version'])).status_code == 409
    assert client.post(path(p, row) + '/remove', json={'version': updated['version'], 'reason': '移除'}).status_code == 409


def test_coding_sum_then_full_hours_filters_pagination_removal_and_modules(client, setup_project):
    p, _, module = setup_project('代码耗时统计')
    other, _, other_module = setup_project('代码耗时隔离')
    assert (metric(client, p)['coding_minutes'], metric(client, p)['coding_hours']) == (0, 0)
    rows = []
    for minutes, expected_minutes, expected_hours in [(59, 59, 0), (59, 118, 1), (2, 120, 2), (90, 210, 3)]:
        response = create_record(client, p, 'coding', data(module, duration_minutes=minutes,
                                 feature='功能 %_' if not rows else f'功能{minutes}'))
        assert response.status_code == 200, response.text
        rows.append(response.json())
        values = metric(client, p)
        assert (values['coding_minutes'], values['coding_hours']) == (expected_minutes, expected_hours)
        assert isinstance(values['coding_hours'], int)
    assert create_record(client, other, 'coding', data(other_module, duration_minutes=600)).status_code == 200
    def listing(**filters):
        result = client.get('/api/records/coding', params={'project_id': p['id'], **filters})
        assert result.status_code == 200, result.text
        return result.json()
    assert listing(size=1, page=2)['total'] == 4
    assert listing(q='%_')['items'][0]['id'] == rows[0]['id']
    assert listing(q='字段映射', module_id=module['id'], start=today(), end=today())['total'] == 4
    assert listing(q='额外耗时')['total'] == 4
    assert listing(module_id=other_module['id'])['total'] == 0
    assert metric(client, p)['coding_minutes'] == 210
    assert client.post(path(p, rows[-1]) + '/remove', json={'version': rows[-1]['version'], 'reason': '移除'}).status_code == 200
    assert listing()['total'] == 3 and metric(client, p)['coding_hours'] == 2
    response = client.put(f'/api/projects/{p["id"]}/modules/{module["id"]}', json={'version': module['version'], 'name': module['name'], 'enabled': False})
    assert response.status_code == 200
    assert create_record(client, p, 'coding', data(module)).status_code == 422
    assert client.put(path(p, rows[0]), json=data(module, version=rows[0]['version'], duration_minutes=60)).status_code == 200
    before = client.get('/api/metrics').json()['coding_minutes']
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert metric(client, p)['coding_minutes'] == 121
    assert client.get('/api/metrics').json()['coding_minutes'] == before - 121
    with pytest.raises(IntegrityError), transaction() as session:
        session.get(m.CodingWork, rows[0]['id']).duration_minutes = 1.5


def test_coding_backup_and_009_migration_preserve_existing_tables(client, setup_project, tmp_path):
    p, _, module = setup_project('代码编写备份')
    row = create_record(client, p, 'coding', data(module)).json()
    backup = client.post('/api/backups').json()
    assert backup['schema'] == '010'
    assert client.put(path(p, row), json=data(module, version=row['version'], duration_minutes=180)).status_code == 200
    assert client.post('/api/backups/' + backup['name'] + '/restore', json={'confirmation': '替换当前业务数据'}).status_code == 200
    assert client.get(path(p, row)).json() == row
    with zipfile.ZipFile(DATA / 'backups' / backup['name']) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    database = tmp_path / 'legacy-009.db'; database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('DROP TABLE coding_work')
        db.execute("DELETE FROM entity_revisions WHERE kind='coding'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='coding'")
        db.execute("UPDATE alembic_version SET version_num='009'"); db.commit()
        before = {name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
                  for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")}
    entries['project.db'] = database.read_bytes()
    manifest = json.loads(entries['manifest.json']); manifest.update(schema='009', database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json'] = json.dumps(manifest).encode()
    legacy = DATA / 'backups' / 'coding-legacy-009.zip'
    with zipfile.ZipFile(legacy, 'w') as z:
        for name, content in entries.items(): z.writestr(name, content)
    response = client.post('/api/backups/' + legacy.name + '/restore', json={'confirmation': '替换当前业务数据'})
    assert response.status_code == 200, response.text
    with closing(sqlite3.connect(DATA / 'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '010'
        assert db.execute('SELECT count(*) FROM coding_work').fetchone()[0] == 0
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name, rows in before.items():
            assert db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() == rows, name
    assert metric(client, p)['coding_hours'] == 0
