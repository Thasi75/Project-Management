from datetime import date, timedelta

from backend import models as m
from backend.config import today
from backend.db import transaction
from .conftest import create_record, task_data
from .test_external_interfaces import create_interface, endpoint
from .test_research import data


def result(client, project, kind, **filters):
    response = client.get('/api/records/' + kind, params={'project_id': project['id'], **filters})
    assert response.status_code == 200, response.text
    return response.json()


def metrics(client, project):
    return client.get('/api/metrics', params={'project_id': project['id']}).json()


def test_task_metric_lists_share_counts_and_overdue_boundary(client, setup_project):
    p, person, _ = setup_project('任务卡片联动')
    other, other_person, _ = setup_project('任务卡片隔离')
    past = (date.fromisoformat(today()) - timedelta(days=7)).isoformat()
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    tomorrow = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
    overdue_ids = set()
    for status in ['未开始', '进行中', '暂停', '已完成', '已取消']:
        extra = {'actual_start': past} if status in ('进行中', '暂停', '已完成') else {}
        if status == '已完成':
            extra.update(actual_end=yesterday, actual_deliverable='交付完成')
        response = create_record(client, p, 'tasks', task_data(person, name=status, status=status,
                                 plan_start=past, plan_end=yesterday, **extra))
        assert response.status_code == 200, response.text
        if status not in ('已完成', '已取消'):
            overdue_ids.add(response.json()['id'])
    for end in [today(), tomorrow]:
        assert create_record(client, p, 'tasks', task_data(person, plan_start=end, plan_end=end)).status_code == 200
    assert create_record(client, other, 'tasks', task_data(other_person, plan_start=past, plan_end=yesterday)).status_code == 200
    values = metrics(client, p)
    assert result(client, p, 'tasks')['total'] == values['total'] == 7
    assert result(client, p, 'tasks', status='已完成')['total'] == values['completed'] == 1
    assert result(client, p, 'tasks', status='未开始')['total'] == values['not_started'] == 3
    selected = result(client, p, 'tasks', overdue=True)
    assert selected['total'] == values['overdue'] == 3
    assert {row['id'] for row in selected['items']} == overdue_ids
    assert result(client, p, 'tasks', overdue=True, size=1, page=2)['total'] == 3
    assert result(client, p, 'tasks', overdue=True, status='已完成')['total'] == 0
    assert result(client, p, 'tasks', overdue=True, q='暂停')['total'] == 1
    row = selected['items'][0]
    assert client.post(f'/api/projects/{p["id"]}/records/tasks/{row["id"]}/remove', json={'version': row['version'], 'reason': '移除'}).status_code == 200
    assert result(client, p, 'tasks', overdue=True)['total'] == metrics(client, p)['overdue'] == 2
    assert client.get('/api/records/tasks', params={'overdue': 'invalid'}).status_code == 422
    assert client.get('/api/records/logs', params={'overdue': True}).status_code == 422


def test_risk_metric_list_supports_not_closed_and_combinations(client, setup_project):
    p, person, _ = setup_project('风险卡片联动')
    other, _, _ = setup_project('风险卡片隔离')
    for status in ['待处理', '处理中', '已关闭']:
        response = create_record(client, p, 'risks', {'description': status, 'status': status,
                                 'owner_id': person['id'], 'closed_date': today() if status == '已关闭' else None})
        assert response.status_code == 200, response.text
    assert create_record(client, other, 'risks', {'description': '其他项目风险'}).status_code == 200
    rows = result(client, p, 'risks', status_ne='已关闭')
    assert rows['total'] == metrics(client, p)['risks'] == 2
    assert {row['status'] for row in rows['items']} == {'待处理', '处理中'}
    assert result(client, p, 'risks', status_ne='已关闭', status='处理中', size=1)['total'] == 1
    assert result(client, p, 'risks', status_ne='已关闭', q='不存在')['total'] == 0
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert result(client, p, 'risks', status_ne='已关闭')['total'] == metrics(client, p)['risks'] == 2
    assert client.get('/api/records/logs', params={'status_ne': '已关闭'}).status_code == 422


def test_interface_metric_list_uses_not_equal_with_legacy_records(client, setup_project):
    p, person, module = setup_project('接口卡片联动')
    other, other_person, other_module = setup_project('接口卡片隔离')
    for status in ['设计', '开发', '上线']:
        create_interface(client, p, person, module, status=status, go_live_date=today() if status == '上线' else None)
    legacy = create_interface(client, p, person, module)
    removed = create_interface(client, p, person, module)
    assert create_record(client, p, 'research', data(person, module)).status_code == 200
    create_interface(client, other, other_person, other_module)
    with transaction() as session:
        old = session.get(m.Research, legacy['id'])
        old.payload = {key: value for key, value in old.payload.items() if key not in ('go_live_date', 'development_notes')}
        session.get(m.Research, removed['id']).deleted = True
    url = endpoint(p)
    response = client.get(url, params={'status_ne': '上线', 'size': 1, 'page': 2})
    assert response.status_code == 200, response.text
    assert response.json()['total'] == metrics(client, p)['unlaunched_interfaces'] == 3
    rows = client.get(url, params={'status_ne': '上线'}).json()['items']
    assert {row['status'] for row in rows} == {'设计', '开发'}
    assert sum(row['status'] == '设计' for row in rows) == 2
    assert client.get(url, params={'status_ne': '上线', 'status': '开发', 'source_id': person['id']}).json()['total'] == 1
    assert client.get(url, params={'status_ne': '上线', 'status': '上线'}).json()['total'] == 0
    assert client.get(url).json()['total'] == 4
    assert client.post(f'/api/projects/{p["id"]}/archive', json={'version': p['version'], 'archived': True}).status_code == 200
    assert client.get(url, params={'status_ne': '上线'}).json()['total'] == metrics(client, p)['unlaunched_interfaces'] == 3
