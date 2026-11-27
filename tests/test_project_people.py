import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from backend import models as m
from backend.config import DATA
from backend.db import transaction
from .conftest import create_record, task_data
from .test_business import update


PROFILE_COLUMNS = ('name', 'team', 'notes', 'enabled', 'version', 'created_at', 'updated_at')


def path(project, person=None):
    return '/api/projects/' + project['id'] + '/people' + ('/' + person['id'] if person else '')


def person_update(client, project, person, **changes):
    data = {key: person[key] for key in ('name', 'team', 'notes', 'enabled', 'version')}
    return client.put(path(project, person), json={**data, **changes})


def project_update(client, project, **changes):
    from backend.schemas import ProjectInput
    data = {key: value for key, value in project.items() if key in ProjectInput.model_fields}
    return client.put('/api/projects/' + project['id'], json={**data, 'reason': '人员验证', **changes})


def test_scoped_people_crud_same_names_conflicts_and_closed_global_api(client, setup_project):
    a, _, _ = setup_project('人员隔离甲')
    b, person_b, _ = setup_project('人员隔离乙')
    first = client.post(path(a), json={'name': '同名人员', 'team': '甲团队', 'notes': '甲项目资料'}).json()
    second = client.post(path(b), json={'name': '同名人员', 'team': '乙团队'}).json()
    assert first['id'] != second['id'] and first['project_id'] == a['id']
    assert all(row['project_id'] == a['id'] for row in client.get(path(a)).json())
    assert second['id'] not in {row['id'] for row in client.get(path(a)).json()}
    assert client.get('/api/people').status_code == 410
    assert client.post('/api/people', json={'name': '旧入口'}).status_code == 410
    assert client.put('/api/people/' + first['id'], json={'name': '旧修改'}).status_code == 410
    assert person_update(client, b, first, name='越界').status_code == 404
    assert client.post(path(a), json={'name': '注入', 'project_id': b['id']}).status_code == 422
    result = person_update(client, a, first, name='仅修改甲', team='甲新团队')
    assert result.status_code == 200 and result.json()['version'] == first['version'] + 1
    assert person_update(client, a, first, name='过期窗口').status_code == 409
    assert next(row for row in client.get(path(b)).json() if row['id'] == second['id']) == second
    current = next(row for row in client.get('/api/projects').json() if row['id'] == a['id'])
    assert first['id'] in current['member_ids']
    assert project_update(client, current, owner_id=person_b['id']).status_code == 422
    assert project_update(client, current, member_ids=[person_b['id']]).status_code == 422
    assert client.post('/api/projects', json={'name': '不复用其他项目', 'scope': '范围', 'member_ids': [first['id']]}).status_code == 422


@pytest.mark.parametrize('kind', ['tasks', 'logs', 'risks'])
def test_all_owner_selectors_reject_other_project_and_keep_disabled_history(client, setup_project, kind):
    a, person_a, module = setup_project('责任人甲-' + kind)
    b, person_b, _ = setup_project('责任人乙-' + kind)
    payload = {'tasks': task_data(person_a), 'logs': {'work_date': '2026-11-01', 'module_id': module['id'], 'content': '工作内容', 'owner_id': person_a['id']},
               'risks': {'description': '项目风险', 'raised_date': '2026-11-01', 'owner_id': person_a['id']}}[kind]
    assert create_record(client, a, kind, {**payload, 'owner_id': person_b['id']}).status_code == 422
    if kind in ('tasks', 'logs'):
        assert create_record(client, a, kind, {**payload, 'participant_ids': [person_b['id']]}).status_code == 422
        payload['participant_ids'] = [person_a['id']]
    saved = create_record(client, a, kind, payload)
    assert saved.status_code == 200, saved.text
    disabled = person_update(client, a, person_a, enabled=False)
    assert disabled.status_code == 200
    assert create_record(client, a, kind, payload).status_code == 422
    assert update(client, a, kind, saved.json(), notes='保留已停用引用').status_code == 200
    assert person_update(client, a, disabled.json(), enabled=True).status_code == 200
    assert create_record(client, a, kind, payload).status_code == 200
    archive = client.post('/api/projects/' + a['id'] + '/archive', json={'version': a['version'], 'archived': True})
    assert archive.status_code == 200
    assert client.get(path(a)).status_code == 200
    assert client.post(path(a), json={'name': '归档不能新增'}).status_code == 409
    assert person_update(client, a, disabled.json(), enabled=True).status_code == 409
    assert client.post(path(b), json={'name': '乙项目仍可新增'}).status_code == 200


