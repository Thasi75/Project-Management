import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend import models as m, service
from backend.config import DATA
from backend.db import Session, transaction
from .conftest import create_record, task_data
from .test_business import update


def data(person, **extra):
    with Session() as session:
        module_id=session.scalar(select(m.Module.id).where(m.Module.project_id==person['project_id'],m.Module.name=='项目公共事务'))
    return {'occurred_at': '2026-11-01 09:08:07', 'location': '会议室一', 'subject': '实施需求沟通', 'module_id':module_id,
            'host_id': person['id'], 'recorder_id': person['id'], 'participant_ids': [person['id']],
            'summary': '确认上线范围与培训计划', 'details': '逐项讨论并形成待办清单。', **extra}


def rows(client, project, kind):
    response = client.get('/api/records/' + kind, params={'project_id': project['id']})
    assert response.status_code == 200, response.text
    return response.json()['items']


def get(client, project, kind, ident):
    return client.get(f'/api/projects/{project["id"]}/records/{kind}/{ident}')


def remove(client, project, kind, row):
    return client.post(f'/api/projects/{project["id"]}/records/{kind}/{row["id"]}/remove', json={
        'version': row['version'], 'effective_date': '2026-11-02', 'reason': '撤销误登记'})


def test_create_mapping_idempotency_and_project_isolation(client, setup_project):
    project, host, _ = setup_project('沟通映射')
    other, _, _ = setup_project('沟通隔离')
    recorder = client.post(f'/api/projects/{project["id"]}/people', json={'name': '记录员'}).json()
    payload = data(host, recorder_id=recorder['id'], participant_ids=[recorder['id']])
    response = create_record(client, project, 'communications', payload, 'communication-once-123')
    assert response.status_code == 200, response.text
    communication = response.json()
    log = rows(client, project, 'logs')[0]
    assert log['id'] == communication['log_id'] and log['communication_id'] == communication['id']
    assert log['work_date'] == '2026-11-01' and log['owner_id'] == host['id']
    assert log['participant_ids'] == [recorder['id']]
    assert log['content'] == payload['summary'] and log['details'] == payload['details']
    assert log['module_id'] == payload['module_id'] and log['task_id'] is None
    assert create_record(client, project, 'communications', payload, 'communication-once-123').json()['id'] == communication['id']
    assert create_record(client, project, 'communications', {**payload, 'subject': '不同内容'}, 'communication-once-123').status_code == 409
    assert len(rows(client, project, 'logs')) == len(rows(client, project, 'communications')) == 1
    assert rows(client, other, 'communications') == rows(client, other, 'logs') == []
    assert get(client, other, 'communications', communication['id']).status_code == 422


def test_edit_sync_preserves_log_extras_conflicts_and_protects_linked_fields(client, setup_project):
    project, host, module = setup_project('沟通同步编辑')
    second = client.post(f'/api/projects/{project["id"]}/people', json={'name': '另一主持人'}).json()
    task = create_record(client, project, 'tasks', task_data(host)).json()
    communication = create_record(client, project, 'communications', data(host)).json()
    log = rows(client, project, 'logs')[0]
    saved = update(client, project, 'logs', log, module_id=module['id'], task_id=task['id'], next_plan='后续安排', notes='日志专用备注')
    assert saved.status_code == 200, saved.text
    revised = update(client, project, 'communications', communication, occurred_at='2026-11-02 12:34:56', host_id=second['id'],
                     participant_ids=[second['id'],host['id']], summary='修订沟通概况', details='修订详情')
    assert revised.status_code == 200, revised.text
    new_log = rows(client, project, 'logs')[0]
    assert new_log['id'] == log['id'] and revised.json()['log_id'] == log['id']
    assert new_log['work_date'] == '2026-11-02' and new_log['owner_id'] == second['id']
    assert set(new_log['participant_ids']) == {second['id'],host['id']}
    assert new_log['content'] == '修订沟通概况' and new_log['details'] == '修订详情'
    assert {key: new_log[key] for key in ('module_id','task_id','next_plan','notes')} == {
        'module_id': module['id'], 'task_id': task['id'], 'next_plan':'后续安排', 'notes':'日志专用备注'}
    assert update(client, project, 'communications', communication, subject='旧窗口').status_code == 409
    assert update(client, project, 'logs', saved.json(), notes='旧日志窗口').status_code == 409
    for field, value in {'work_date':'2026-11-03','owner_id':host['id'],'participant_ids':[], 'content':'不允许单独修改','details':'不同详情','module_id':None}.items():
        assert update(client, project, 'logs', new_log, **{field:value}).status_code == 409
    assert remove(client, project, 'logs', new_log).status_code == 409
    assert remove(client, project, 'communications', communication).status_code == 409
    assert remove(client, project, 'communications', revised.json()).status_code == 200
    assert rows(client, project, 'communications') == rows(client, project, 'logs') == []
    assert get(client, project, 'communications', communication['id']).json()['deleted'] is True
    assert get(client, project, 'logs', log['id']).json()['deleted'] is True
    for kind, ident in [('communications',communication['id']),('logs',log['id'])]:
        history = client.get(f'/api/projects/{project["id"]}/history/{kind}/{ident}').json()
        assert len(history) >= 3 and history[0]['after']['deleted'] is True


