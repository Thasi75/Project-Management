import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from backend import models as m
from backend.config import DATA, today
from backend.db import Session, transaction
from backend.research_export import COLUMNS
from .conftest import create_record
from .test_log_export import read_export, NS


def data(person, module, **changes):
    return {'research_date': '2026-11-01', 'module_id': module['id'],
            'requirement': '培训申请\n按科室审核', 'source_id': person['id'], 'recorder_id': person['id'],
            'solution': '配置审核流程\n增加审批权限', **changes}


def path(project, row=None):
    return f'/api/projects/{project["id"]}/records/research' + ('/'+row['id'] if row else '')


def export_path(project):
    return f'/api/projects/{project["id"]}/research/export'


def test_research_required_defaults_sequence_and_validation(client, setup_project):
    p, person, module = setup_project('调研必填')
    for field in ['research_date', 'module_id', 'requirement', 'source_id', 'recorder_id', 'solution']:
        missing = data(person, module); missing.pop(field)
        assert create_record(client, p, 'research', missing).status_code == 422
        for value in ['', '   ', None]:
            assert create_record(client, p, 'research', data(person, module, **{field: value})).status_code == 422
    for field in ['importance', 'responded', 'status']:
        for value in ['', None, '无效枚举']:
            assert create_record(client, p, 'research', data(person, module, **{field: value})).status_code == 422
    for value in ['2026-02-30', '2026-1-1', (date.fromisoformat(today())+timedelta(days=1)).isoformat()]:
        assert create_record(client, p, 'research', data(person, module, research_date=value)).status_code == 422
    for value in [0, -1, 1.5, True, '1', 2147483648]:
        assert create_record(client, p, 'research', data(person, module, sequence=value)).status_code == 422
    next_path = f'/api/projects/{p["id"]}/research/next-sequence'
    assert client.get(next_path).json()['sequence'] == 1
    key = uuid4().hex
    response = create_record(client, p, 'research', data(person, module), key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert [row[x] for x in ['sequence', 'importance', 'responded', 'status', 'notes']] == [1, '中', '是', '设计', '']
    assert create_record(client, p, 'research', data(person, module), key).json()['id'] == row['id']
    assert create_record(client, p, 'research', data(person, module, notes='另一内容'), key).status_code == 409
    second = create_record(client, p, 'research', data(person, module, sequence=8)).json()
    assert client.get(next_path).json()['sequence'] == 9
    assert client.post(path(p, second)+'/remove', json={'version': second['version'], 'reason': '重复记录'}).status_code == 200
    assert client.get(next_path).json()['sequence'] == 9
    assert create_record(client, p, 'research', data(person, module)).json()['sequence'] == 9


def test_research_project_isolation_disabled_refs_edit_history_and_archive(client, setup_project):
    p, person, module = setup_project('调研甲'); other, stranger, foreign_module = setup_project('调研乙')
    for field, value in [('module_id', foreign_module['id']), ('source_id', stranger['id']), ('recorder_id', stranger['id'])]:
        assert create_record(client, p, 'research', data(person, module, **{field: value})).status_code == 422
    assert create_record(client, p, 'research', data(person, module, project_id=other['id'])).status_code == 422
    row = create_record(client, p, 'research', data(person, module)).json()
    assert client.get(path(other, row)).status_code == 422
    assert client.put(path(other, row), json=data(stranger, foreign_module, version=row['version'])).status_code == 422
    assert client.post(path(other, row)+'/remove', json={'version': row['version'], 'reason': '测试'}).status_code == 422
    with transaction() as session:
        session.get(m.Member, (p['id'], person['id'])).enabled = False
        session.get(m.Module, module['id']).enabled = False
    assert create_record(client, p, 'research', data(person, module)).status_code == 422
    response = client.put(path(p, row), json=data(person, module, version=row['version'], sequence=3,
        status='上线', importance='高', responded='否', solution='修订方案\n第二行'))
    assert response.status_code == 200, response.text
    saved = response.json(); assert saved['sequence'] == 3 and saved['status'] == '上线'
    assert client.put(path(p, row), json=data(person, module, version=row['version'])).status_code == 409
    history = client.get(f'/api/projects/{p["id"]}/history/research/{row["id"]}').json()
    assert len(history) == 2 and history[0]['before']['sequence'] == 1 and history[0]['after']['sequence'] == 3
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert client.get(path(p, saved)).status_code == 200
    assert create_record(client, p, 'research', data(person, module)).status_code == 409
    assert client.put(path(p, saved), json=data(person, module, version=saved['version'])).status_code == 409
    assert client.post(path(p, saved)+'/remove', json={'version': saved['version'], 'reason': '测试'}).status_code == 409
    _, _, rows = read_export(client.get(export_path(p)))
    assert rows[5][3] == module['name'] and rows[5][5:7] == [person['name'], person['name']]


def test_research_sort_filters_pagination_export_all_and_report_unchanged(client, setup_project):
    p, person, module = setup_project('调研筛选'); other, stranger, foreign_module = setup_project('其他调研')
    before = client.post(f'/api/projects/{p["id"]}/report-preview', json={'start': '2026-11-01', 'end': '2026-11-20'}).json()
    create_record(client, other, 'research', data(stranger, foreign_module, requirement='其他项目内容'))
    with transaction() as session:
        for i in range(205):
            session.add(m.Research(project_id=p['id'], code='REQ-EXPORT-'+str(i), sequence=205-i,
                research_date=f'2026-11-{i%20+1:02d}', module_id=module['id'], source_id=person['id'], recorder_id=person['id'],
                importance='高' if i%2 else '中', responded='是', status='开发' if i%2 else '设计',
                payload={'requirement': '=SUM(1,2)\n需求 %_', 'solution': '方案\n第二行', 'notes': 'https://example.com'}))
    def listing(**filters):
        r = client.get('/api/records/research', params={'project_id': p['id'], **filters})
        assert r.status_code == 200, r.text
        return r.json()
    first = listing(); assert first['total'] == 205 and [r['sequence'] for r in first['items']] == list(range(1, 21))
    assert [r['sequence'] for r in listing(page=2)['items']] == list(range(21, 41))
    response = client.get(export_path(p), params={'page': 10, 'size': 1})
    sheet, styles, rows = read_export(response)
    assert response.headers['x-export-count'] == '205'
    assert rows[4] == [label for label, _ in COLUMNS]
    assert [int(r[0]) for n, r in rows.items() if n >= 5] == list(range(1, 206))
    assert rows[5][3:] == [module['name'], '=SUM(1,2)\n需求 %_', person['name'], person['name'], '中', '是', '设计', '方案\n第二行', 'https://example.com']
    assert sheet.find('s:autoFilter', NS).get('ref') == 'A4:L209'
    assert sheet.find('.//s:c[@r="A5"]', NS).get('t') != 's'
    assert (datetime(1899, 12, 30)+timedelta(days=float(rows[5][2]))).strftime('%Y-%m-%d') == '2026-11-05'
    assert any(f.get('formatCode') == 'yyyy-mm-dd' for f in styles.findall('.//s:numFmt', NS))
    filters = {'q': '%_', 'module_id': module['id'], 'status': '开发', 'start': '2026-11-01', 'end': '2026-11-06',
               'importance': '高', 'responded': '是', 'source_id': person['id'], 'recorder_id': person['id']}
    for chosen in [filters, *[{k: v} for k, v in filters.items()]]:
        expected = listing(size=200, **chosen)
        codes = [r['code'] for r in expected['items']]
        if expected['total'] > 200: codes += [r['code'] for r in listing(size=200, page=2, **chosen)['items']]
        _, _, actual = read_export(client.get(export_path(p), params=chosen))
        assert [r[1] for n, r in actual.items() if n >= 5] == codes
    # Removing a row is reflected in both list and Excel, while its history is retained.
    removed = first['items'][0]
    assert client.post(path(p, removed)+'/remove', json={'version': removed['version'], 'reason': '重复'}).status_code == 200
    assert listing()['total'] == 204
    _, _, remaining = read_export(client.get(export_path(p)))
    assert removed['code'] not in [r[1] for n, r in remaining.items() if n >= 5]
    after = client.post(f'/api/projects/{p["id"]}/report-preview', json={'start': '2026-11-01', 'end': '2026-11-20'}).json()
    before.pop('captured_at'); after.pop('captured_at')
    assert before == after


def test_research_export_empty_invalid_date_and_oversized_cell(client, setup_project):
    p, person, module = setup_project('空调研')
    _, _, rows = read_export(client.get(export_path(p))); assert not [n for n in rows if n >= 5]
    assert client.get('/api/projects/missing/research/export').status_code == 404
    for filters in [{'start': '2026-1-1'}, {'end': '2026-02-30'}, {'start': '2026-11-02', 'end': '2026-11-01'}]:
        assert client.get(export_path(p), params=filters).status_code == 422
    assert create_record(client, p, 'research', data(person, module, requirement='字'*32768)).status_code == 200
    response = client.get(export_path(p)); assert response.status_code == 422 and '32767' in response.text


def test_research_backup_restore_and_008_upgrade_preserves_existing_data(client, setup_project, tmp_path):
    p, person, module = setup_project('调研备份')
    row = create_record(client, p, 'research', data(person, module)).json()
    backup = client.post('/api/backups').json(); assert backup['schema'] == '009'
    assert client.put(path(p, row), json=data(person, module, version=row['version'], solution='临时修改')).status_code == 200
    assert client.post('/api/backups/'+backup['name']+'/restore', json={'confirmation': '替换当前业务数据'}).status_code == 200
    assert client.get(path(p, row)).json() == row
    with zipfile.ZipFile(DATA/'backups'/backup['name']) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    database = tmp_path/'legacy-008.db'; database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='008'"); db.commit()
        old = {name: db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall()
               for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")}
    entries['project.db'] = database.read_bytes()
    manifest = json.loads(entries['manifest.json']); manifest.update(schema='008', database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json'] = json.dumps(manifest).encode()
    legacy = DATA/'backups/research-legacy-008.zip'
    with zipfile.ZipFile(legacy, 'w') as z:
        for name, content in entries.items(): z.writestr(name, content)
    assert client.get('/api/backups/'+legacy.name+'/preview').status_code == 200
    result = client.post('/api/backups/'+legacy.name+'/restore', json={'confirmation': '替换当前业务数据'})
    assert result.status_code == 200, result.text
    with closing(sqlite3.connect(DATA/'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '009'
        assert db.execute('SELECT count(*) FROM requirement_research').fetchone()[0] == 0
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name, rows in old.items(): assert db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() == rows, name
    assert create_record(client, p, 'research', data(person, module)).status_code == 200
