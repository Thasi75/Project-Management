import io
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from sqlalchemy import select

from backend import models as m
from backend.db import Session, transaction
from backend.log_export import COLUMNS, MIME
from .conftest import create_record, task_data
from .test_communications import data as communication_data

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def read_export(response):
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ''
    assert response.headers['content-type'] == MIME
    assert "filename*=UTF-8''" in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        texts = [''.join(item.itertext()) for item in strings]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        styles = ET.fromstring(archive.read('xl/styles.xml'))
        assert not sheet.findall('.//s:f', NS)
        assert not sheet.findall('.//s:hyperlink', NS)
        rows = []
        for row in sheet.findall('.//s:sheetData/s:row', NS):
            values = []
            for cell in row.findall('s:c', NS):
                value = cell.find('s:v', NS)
                text = value.text if value is not None else ''
                values.append(texts[int(text)] if cell.get('t') == 's' else text)
            rows.append((int(row.get('r')), values))
        return sheet, styles, dict(rows)


def endpoint(project):
    return f'/api/projects/{project["id"]}/logs/export'


def log(person, module=None, **changes):
    return {'work_date': '2026-11-01', 'owner_id': person['id'], 'module_id': module['id'] if module else None,
            'content': '完成工作', 'effective_date': '2026-11-01', **changes}


def test_export_includes_all_pages_in_list_order_and_does_not_write(client, setup_project):
    project, person, module = setup_project('全部分页导出')
    other, other_person, _ = setup_project('其他项目不导出')
    create_record(client, other, 'logs', log(other_person, content='其他项目内容'))
    with transaction() as session:
        for index in range(205):
            session.add(m.WorkLog(project_id=project['id'], code='L-EXPORT-'+str(index), owner_id=person['id'],
                                  module_id=module['id'], work_date=f'2026-10-{index%20+1:02d}', payload={'content': '工作 '+str(index)}))
        session.add(m.WorkLog(project_id=project['id'], code='L-REMOVED-EXPORT', deleted=True,
                              owner_id=person['id'], work_date='2026-11-01', payload={'content': '已移除内容'}))
    expected = []
    for page in range(1, 12):
        records = client.get('/api/records/logs', params={'project_id': project['id'], 'page': page}).json()
        expected += [r['code'] for r in records['items']]
    with Session() as session:
        before = [(r.id, r.version, r.updated_at, r.payload) for r in session.scalars(select(m.WorkLog).where(m.WorkLog.project_id == project['id']))]
    response = client.get(endpoint(project), params={'page': 10, 'size': 1})
    sheet, styles, rows = read_export(response)
    assert response.headers['x-export-count'] == '205'
    assert [row[0] for number, row in rows.items() if number >= 5] == expected
    assert rows[4] == [label for label, _ in COLUMNS]
    assert '全部分页导出' in rows[1][0] and '共 205 条' in rows[2][0]
    assert sheet.find('s:autoFilter', NS).get('ref') == 'A4:K209'
    pane = sheet.find('.//s:pane', NS)
    assert pane.get('ySplit') == '4' and pane.get('xSplit') == '2'
    assert any(item.get('formatCode') == 'yyyy-mm-dd' for item in styles.findall('.//s:numFmt', NS))
    with Session() as session:
        after = [(r.id, r.version, r.updated_at, r.payload) for r in session.scalars(select(m.WorkLog).where(m.WorkLog.project_id == project['id']))]
    assert before == after


def test_export_filters_match_list_and_resolve_names(client, setup_project):
    project, owner, module = setup_project('筛选导出')
    participant = client.post(f'/api/projects/{project["id"]}/people', json={'name': '参与同事'}).json()
    task = create_record(client, project, 'tasks', task_data(owner, module_id=module['id'])).json()
    record = create_record(client, project, 'logs', log(owner, module, task_id=task['id'], participant_ids=[participant['id']],
        content='验收 %_ 已完成', details='第一行\n第二行', next_plan='后续培训', notes='备注')).json()
    create_record(client, project, 'logs', log(owner, module, work_date='2026-11-02', content='不在日期内'))
    create_record(client, project, 'logs', log(participant, content='其他责任人'))
    filters = {'q': '%_', 'owner_id': owner['id'], 'module_id': module['id'], 'task_id': task['id'], 'start': '2026-11-01', 'end': '2026-11-01'}
    expected = client.get('/api/records/logs', params={'project_id': project['id'], **filters}).json()
    _, _, rows = read_export(client.get(endpoint(project), params=filters))
    assert len(expected['items']) == 1 and rows[5][0] == expected['items'][0]['code'] == record['code']
    assert rows[5][2:] == [module['name'], owner['name'], '参与同事', task['name'], '验收 %_ 已完成', '第一行\n第二行', '后续培训', '备注', '手工登记']
    assert (datetime(1899, 12, 30)+timedelta(days=float(rows[5][1]))).date().isoformat() == '2026-11-01'
    assert '%_' in rows[2][0] and owner['name'] in rows[2][0]
    for field in filters:
        subset = {field: filters[field]}
        expected = client.get('/api/records/logs', params={'project_id': project['id'], **subset}).json()
        _, _, actual = read_export(client.get(endpoint(project), params=subset))
        assert [row[0] for number, row in actual.items() if number >= 5] == [row['code'] for row in expected['items']]


def test_communication_disabled_dictionary_and_archived_export(client, setup_project):
    project, person, module = setup_project('沟通日志导出')
    meeting = create_record(client, project, 'communications', communication_data(person)).json()
    with transaction() as session:
        session.get(m.Member, (project['id'], person['id'])).enabled = False
        session.get(m.Module, module['id']).enabled = False
    response = client.post(f'/api/projects/{project["id"]}/archive', json={'version': project['version'], 'archived': True})
    assert response.status_code == 200
    _, _, rows = read_export(client.get(endpoint(project)))
    assert rows[5][2] == module['name'] and rows[5][3] == person['name'] and rows[5][4] == person['name']
    assert rows[5][6] == meeting['summary'] and rows[5][7] == meeting['details']
    assert rows[5][10] == '项目沟通：' + meeting['subject']


def test_empty_foreign_filter_missing_project_and_invalid_dates(client, setup_project):
    project, person, _ = setup_project('空导出')
    other, _, module = setup_project('跨项目筛选')
    create_record(client, other, 'logs', log(client.get(f'/api/projects/{other["id"]}/people').json()[0], module))
    response = client.get(endpoint(project), params={'module_id': module['id']})
    _, _, rows = read_export(response)
    assert response.headers['x-export-count'] == '0' and max(rows) == 4
    assert '无匹配项' in rows[2][0] and module['id'] not in rows[2][0]
    assert client.get('/api/projects/missing/logs/export').status_code == 404
    assert client.get(endpoint(project), params={'start': 'bad'}).status_code == 422
    assert client.get(endpoint(project), params={'start': '2026-11-02', 'end': '2026-11-01'}).status_code == 422


def test_text_is_not_executed_as_formula_or_hyperlink_and_large_cells_fail(client, setup_project):
    project, person, _ = setup_project('文本安全导出')
    values = {'content': '=1+1', 'details': '+SUM(1,2)\n中文', 'next_plan': 'https://example.com', 'notes': '@SUM(1,2)'}
    record = create_record(client, project, 'logs', log(person, **values)).json()
    _, _, rows = read_export(client.get(endpoint(project)))
    assert rows[5][6:10] == list(values.values())
    with transaction() as session:
        session.get(m.WorkLog, record['id']).payload = {'content': '超长', 'details': '中'*32768}
    response = client.get(endpoint(project))
    assert response.status_code == 422 and '32767' in response.json()['detail']
