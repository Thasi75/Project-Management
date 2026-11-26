import json
from backend.db import Session
from backend import models as m
from backend.service import serialize
from .conftest import create_record, task_data


def update(client, p, kind, row, **patch):
    from backend.main import SCHEMAS
    fields = SCHEMAS[kind].model_fields
    data = {k: v for k, v in row.items() if k in fields}
    data.update(patch)
    return client.put(f'/api/projects/{p["id"]}/records/{kind}/{row["id"]}', json=data)


def test_project_isolation_archive_scope(client, setup_project):
    p, person, module = setup_project('甲')
    other, _, other_module = setup_project('乙')
    task = create_record(client, p, 'tasks', task_data(person)).json()
    bad = create_record(client, p, 'logs', {'work_date':'2026-11-02','module_id':other_module['id'],'owner_id':person['id'],'content':'不应成功'})
    assert bad.status_code == 422
    assert client.get('/api/records/tasks?project_id='+other['id']).json()['total'] == 0
    from backend.schemas import ProjectInput
    payload = {k:v for k,v in p.items() if k in ProjectInput.model_fields}
    payload.update(scope='增加报表培训',effective_date='2026-11-02',reason='新增培训范围')
    response = client.put('/api/projects/'+p['id'],json=payload)
    assert response.status_code == 200, response.text
    p=response.json()
    scopes=client.get('/api/projects/'+p['id']+'/scopes').json()
    assert len(scopes)==2 and scopes[-1]['scope'] != scopes[0]['scope']
    archived=client.post('/api/projects/'+p['id']+'/archive',json={'version':p['version'],'archived':True}).json()
    assert create_record(client,p,'tasks',task_data(person)).status_code==409
    assert client.post('/api/projects/'+p['id']+'/archive',json={'version':archived['version'],'archived':False}).status_code==200


def test_task_lifecycle_and_date_guards(client, setup_project):
    p,person,module=setup_project()
    assert create_record(client,p,'tasks',task_data(person,plan_end='2026-10-01')).status_code==422
    assert create_record(client,p,'tasks',task_data(person,status='已完成')).status_code==422
    assert create_record(client,p,'tasks',task_data(person,status='进行中',actual_start='2099-01-01')).status_code==422
    row=create_record(client,p,'tasks',task_data(person)).json()
    assert update(client,p,'tasks',row,status='暂停',reason='错误转换').status_code==422
    started=update(client,p,'tasks',row,status='进行中',actual_start='2026-11-02',effective_date='2026-11-02',reason='开始').json()
    paused=update(client,p,'tasks',started,status='暂停',effective_date='2026-11-03',reason='等待客户').json()
    complete=update(client,p,'tasks',paused,status='已完成',actual_end='2026-11-10',actual_deliverable='上线记录',effective_date='2026-11-10',reason='交付').json()
    assert complete['status']=='已完成'
    reopened=update(client,p,'tasks',complete,status='进行中',actual_end=None,effective_date='2026-11-12',reason='缺陷重开').json()
    assert reopened['actual_deliverable']=='上线记录' and reopened['actual_end'] is None
    assert update(client,p,'tasks',complete,reason='过期窗口').status_code==409
    canceled=update(client,p,'tasks',reopened,status='已取消',effective_date='2026-11-13',reason='取消').json()
    assert update(client,p,'tasks',canceled,status='未开始',actual_start=None,effective_date='2026-11-14',reason='恢复错误状态').status_code==422
    assert update(client,p,'tasks',canceled,status='进行中',effective_date='2026-11-14',reason='恢复').status_code==200
    history=client.get(f'/api/projects/{p["id"]}/history/tasks/{row["id"]}').json()
    assert len(history)>=6


def test_task_start_order_across_pages_and_filters(client, setup_project):
    p, person, module = setup_project('任务排序')
    dates = ['2026-11-20', '2026-11-03', '2026-10-28', '2026-11-03', '2026-12-01']
    created = []
    for index, start in enumerate(dates):
        response = create_record(client, p, 'tasks', task_data(
            person, name=f'排序任务{index}', plan_start=start, plan_end=start,
            phase='实施' if index % 2 == 0 else '准备'))
        assert response.status_code == 200, response.text
        created.append(response.json())
    base = f'/api/records/tasks?project_id={p["id"]}&size=2'
    pages = [client.get(base + f'&page={page}').json() for page in range(1, 4)]
    rows = [row for page in pages for row in page['items']]
    assert all(page['total'] == 5 for page in pages)
    assert [row['plan_start'] for row in rows] == sorted(dates)
    assert {row['id'] for row in rows} == {row['id'] for row in created}
    assert [row['id'] for row in client.get(base).json()['items']] == [row['id'] for row in rows[:2]]
    filtered = client.get(base + '&phase=实施&q=排序任务').json()
    assert filtered['total'] == 3
    assert [row['plan_start'] for row in filtered['items']] == ['2026-10-28', '2026-11-20']

    # Work logs use the same oldest-first business-date ordering.
    for work_date in ['2026-11-03', '2026-11-01']:
        response = create_record(client, p, 'logs', {
            'module_id': module['id'], 'owner_id': person['id'],
            'content': '排序验收', 'work_date': work_date})
        assert response.status_code == 200, response.text
    logs = client.get('/api/records/logs?project_id=' + p['id']).json()['items']
    assert [row['work_date'] for row in logs] == ['2026-11-01', '2026-11-03']


