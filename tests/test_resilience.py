import copy
import json
import zipfile
from pathlib import Path
from sqlalchemy import select
from backend.config import DATA
from backend.db import Session,transaction,engine
from backend import models as m,reporting
from .conftest import create_record,task_data
from .test_business import update


def test_chinese_keyword_filters_and_pagination(client,setup_project):
    p,person,module=setup_project('分页与中文检索')
    for i in range(23):
        create_record(client,p,'logs',{'work_date':'2026-11-03','module_id':module['id'],'owner_id':person['id'],'content':f'库存联调第{i}项'})
    first=client.get('/api/records/logs',params={'project_id':p['id'],'q':'库存联调','size':20}).json()
    second=client.get('/api/records/logs',params={'project_id':p['id'],'q':'库存联调','size':20,'page':2}).json()
    assert first['total']==23 and len(first['items'])==20 and len(second['items'])==3
    assert set(x['id'] for x in first['items']).isdisjoint(x['id'] for x in second['items'])


def test_tampered_backup_does_not_replace_data(client,setup_project):
    p,person,module=setup_project('损坏备份')
    backup=client.post('/api/backups').json()
    original=DATA/'backups'/backup['name']
    corrupt=DATA/'backups'/'tampered-test.zip'
    with zipfile.ZipFile(original) as source,zipfile.ZipFile(corrupt,'w') as target:
        for name in source.namelist():
            target.writestr(name,b'invalid database' if name=='project.db' else source.read(name))
    assert client.get('/api/backups/tampered-test.zip/preview').status_code==422
    assert client.post('/api/backups/tampered-test.zip/restore',json={'confirmation':'替换当前业务数据'}).status_code==422
    assert any(x['id']==p['id'] for x in client.get('/api/projects').json())


def test_period_plan_delay_does_not_rewrite_old_plan(client,setup_project):
    p,person,module=setup_project('延期修订')
    task=create_record(client,p,'tasks',task_data(person,plan_end='2026-11-05')).json()
    update(client,p,'tasks',task,plan_end='2026-11-20',effective_date='2026-11-08',reason='确认延期')
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    assert snap['sources'][task['code']]['plan_end']=='2026-11-05'
    assert snap['metrics']['期末逾期任务数']==1
    assert client.post('/api/projects/'+p['id']+'/records/changes/x/transition',json={}).status_code==404


def test_snapshot_names_are_immutable(client,setup_project):
    p,person,module=setup_project('名称快照')
    create_record(client,p,'tasks',task_data(person,module_id=module['id']))
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    copy_before=copy.deepcopy(snap)
    client.put('/api/projects/'+p['id']+'/people/'+person['id'],json={'name':'新的显示名称','version':person['version']})
    with transaction() as session:
        brief=m.Brief(project_id=p['id'],start='2026-11-01',end='2026-11-07',title='固定快照')
        session.add(brief);session.flush()
        version=m.BriefVersion(brief_id=brief.id,number=1,snapshot=snap,content={'sections':[]},model='test',source='测试')
        session.add(version);session.flush();vid=version.id
    assert client.get('/api/brief-versions/'+vid).json()['snapshot']==copy_before


def test_risk_close_and_reopen_are_separate_facts(client,setup_project):
    p,person,module=setup_project('风险重开')
    risk=create_record(client,p,'risks',{'description':'外部接口问题','raised_date':'2026-11-01','status':'已关闭','closed_date':'2026-11-03','effective_date':'2026-11-03'}).json()
    reopened=update(client,p,'risks',risk,status='处理中',closed_date=None,effective_date='2026-11-05',reason='复测出现').json()
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    assert snap['metrics']['期内关闭风险数']==1
    assert snap['metrics']['期末未关闭风险数']==1


def test_restart_persistence_and_sqlite_integrity(client,setup_project):
    p,person,module=setup_project('持久化')
    row=create_record(client,p,'tasks',task_data(person)).json()
    engine.dispose()
    with Session() as session:
        assert session.get(m.Task,row['id']).name==row['name']
        assert session.connection().exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
        assert not session.connection().exec_driver_sql('PRAGMA foreign_key_check').all()