def test_legacy_shared_identity_migrates_without_rewriting_history_or_snapshots(client, setup_project, tmp_path):
    a, shared, _ = setup_project('旧共享人员甲')
    b, _, _ = setup_project('旧共享人员乙')
    with transaction() as session:
        legacy_profile = {key: getattr(session.get(m.Person, shared['id']), key) for key in PROFILE_COLUMNS}
        session.add(m.Member(project_id=b['id'], person_id=shared['id'], **{key: shared[key] for key in PROFILE_COLUMNS}))
    task_a = create_record(client, a, 'tasks', task_data(shared, participant_ids=[shared['id']])).json()
    task_b = create_record(client, b, 'tasks', task_data(shared, participant_ids=[shared['id']])).json()
    period = {'start': '2026-11-01', 'end': '2026-11-07'}
    snapshot = client.post('/api/projects/' + b['id'] + '/report-preview', json=period).json()
    with transaction() as session:
        brief = m.Brief(project_id=b['id'], start=period['start'], end=period['end'], title='原始简报')
        session.add(brief)
        session.flush()
        version = m.BriefVersion(brief_id=brief.id, number=1, snapshot=copy.deepcopy(snapshot), content={'sections': []}, model='test', source='测试')
        session.add(version)
        session.flush()
        version_id = version.id
    history = client.get(f'/api/projects/{b["id"]}/history/tasks/{task_b["id"]}').json()
    backup = client.post('/api/backups').json()
    with zipfile.ZipFile(DATA / 'backups' / backup['name']) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    database = tmp_path / 'legacy-002.db'
    database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('DROP TABLE project_costs')
        db.execute("DELETE FROM entity_revisions WHERE kind='costs'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='costs'")
        db.execute('DROP TABLE project_configurations')
        db.execute("DELETE FROM entity_revisions WHERE kind='configurations'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='configurations'")
        db.execute('DROP TABLE communications')
        for column in PROFILE_COLUMNS:
            db.execute('ALTER TABLE project_members DROP COLUMN ' + column)
        db.execute('DROP TABLE coding_work')
        db.execute("DELETE FROM entity_revisions WHERE kind='coding'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='coding'")
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='002'")
        db.commit()
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    entries['project.db'] = database.read_bytes()
    manifest = json.loads(entries['manifest.json'])
    manifest.update(schema='002', database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json'] = json.dumps(manifest).encode()
    legacy = DATA / 'backups' / 'legacy-project-people-002.zip'
    with zipfile.ZipFile(legacy, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    assert client.get('/api/backups/' + legacy.name + '/preview').status_code == 200
    restored = client.post('/api/backups/' + legacy.name + '/restore', json={'confirmation': '替换当前业务数据'})
    assert restored.status_code == 200, restored.text
    local_a = next(row for row in client.get(path(a)).json() if row['id'] == shared['id'])
    local_b = next(row for row in client.get(path(b)).json() if row['id'] == shared['id'])
    assert {key: local_a[key] for key in PROFILE_COLUMNS} == legacy_profile
    assert {key: local_a[key] for key in PROFILE_COLUMNS} == {key: local_b[key] for key in PROFILE_COLUMNS}
    changed = person_update(client, a, local_a, name='只属于甲的新名称', team='甲团队', notes='甲备注', enabled=False)
    assert changed.status_code == 200
    assert next(row for row in client.get(path(b)).json() if row['id'] == shared['id']) == local_b
    snap_a = client.post('/api/projects/' + a['id'] + '/report-preview', json=period).json()
    snap_b = client.post('/api/projects/' + b['id'] + '/report-preview', json=period).json()
    assert snap_a['sources'][task_a['code']]['owner_name'] == '只属于甲的新名称'
    assert snap_a['sources'][task_a['code']]['participant_names'] == ['只属于甲的新名称']
    assert snap_b['sources'][task_b['code']]['owner_name'] == shared['name']
    assert snap_b['sources'][task_b['code']]['participant_names'] == [shared['name']]
    assert client.get('/api/brief-versions/' + version_id).json()['snapshot'] == snapshot
    assert client.get(f'/api/projects/{b["id"]}/history/tasks/{task_b["id"]}').json() == history
    assert create_record(client, a, 'tasks', task_data(shared)).status_code == 422
    assert create_record(client, b, 'tasks', task_data(shared)).status_code == 200
    # A current backup retains divergent project profiles, not the legacy global values.
    current = client.post('/api/backups').json()
    assert current['schema'] == '010'
    assert person_update(client, a, changed.json(), name='临时名称').status_code == 200
    assert client.post('/api/backups/' + current['name'] + '/restore', json={'confirmation': '替换当前业务数据'}).status_code == 200
    assert next(row for row in client.get(path(a)).json() if row['id'] == shared['id'])['name'] == '只属于甲的新名称'
    with sqlite3.connect(DATA / 'project.db') as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '010'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