@pytest.mark.parametrize('patch', [
    {'occurred_at':'2026-11-01T09:08:07'}, {'occurred_at':'2026-11-01 09:08'}, {'occurred_at':'2026-2-1 09:08:07'},
    {'occurred_at':'2026-02-30 09:08:07'}, {'occurred_at':'2026-11-01 24:00:00'}, {'occurred_at':'2099-01-01 00:00:00'},
    {'subject':''}, {'summary':''}, {'host_id':''}, {'recorder_id':''}, {'module_id':None}, {'module_id':''}, {'module_id':'   '}
])
def test_invalid_fields_never_create_a_log(client, setup_project, patch):
    project, person, _ = setup_project('沟通校验')
    assert create_record(client, project, 'communications', data(person, **patch)).status_code == 422
    assert rows(client, project, 'communications') == rows(client, project, 'logs') == []


def test_people_boundaries_disabled_members_and_archive(client, setup_project):
    project, person, _ = setup_project('沟通人员边界')
    other, foreign, _ = setup_project('另一项目')
    for patch in [{'host_id':foreign['id']},{'recorder_id':foreign['id']},{'participant_ids':[foreign['id']]},{'participant_ids':[person['id'],person['id']]}]:
        assert create_record(client, project, 'communications', data(person, **patch)).status_code == 422
    assert rows(client, project, 'logs') == []
    communication = create_record(client, project, 'communications', data(person)).json()
    client.put(f'/api/projects/{project["id"]}/people/{person["id"]}', json={'name':person['name'],'version':person['version'],'enabled':False})
    assert create_record(client, project, 'communications', data(person)).status_code == 422
    kept = update(client, project, 'communications', communication, details='保留已停用引用')
    assert kept.status_code == 200
    assert client.post(f'/api/projects/{project["id"]}/archive', json={'version':project['version'],'archived':True}).status_code == 200
    assert create_record(client, project, 'communications', data(person)).status_code == 409
    assert update(client, project, 'communications', kept.json(), details='归档不许修改').status_code == 409
    assert remove(client, project, 'communications', kept.json()).status_code == 409
    assert get(client, project, 'communications', communication['id']).status_code == 200


def test_transaction_rolls_back_both_create_and_edit(client, setup_project, monkeypatch):
    project, person, _ = setup_project('沟通事务')
    original_sync = service.sync_relations
    def fail_communication(session, obj, kind, values):
        if kind == 'communications':
            raise HTTPException(409, '测试：沟通写入失败')
        original_sync(session, obj, kind, values)
    monkeypatch.setattr(service,'sync_relations',fail_communication)
    assert create_record(client, project, 'communications', data(person), 'rollback-key-123').status_code == 409
    assert rows(client, project, 'logs') == rows(client, project, 'communications') == []
    monkeypatch.setattr(service,'sync_relations',original_sync)
    communication = create_record(client, project, 'communications', data(person), 'rollback-key-123').json()
    before_log = rows(client, project, 'logs')[0]
    monkeypatch.setattr(service,'sync_relations',fail_communication)
    assert update(client, project, 'communications', communication, summary='不应落库').status_code == 409
    assert get(client, project, 'communications', communication['id']).json() == communication
    assert rows(client, project, 'logs')[0] == before_log


@pytest.mark.parametrize('module', [None, ''])
def test_manual_work_logs_can_omit_modules(client, setup_project, module):
    project, person, _ = setup_project('无模块日志')
    response = create_record(client, project, 'logs', {'work_date':'2026-11-01','owner_id':person['id'],'module_id':module,'content':'跨模块工作'})
    assert response.status_code == 200, response.text
    assert response.json()['module_id'] is None
    assert 'communication_id' not in response.json()
    assert update(client, project, 'logs', response.json(), content='普通日志仍可编辑').status_code == 200


def test_textarea_heights_persist_per_record_without_entering_work_logs(client, setup_project):
    project, person, _ = setup_project('沟通高度')
    first = create_record(client, project, 'communications', data(person, summary_height=240, details_height=420)).json()
    other = create_record(client, project, 'communications', data(person)).json()
    saved = get(client, project, 'communications', first['id']).json()
    assert (saved['summary_height'], saved['details_height']) == (240, 420)
    changed = update(client, project, 'communications', saved, summary_height=310, details_height=510)
    assert changed.status_code == 200, changed.text
    reopened = get(client, project, 'communications', first['id']).json()
    assert (reopened['summary_height'], reopened['details_height']) == (310, 510)
    assert reopened['log_id'] == first['log_id']
    untouched = get(client, project, 'communications', other['id']).json()
    assert untouched.get('summary_height') is None and untouched.get('details_height') is None
    log = get(client, project, 'logs', first['log_id']).json()
    assert log['content'] == first['summary'] and log['details'] == first['details']
    assert 'summary_height' not in log and 'details_height' not in log
    for invalid in (0, -1, 79, 'not-a-height'):
        response = update(client, project, 'communications', reopened, details_height=invalid)
        assert response.status_code == 422
    assert get(client, project, 'communications', first['id']).json() == reopened


