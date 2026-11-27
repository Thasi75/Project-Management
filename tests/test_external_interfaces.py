from datetime import date, timedelta

from backend import models as m
from backend.config import today
from backend.db import Session, transaction
from .conftest import create_record
from .test_research import data, path


def endpoint(project, row=None):
    return f'/api/projects/{project["id"]}/external-interfaces' + ('/' + row['id'] if row else '')


def payload(row, **changes):
    return {'version': row['version'], 'status': row['status'], 'development_notes': row.get('development_notes', ''),
            'go_live_date': row.get('go_live_date'), **changes}


def create_interface(client, project, person, module, **changes):
    response = create_record(client, project, 'research', data(person, module, is_interface=True, integration_system='HIS', **changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_unlaunched_interface_metric_scope_and_list_filters(client, setup_project):
    p, person, module = setup_project('未上线接口统计')
    other, other_person, other_module = setup_project('接口指标隔离')
    metric = '/api/metrics?project_id=' + p['id']
    assert client.get(metric).json()['unlaunched_interfaces'] == 0
    create_interface(client, p, person, module, status='设计')
    create_interface(client, p, person, module, status='开发')
    create_interface(client, p, person, module, status='上线', go_live_date=today())
    create_interface(client, other, other_person, other_module)
    normal = create_record(client, p, 'research', data(person, module)).json()
    with transaction() as session:
        legacy = session.get(m.Research, normal['id'])
        legacy.payload = {key: value for key, value in legacy.payload.items() if key != 'is_interface'}
    assert client.get(metric).json()['unlaunched_interfaces'] == 2
    assert client.get('/api/metrics?project_id=' + other['id']).json()['unlaunched_interfaces'] == 1
    for filters in [{'size': 1, 'page': 2}, {'status': '上线'}, {'q': '不存在的接口'}]:
        assert client.get(endpoint(p), params=filters).status_code == 200
        assert client.get(metric).json()['unlaunched_interfaces'] == 2


def test_unlaunched_interface_metric_tracks_both_editors_and_removal(client, setup_project):
    p, person, module = setup_project('接口指标刷新')
    row = create_interface(client, p, person, module)
    metric = '/api/metrics?project_id=' + p['id']
    assert client.get(metric).json()['unlaunched_interfaces'] == 1
    response = client.put(endpoint(p, row), json=payload(row, status='上线', go_live_date=today()))
    assert response.status_code == 200, response.text
    row = response.json()
    assert client.get(metric).json()['unlaunched_interfaces'] == 0
    response = client.put(path(p, row), json=data(person, module, version=row['version'],
                          is_interface=True, integration_system='HIS', status='开发'))
    assert response.status_code == 200, response.text
    row = response.json()
    assert client.get(metric).json()['unlaunched_interfaces'] == 1
    response = client.put(path(p, row), json=data(person, module, version=row['version'], is_interface=False))
    assert response.status_code == 200, response.text
    row = response.json()
    assert client.get(metric).json()['unlaunched_interfaces'] == 0
    response = client.put(path(p, row), json=data(person, module, version=row['version'],
                          is_interface=True, integration_system='HIS'))
    assert response.status_code == 200, response.text
    row = response.json()
    assert client.get(metric).json()['unlaunched_interfaces'] == 1
    assert client.post(path(p, row) + '/remove', json={'version': row['version'], 'reason': '移除'}).status_code == 200
    assert client.get(metric).json()['unlaunched_interfaces'] == 0


def test_unlaunched_interface_metric_archived_project_and_global_totals(client, setup_project):
    p, person, module = setup_project('归档接口指标')
    create_interface(client, p, person, module)
    before = client.get('/api/metrics').json()['unlaunched_interfaces']
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert client.get('/api/metrics?project_id=' + p['id']).json()['unlaunched_interfaces'] == 1
    assert client.get('/api/metrics').json()['unlaunched_interfaces'] == before - 1


def test_external_interfaces_live_list_order_filters_and_scope(client, setup_project):
    p, person, module = setup_project('外部接口列表')
    other, other_person, other_module = setup_project('其他接口项目')
    create_interface(client, other, other_person, other_module)
    create_record(client, p, 'research', data(person, module, sequence=1))
    later = create_interface(client, p, person, module, sequence=8)
    first = create_interface(client, p, person, module, sequence=3, status='开发')
    changed = client.put(endpoint(p, first), json=payload(first, development_notes='已完成联调\n等待验证')).json()
    assert changed['id'] == first['id']
    listing = client.get(endpoint(p)).json()
    assert listing['total'] == 2
    assert [row['id'] for row in listing['items']] == [first['id'], later['id']]
    assert client.get(endpoint(p), params={'size': 1, 'page': 2}).json()['items'][0]['id'] == later['id']
    for filters in [{'q': '联调'}, {'status': '开发'}, {'source_id': person['id'], 'status': '开发', 'q': '联调'}]:
        result = client.get(endpoint(p), params=filters).json()
        assert result['total'] == 1 and result['items'][0]['id'] == first['id']
    assert client.get(endpoint(p), params={'source_id': other_person['id']}).json()['total'] == 0
    assert client.get(endpoint(p), params={'page': 0}).status_code == 422
    assert client.get(endpoint({'id': 'missing'})).status_code == 404


def test_external_interface_updates_shared_record_and_retains_details_on_research_save(client, setup_project):
    p, person, module = setup_project('接口同步')
    row = create_interface(client, p, person, module)
    before = client.post(f'/api/projects/{p["id"]}/report-preview', json={'start': '2026-11-01', 'end': today()}).json()
    response = client.put(endpoint(p, row), json=payload(row, status='上线', development_notes='接口开发完成\n联调通过', go_live_date=today()))
    assert response.status_code == 200, response.text
    live = response.json()
    assert live['version'] == row['version'] + 1
    assert client.get(path(p, row)).json() == live
    for key in ['sequence', 'integration_system', 'requirement', 'solution', 'source_id', 'module_id', 'research_date']:
        assert live[key] == row[key]
    # Existing research clients omit the new date and cannot erase interface details.
    response = client.put(path(p, row), json=data(person, module, version=live['version'], is_interface=True,
                          integration_system='HIS', status='上线', requirement='新的原始需求'))
    assert response.status_code == 200, response.text
    edited = response.json()
    external = client.get(endpoint(p, row)).json()
    assert external == edited
    assert external['requirement'] == '新的原始需求'
    assert external['development_notes'] == live['development_notes'] and external['go_live_date'] == today()
    reverted = client.put(path(p, row), json=data(person, module, version=edited['version'], is_interface=True,
                          integration_system='HIS', status='开发')).json()
    assert client.get(endpoint(p, row)).json()['status'] == '开发'
    assert reverted['development_notes'] == live['development_notes'] and reverted['go_live_date'] == today()
    history = client.get(f'/api/projects/{p["id"]}/history/research/{row["id"]}').json()
    change = next(item for item in history if item['reason'] == '维护外部接口')
    assert change['before']['status'] == '设计' and change['after']['status'] == '上线'
    assert change['after']['go_live_date'] == today()
    with Session() as session:
        assert len(session.query(m.Research).filter_by(project_id=p['id']).all()) == 1
    after = client.post(f'/api/projects/{p["id"]}/report-preview', json={'start': '2026-11-01', 'end': today()}).json()
    before.pop('captured_at'); after.pop('captured_at')
    assert before == after


def test_external_interface_dates_and_research_validation(client, setup_project):
    p, person, module = setup_project('接口日期规则')
    row = create_interface(client, p, person, module)
    tomorrow = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
    for value in [None, '', '  ', '2026-02-30', '2026-1-01', tomorrow]:
        response = client.put(endpoint(p, row), json=payload(row, status='上线', go_live_date=value))
        assert response.status_code == 422, response.text
        assert client.get(endpoint(p, row)).json() == row
    for changes in [{'status': '完成'}, {'development_notes': None}, {'version': None}, {'version': '1'}]:
        assert client.put(endpoint(p, row), json=payload(row, **changes)).status_code == 422
    response = client.put(path(p, row), json=data(person, module, version=row['version'], is_interface=True,
                          integration_system='HIS', status='上线'))
    assert response.status_code == 422 and '上线日期' in response.text
    assert create_record(client, p, 'research', data(person, module, is_interface=True, integration_system='HIS', status='上线')).status_code == 422
    assert create_record(client, p, 'research', data(person, module, status='上线')).status_code == 200
    success = client.put(path(p, row), json=data(person, module, version=row['version'], is_interface=True,
                         integration_system='HIS', status='上线', go_live_date=today()))
    assert success.status_code == 200
    assert client.get(endpoint(p, row)).json()['go_live_date'] == today()
    assert client.put(endpoint(p, row), json=payload(success.json(), go_live_date=None)).status_code == 422


def test_external_interface_readonly_fields_version_and_archived_protection(client, setup_project):
    p, person, module = setup_project('接口编辑边界')
    other, _, _ = setup_project('接口越界')
    row = create_interface(client, p, person, module)
    for key, value in [('sequence', 99), ('integration_system', '修改系统'), ('requirement', '篡改需求'),
                       ('solution', '篡改方案'), ('source_id', person['id']), ('is_interface', False), ('project_id', other['id'])]:
        assert client.put(endpoint(p, row), json={**payload(row), key: value}).status_code == 422
    assert client.get(endpoint(p, row)).json() == row
    assert client.get(endpoint(other, row)).status_code == 422
    assert client.put(endpoint(other, row), json=payload(row)).status_code == 422
    saved = client.put(endpoint(p, row), json=payload(row, status='开发')).json()
    assert client.put(endpoint(p, row), json=payload(row, development_notes='旧窗口覆盖')).status_code == 409
    assert client.put(path(p, row), json=data(person, module, version=row['version'], is_interface=True, integration_system='HIS')).status_code == 409
    assert client.get(endpoint(p, row)).json() == saved
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert client.get(endpoint(p)).json()['total'] == 1
    assert client.get(endpoint(p, row)).status_code == 200
    assert client.put(endpoint(p, row), json=payload(saved, development_notes='归档修改')).status_code == 409


def test_external_interface_hide_reenable_and_remove_preserve_details(client, setup_project):
    p, person, module = setup_project('接口显隐')
    row = create_interface(client, p, person, module)
    saved = client.put(endpoint(p, row), json=payload(row, status='开发', development_notes='保留的开发情况', go_live_date=today())).json()
    hidden = client.put(path(p, row), json=data(person, module, version=saved['version'], is_interface=False, status='开发')).json()
    assert client.get(endpoint(p)).json()['total'] == 0
    assert client.get(endpoint(p, row)).status_code == 409
    assert client.put(endpoint(p, row), json=payload(hidden)).status_code == 409
    assert hidden['development_notes'] == saved['development_notes'] and hidden['go_live_date'] == saved['go_live_date']
    shown = client.put(path(p, row), json=data(person, module, version=hidden['version'], is_interface=True, integration_system='新系统')).json()
    assert client.get(endpoint(p)).json()['total'] == 1
    assert shown['development_notes'] == saved['development_notes'] and shown['go_live_date'] == saved['go_live_date']
    assert client.post(path(p, row)+'/remove', json={'version': shown['version'], 'reason': '移除'}).status_code == 200
    assert client.get(endpoint(p)).json()['total'] == 0
    assert client.get(endpoint(p, row)).status_code == 422
    assert client.put(endpoint(p, row), json=payload(shown)).status_code == 422
    with Session() as session:
        assert session.get(m.Research, row['id']).payload['development_notes'] == '保留的开发情况'


def test_external_interface_legacy_defaults_and_backup_restore(client, setup_project):
    p, person, module = setup_project('接口历史')
    row = create_interface(client, p, person, module)
    with transaction() as session:
        legacy = session.get(m.Research, row['id'])
        legacy.status = '上线'
        old_payload = {key: value for key, value in legacy.payload.items() if key not in ('development_notes', 'go_live_date')}
        legacy.payload = dict(old_payload)
    loaded = client.get(endpoint(p, row)).json()
    assert loaded['development_notes'] == '' and loaded['go_live_date'] is None
    with Session() as session:
        assert session.get(m.Research, row['id']).payload == old_payload
    assert client.put(endpoint(p, row), json=payload(loaded)).status_code == 422
    fixed = client.put(endpoint(p, row), json=payload(loaded, go_live_date=today(), development_notes='补录日期')).json()
    backup = client.post('/api/backups').json()
    assert client.put(endpoint(p, row), json=payload(fixed, development_notes='后续修改')).status_code == 200
    assert client.post('/api/backups/'+backup['name']+'/restore', json={'confirmation': '替换当前业务数据'}).status_code == 200
    assert client.get(endpoint(p, row)).json() == fixed
    assert client.get(path(p, row)).json() == fixed