def test_logs_and_change_contract(client, setup_project):
    p,person,module=setup_project()
    p2,person2,module2=setup_project('隔离')
    task=create_record(client,p,'tasks',task_data(person)).json()
    other=create_record(client,p2,'tasks',task_data(person2)).json()
    log={'work_date':'2026-11-03','module_id':module['id'],'owner_id':person['id'],'task_id':task['id'],'content':'联调验证','participant_ids':[person['id']]}
    assert create_record(client,p,'logs',log).status_code==200
    assert create_record(client,p,'logs',log).status_code==200
    assert client.get('/api/records/logs?project_id='+p['id']+'&start=2026-11-03&end=2026-11-03').json()['total']==2
    assert client.get('/api/records/tasks?project_id='+p['id']).json()['items'][0]['status']=='未开始'
    change={'title':'新增订单导出','content':'登记导出字段','change_date':'2026-11-04','task_ids':[task['id']]}
    first=create_record(client,p,'changes',change,'idempotency-123456').json()
    same=create_record(client,p,'changes',change,'idempotency-123456').json()
    assert first['id']==same['id'] and 'status' not in first
    assert create_record(client,p,'changes',{**change,'title':'另一个内容'},'idempotency-123456').status_code==409
    assert create_record(client,p,'changes',{**change,'status':'已确认'}).status_code==422
    assert create_record(client,p,'changes',{**change,'task_ids':[other['id']]}).status_code==422
    assert len(client.get('/api/projects/'+p['id']+'/scopes').json())==1
    edited=update(client,p,'changes',first,impact='预计补充培训',reason='补充说明').json()
    assert edited['version']==2
    assert client.post(f'/api/projects/{p["id"]}/records/changes/{first["id"]}/remove',json={'version':2,'reason':'撤销误录','effective_date':'2026-11-05'}).status_code==200
    assert client.get('/api/records/changes?project_id='+p['id']).json()['total']==0


def test_disabled_dictionary_and_empty_metrics(client,setup_project):
    p,person,module=setup_project()
    metrics=client.get('/api/metrics?project_id='+p['id']).json()
    assert metrics['completion_rate'] is None
    assert metrics['not_started'] == 0
    assert metrics['project_progress'] == 0
    task=create_record(client,p,'tasks',task_data(person,module_id=module['id'])).json()
    response=client.put('/api/projects/'+p['id']+'/people/'+person['id'],json={'version':person['version'],'name':person['name'],'enabled':False})
    assert response.status_code==200
    assert create_record(client,p,'tasks',task_data(person)).status_code==422
    assert update(client,p,'tasks',task,notes='保留已有引用',effective_date='2026-11-01').status_code==200
    module_disabled=client.put(f'/api/projects/{p["id"]}/modules/{module["id"]}',json={'version':module['version'],'name':module['name'],'enabled':False})
    assert module_disabled.status_code==200


def test_not_started_metric_tracks_project_task_status(client, setup_project):
    p, person, _ = setup_project('未开始指标')
    other, other_person, _ = setup_project('指标隔离')
    waiting = create_record(client, p, 'tasks', task_data(person)).json()
    future = create_record(client, p, 'tasks', task_data(
        person, name='未来计划', plan_start='2099-01-01', plan_end='2099-01-07')).json()
    for status, extra in [
        ('进行中', {'actual_start': '2026-11-01'}),
        ('已完成', {'actual_start': '2026-11-01', 'actual_end': '2026-11-07', 'actual_deliverable': '验收完成'}),
        ('已取消', {}),
    ]:
        response = create_record(client, p, 'tasks', task_data(person, status=status, **extra))
        assert response.status_code == 200, response.text
    assert create_record(client, other, 'tasks', task_data(other_person)).status_code == 200

    result = client.get('/api/metrics?project_id=' + p['id']).json()
    assert result['not_started'] == 2
    assert (result['total'], result['completed'], result['completion_rate']) == (5, 1, 25.0)
    assert update(client, p, 'tasks', waiting, status='进行中', actual_start='2026-11-01', reason='任务开始').status_code == 200
    assert client.get('/api/metrics?project_id=' + p['id']).json()['not_started'] == 1
    removed = client.post(f'/api/projects/{p["id"]}/records/tasks/{future["id"]}/remove', json={
        'version': future['version'], 'effective_date': '2026-11-01', 'reason': '移除测试任务'})
    assert removed.status_code == 200, removed.text
    assert client.get('/api/metrics?project_id=' + p['id']).json()['not_started'] == 0
    assert client.get('/api/metrics?project_id=' + other['id']).json()['not_started'] == 1