def test_module_required_sync_isolation_disabled_and_legacy(client, setup_project):
    project, person, default = setup_project('沟通模块')
    other, _, foreign = setup_project('其他项目模块')
    target = client.post(f'/api/projects/{project["id"]}/modules', json={'name':'交付验收'}).json()
    payload = data(person)
    del payload['module_id']
    assert create_record(client, project, 'communications', payload).status_code == 422
    assert create_record(client, project, 'communications', data(person,module_id=foreign['id'])).status_code == 422
    assert rows(client,project,'communications') == rows(client,project,'logs') == []
    original = create_record(client,project,'communications',data(person,summary_height=250,details_height=340)).json()
    revised = update(client,project,'communications',original,module_id=target['id'])
    assert revised.status_code == 200, revised.text
    saved = get(client,project,'communications',original['id']).json()
    log = get(client,project,'logs',original['log_id']).json()
    assert saved['module_id'] == log['module_id'] == target['id']
    assert (saved['summary_height'],saved['details_height']) == (250,340)
    assert len(rows(client,project,'logs')) == 1
    assert update(client,project,'logs',log,module_id=default['id']).status_code == 409
    assert update(client,project,'communications',saved,module_id=foreign['id']).status_code == 422
    assert get(client,project,'logs',log['id']).json() == log
    snapshot=client.post(f'/api/projects/{project["id"]}/report-preview',json={'start':'2026-11-01','end':'2026-11-01'}).json()
    assert snapshot['counts']['logs']==1
    assert target['name'] in json.dumps(snapshot,ensure_ascii=False)
    assert client.put(f'/api/projects/{project["id"]}/modules/{target["id"]}',json={'version':target['version'],'name':target['name'],'enabled':False}).status_code==200
    assert create_record(client,project,'communications',data(person,module_id=target['id'])).status_code==422
    # Simulate a pre-field record whose linked log already held a disabled module.
    with transaction() as session:
        obj=session.get(m.Communication,saved['id'])
        obj.payload={key:value for key,value in obj.payload.items() if key!='module_id'}
    legacy=get(client,project,'communications',saved['id']).json()
    assert legacy['module_id']==target['id']
    kept=update(client,project,'communications',legacy,summary='保留既有停用模块')
    assert kept.status_code==200,kept.text
    assert get(client,project,'logs',log['id']).json()['module_id']==target['id']
    with transaction() as session:
        obj=session.get(m.Communication,saved['id']);obj.payload={key:value for key,value in obj.payload.items() if key!='module_id'}
        session.get(m.WorkLog,log['id']).module_id=None
    unassigned=get(client,project,'communications',saved['id']).json()
    assert not unassigned.get('module_id')
    assert update(client,project,'communications',unassigned,module_id=default['id']).status_code==200
    assert get(client,project,'logs',log['id']).json()['module_id']==default['id']


def test_search_dates_snapshot_and_current_backup(client, setup_project):
    project, person, _ = setup_project('沟通搜索备份')
    first = create_record(client, project, 'communications', data(person, occurred_at='2026-11-01 00:00:00')).json()
    last = create_record(client, project, 'communications', data(person, occurred_at='2026-11-01 23:59:59', subject='晚间线上交流', location='远程', participant_ids=[])).json()
    for term in ('晚间线上','远程','确认上线','逐项讨论'):
        result=client.get('/api/records/communications',params={'project_id':project['id'],'q':term,'start':'2026-11-01','end':'2026-11-01','host_id':person['id']}).json()
        assert last['id'] in {row['id'] for row in result['items']}
    assert [row['id'] for row in rows(client,project,'communications')] == [first['id'], last['id']]
    snap=client.post(f'/api/projects/{project["id"]}/report-preview',json={'start':'2026-11-01','end':'2026-11-01'}).json()
    assert snap['counts']['logs'] == 2
    assert len([source for source in snap['sources'] if source.startswith('L-')]) == 2
    assert not any(source.startswith('M-') for source in snap['sources'])
    frozen=copy.deepcopy(snap)
    with transaction() as session:
        brief=m.Brief(project_id=project['id'],start='2026-11-01',end='2026-11-01',title='沟通日志快照')
        session.add(brief);session.flush()
        version=m.BriefVersion(brief_id=brief.id,number=1,snapshot=frozen,content={'sections':[]},model='test',source='测试')
        session.add(version);session.flush();vid=version.id
    backup=client.post('/api/backups').json()
    assert backup['schema']=='009'
    assert remove(client,project,'communications',last).status_code==200
    assert client.get('/api/brief-versions/'+vid).json()['snapshot']==frozen
    assert client.post('/api/backups/'+backup['name']+'/restore',json={'confirmation':'替换当前业务数据'}).status_code==200
    assert len(rows(client,project,'communications'))==len(rows(client,project,'logs'))==2
    with sqlite3.connect(DATA/'project.db') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