def test_project_progress_weights_inclusive_planned_days(client, setup_project):
    p, person, _ = setup_project('计划天数进度')
    other, other_person, _ = setup_project('计划天数隔离')
    done = create_record(client, p, 'tasks', task_data(
        person, plan_start='2026-10-31', plan_end='2026-11-01', status='已完成',
        actual_start='2026-10-20', actual_end='2026-10-25', actual_deliverable='完成')).json()
    waiting = create_record(client, p, 'tasks', task_data(
        person, plan_start='2099-01-01', plan_end='2099-01-13')).json()
    canceled = create_record(client, p, 'tasks', task_data(
        person, plan_start='2026-11-03', plan_end='2026-11-03', status='已取消')).json()
    assert create_record(client, other, 'tasks', task_data(other_person)).status_code == 200
    url = '/api/metrics?project_id=' + p['id']
    result = client.get(url).json()
    # 2 / (2 + 13 + 1) = 12.5%, including a same-day canceled task; actual duration is irrelevant.
    assert result['project_progress'] == 13
    assert isinstance(result['project_progress'], int)
    assert result['completion_rate'] == 50.0
    assert client.get('/api/metrics?project_id=' + other['id']).json()['project_progress'] == 0
    assert client.get('/api/records/tasks?project_id=' + p['id'] + '&status=已完成&size=1').json()['total'] == 1
    assert client.get(url).json()['project_progress'] == 13

    removed = client.post(f'/api/projects/{p["id"]}/records/tasks/{canceled["id"]}/remove', json={
        'version': canceled['version'], 'effective_date': '2026-11-10', 'reason': '移除取消项'})
    assert removed.status_code == 200, removed.text
    response = update(client, p, 'tasks', waiting, plan_start='2026-11-02', plan_end='2026-11-09', reason='调整计划')
    assert response.status_code == 200, response.text
    waiting = response.json()
    assert client.get(url).json()['project_progress'] == 20  # 2 / (2 + 8).
    response = update(client, p, 'tasks', waiting, status='已完成', actual_start='2026-11-02',
                      actual_end='2026-11-09', actual_deliverable='完成', reason='任务完成')
    assert response.status_code == 200, response.text
    assert client.get(url).json()['project_progress'] == 100
    assert update(client, p, 'tasks', done, status='进行中', actual_end=None, reason='重新打开').status_code == 200
    assert client.get(url).json()['project_progress'] == 80
    archived = client.post('/api/projects/' + p['id'] + '/archive', json={'version': p['version'], 'archived': True})
    assert archived.status_code == 200
    assert client.get(url).json()['project_progress'] == 80


def test_attachment_upload_backup_restore(client,setup_project):
    p,person,module=setup_project('恢复样例')
    files=[]
    for payload in [b'first',b'second']:
        response=client.post('/api/attachments/upload?project_id='+p['id'],files={'file':('同名.txt',payload,'text/plain')})
        assert response.status_code==200,response.text
        files.append(response.json())
    assert files[0]['id'] != files[1]['id']
    assert client.post('/api/attachments/upload?project_id='+p['id'],files={'file':('bad.exe',b'bad')}).status_code==422
    staged=client.post('/api/attachments/upload',files={'file':('cancel.txt',b'tmp')}).json()
    assert client.delete('/api/attachments/staged/'+staged['id']).status_code==200
    task=create_record(client,p,'tasks',task_data(person,attachment_ids=[files[0]['id']])).json()
    from backend.db import transaction
    from backend.reporting import HEADINGS
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    content={'sections':[{'heading':h,'paragraphs':[]} for h in HEADINGS]}
    with transaction() as session:
        brief=m.Brief(project_id=p['id'],start='2026-11-01',end='2026-11-07',title='恢复前简报')
        session.add(brief);session.flush()
        version=m.BriefVersion(brief_id=brief.id,number=1,snapshot=snap,content=content,model='test',source='恢复验收')
        session.add(version);session.flush();vid=version.id
    backup=client.post('/api/backups').json()
    preview=client.get('/api/backups/'+backup['name']+'/preview')
    assert preview.status_code==200 and preview.json()['valid']
    extra=create_record(client,p,'changes',{'title':'备份后的记录','content':'恢复时应消失'}).json()
    assert client.post('/api/backups/'+backup['name']+'/restore',json={'confirmation':'错误'}).status_code==422
    restored=client.post('/api/backups/'+backup['name']+'/restore',json={'confirmation':'替换当前业务数据'})
    assert restored.status_code==200,restored.text
    assert 'before-restore' in restored.json()['safety_backup']
    assert client.get('/api/records/changes?project_id='+p['id']).json()['total']==0
    assert client.get('/api/attachments/'+files[0]['id']+'/download').content==b'first'
    assert client.get('/api/records/tasks?project_id='+p['id']).json()['items'][0]['attachment_ids']==[files[0]['id']]
    restored_version=client.get('/api/brief-versions/'+vid).json()
    assert restored_version['snapshot']==snap and restored_version['content']==content
    assert client.get('/api/brief-versions/'+vid+'/export/docx').status_code==200


def test_loopback_origin_guard(client):
    assert client.post('/api/people',json={'name':'跨域'},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/projects',headers={'Host':'evil.example'}).status_code==403
