import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import date, timedelta
from uuid import uuid4

import pytest
from backend import reporting, models as m
from backend.config import DATA, today
from backend.db import Session, transaction
from backend.schemas import ReportContent
from .conftest import create_record


def data(project, **changes):
    return {'config_name':'服务器IP', 'config_info':'服务器环境配置\n已启用访问审计',
            'config_date':'2026-11-05', 'notes':'配置记录备注\n待复核', **changes}


def path(project, row=None):
    return f'/api/projects/{project["id"]}/records/configurations' + ('/'+row['id'] if row else '')


def preview(client, project):
    response=client.post(f'/api/projects/{project["id"]}/report-preview',json={'start':'2026-11-01','end':'2026-11-07'})
    assert response.status_code==200,response.text
    return response.json()


def test_configuration_crud_validation_isolation_and_archive(client,setup_project):
    p,_,_=setup_project('配置管理甲');other,_,_=setup_project('配置管理乙')
    for field in ['config_name','config_info','config_date']:
        missing=data(p);missing.pop(field)
        assert create_record(client,p,'configurations',missing).status_code==422
        for value in ['', '   ', None]:
            assert create_record(client,p,'configurations',data(p,**{field:value})).status_code==422
    for value in ['2026-02-30','2026-1-1',(date.fromisoformat(today())+timedelta(days=1)).isoformat()]:
        assert create_record(client,p,'configurations',data(p,config_date=value)).status_code==422
    assert create_record(client,p,'configurations',data(p,config_name='名'*201)).status_code==422
    assert create_record(client,p,'configurations',data(p,project_id=other['id'])).status_code==422
    assert client.post('/api/projects/missing/records/configurations',json=data(p),headers={'Idempotency-Key':uuid4().hex}).status_code==404
    key=uuid4().hex
    response=create_record(client,p,'configurations',data(p),key)
    assert response.status_code==200,response.text
    row=response.json();assert row['code'].startswith('CFG-')
    assert row['config_info']==data(p)['config_info'] and row['notes']==data(p)['notes']
    assert row['config_name']=='服务器IP' and row['project_id']==p['id']
    assert create_record(client,p,'configurations',data(p),key).json()['id']==row['id']
    assert create_record(client,p,'configurations',data(p,notes='不同内容'),key).status_code==409
    assert client.get(path(other,row)).status_code==422
    assert client.put(path(other,row),json=data(other,version=row['version'])).status_code==422
    assert client.put(path(p,row),json=data(p,project_id=other['id'],version=row['version'])).status_code==422
    assert client.post(path(other,row)+'/remove',json={'version':row['version'],'reason':'测试'}).status_code==422
    changed=client.put(path(p,row),json=data(p,version=row['version'],config_name='  数据库IP  ',config_info='修订后配置'))
    assert changed.status_code==200,changed.text
    updated=changed.json()
    assert updated['config_name']=='数据库IP' and updated['project_id']==p['id']
    assert client.put(path(p,row),json=data(p,version=row['version'])).status_code==409
    history=client.get(f'/api/projects/{p["id"]}/history/configurations/{row["id"]}').json()
    assert len(history)==2 and history[0]['before']['config_info']==data(p)['config_info']
    assert history[0]['before']['config_name']=='服务器IP' and history[0]['after']['config_name']=='数据库IP'
    archived=client.post(f'/api/projects/{p["id"]}/archive',json={'version':p['version'],'archived':True})
    assert archived.status_code==200
    assert client.get(path(p,row)).json()['config_info']=='修订后配置'
    assert create_record(client,p,'configurations',data(p)).status_code==409
    assert client.put(path(p,row),json=data(p,version=updated['version'])).status_code==409
    assert client.post(path(p,row)+'/remove',json={'version':updated['version'],'reason':'测试'}).status_code==409


def test_configuration_filters_pagination_and_removal(client,setup_project):
    p,_,_=setup_project('配置筛选');other,_,_=setup_project('配置隔离')
    create_record(client,other,'configurations',data(other,config_info='不应出现'))
    rows=[create_record(client,p,'configurations',data(p,config_date=f'2026-11-{i:02d}',notes='备注专用词' if i==3 else '')).json() for i in range(1,6)]
    literal=create_record(client,p,'configurations',data(p,config_name='特殊 %_ 名称',config_date='2026-11-06')).json()
    def listing(**filters):
        response=client.get('/api/records/configurations',params={'project_id':p['id'],**filters})
        assert response.status_code==200,response.text
        return response.json()
    first=listing(size=2);assert first['total']==6 and [r['config_date'] for r in first['items']]==['2026-11-01','2026-11-02']
    assert [r['id'] for r in listing(size=2,page=2)['items']]==[rows[2]['id'],rows[3]['id']]
    assert [r['id'] for r in listing(start='2026-11-02',end='2026-11-03')['items']]==[rows[1]['id'],rows[2]['id']]
    assert [r['id'] for r in listing(q='备注专用词')['items']]==[rows[2]['id']]
    assert [r['id'] for r in listing(q='%_')['items']]==[literal['id']]
    assert [r['id'] for r in listing(q='特殊')['items']]==[literal['id']]
    assert listing(q='服务器IP')['total']==5
    assert listing(q='不存在')['total']==0
    removed=client.post(path(p,literal)+'/remove',json={'version':literal['version'],'reason':'配置重复'})
    assert removed.status_code==200 and removed.json()['deleted']
    assert listing()['total']==5
    assert client.get(path(p,literal)).json()['deleted']
    assert literal['code'] not in preview(client,p)['sources']


def test_configuration_report_generation_and_immutable_versions(client,setup_project,monkeypatch):
    p,_,_=setup_project('配置简报');other,_,_=setup_project('其他配置简报')
    begin=create_record(client,p,'configurations',data(p,config_date='2026-11-01')).json()
    end=create_record(client,p,'configurations',data(p,config_date='2026-11-07')).json()
    for day in ['2026-10-31','2026-11-08']:
        create_record(client,p,'configurations',data(p,config_date=day))
    excluded=create_record(client,other,'configurations',data(other)).json()
    snap=preview(client,p)
    assert snap['counts']['configurations']==2 and snap['metrics']['本期配置记录数']==2
    assert set(k for k in snap['sources'] if k.startswith('CFG-'))=={begin['code'],end['code']}
    assert excluded['code'] not in snap['sources']
    assert snap['sources'][begin['code']]['config_info']==begin['config_info']
    assert snap['sources'][begin['code']]['config_name']=='服务器IP'
    assert snap['sources'][begin['code']]['notes']==begin['notes']
    assert any(begin['code'] in batch for batch in reporting.batches(snap))
    captured=[]
    content={'sections':[{'heading':h,'paragraphs':[{'text':'服务器环境配置已记录，并启用访问审计。','source_ids':[begin['code']]}] if h=='本期工作' else []} for h in reporting.HEADINGS]}
    class Responses:
        def parse(self,**kwargs):
            captured.append(kwargs)
            material=json.loads(kwargs['input'][1]['content'])
            assert material['sources'][begin['code']]['config_info']==begin['config_info']
            assert material['sources'][begin['code']]['config_name']=='服务器IP'
            return type('Response',(),{'status':'completed','output_parsed':ReportContent.model_validate(content)})()
    monkeypatch.setattr(reporting,'read_key',lambda:'test-only')
    monkeypatch.setattr(reporting,'OpenAI',lambda **kwargs:type('Client',(),{'responses':Responses()})())
    with transaction() as session:
        brief=m.Brief(project_id=p['id'],start=snap['start'],end=snap['end'],title='配置测试简报')
        session.add(brief);session.flush()
        job=m.Job(project_id=p['id'],brief_id=brief.id,status='等待中',model='test',snapshot=copy.deepcopy(snap))
        session.add(job);session.flush();job_id=job.id
    reporting.run_job(job_id)
    with Session() as session:
        job=session.get(m.Job,job_id);assert job.status=='成功',job.error
        vid=job.result_id
    stored=client.get('/api/brief-versions/'+vid).json()
    assert captured and stored['content']==content
    assert client.get('/api/brief-versions/'+vid+'/export/docx').status_code==200
    updated=client.put(path(p,begin),json=data(p,version=begin['version'],config_date='2026-11-01',config_name='数据库IP',config_info='配置修订内容')).json()
    assert preview(client,p)['sources'][begin['code']]['config_info']=='配置修订内容'
    assert preview(client,p)['sources'][begin['code']]['config_name']=='数据库IP'
    assert client.post(path(p,updated)+'/remove',json={'version':updated['version'],'reason':'测试移除'}).status_code==200
    assert preview(client,p)['counts']['configurations']==1
    assert client.get('/api/brief-versions/'+vid).json()==stored


def test_configuration_backup_restore_and_schema_004_upgrade(client,setup_project,tmp_path):
    p,_,_=setup_project('配置备份');row=create_record(client,p,'configurations',data(p)).json()
    backup=client.post('/api/backups').json();assert backup['schema']=='010'
    assert client.put(path(p,row),json=data(p,version=row['version'],config_info='临时修改')).status_code==200
    assert client.post('/api/backups/'+backup['name']+'/restore',json={'confirmation':'替换当前业务数据'}).status_code==200
    assert client.get(path(p,row)).json()==row
    with zipfile.ZipFile(DATA/'backups'/backup['name']) as z:
        entries={name:z.read(name) for name in z.namelist()}
    database=tmp_path/'legacy-004.db';database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('DROP TABLE project_costs')
        db.execute("DELETE FROM entity_revisions WHERE kind='costs'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='costs'")
        db.execute('DROP TABLE project_configurations')
        db.execute("DELETE FROM entity_revisions WHERE kind='configurations'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='configurations'")
        db.execute('DROP TABLE coding_work')
        db.execute("DELETE FROM entity_revisions WHERE kind='coding'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='coding'")
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='004'");db.commit()
        old_tables={name:db.execute('SELECT * FROM "'+name+'"').fetchall() for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")}
    entries['project.db']=database.read_bytes()
    manifest=json.loads(entries['manifest.json']);manifest.update(schema='004',database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json']=json.dumps(manifest).encode()
    legacy=DATA/'backups/configuration-legacy-004.zip'
    with zipfile.ZipFile(legacy,'w') as z:
        for name,content in entries.items():z.writestr(name,content)
    assert client.get('/api/backups/'+legacy.name+'/preview').status_code==200
    restored=client.post('/api/backups/'+legacy.name+'/restore',json={'confirmation':'替换当前业务数据'})
    assert restored.status_code==200,restored.text
    with closing(sqlite3.connect(DATA/'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='010'
        assert db.execute('SELECT count(*) FROM project_configurations').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name,rows in old_tables.items():assert db.execute('SELECT * FROM "'+name+'"').fetchall()==rows,name
    assert create_record(client,p,'configurations',data(p)).status_code==200


def test_configuration_schema_006_preserves_legacy_names_and_original_data(client,setup_project,tmp_path):
    p,_,_=setup_project('旧配置所属项目');other,_,_=setup_project('归档配置所属项目')
    active=create_record(client,p,'configurations',data(p)).json()
    removed=create_record(client,p,'configurations',data(p,config_info='已移除配置')).json()
    assert client.post(path(p,removed)+'/remove',json={'version':removed['version'],'reason':'旧配置'}).status_code==200
    archived=create_record(client,other,'configurations',data(other)).json()
    assert client.post(f'/api/projects/{other["id"]}/archive',json={'version':other['version'],'archived':True}).status_code==200
    backup=client.post('/api/backups').json()
    with zipfile.ZipFile(DATA/'backups'/backup['name']) as z:
        entries={name:z.read(name) for name in z.namelist()}
    database=tmp_path/'legacy-006.db';database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('ALTER TABLE project_configurations DROP COLUMN config_name')
        db.execute('DROP INDEX ix_project_costs_expense_date')
        db.execute('ALTER TABLE project_costs DROP COLUMN expense_date')
        db.execute('DROP TABLE coding_work')
        db.execute("DELETE FROM entity_revisions WHERE kind='coding'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='coding'")
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='006'");db.commit()
        # Include all legacy records and original columns, not only visible rows.
        old={name:([c[1] for c in db.execute('PRAGMA table_info("'+name+'")')],
                   db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall())
             for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")}
        expected=dict(db.execute('SELECT c.id,p.name FROM project_configurations c JOIN projects p ON p.id=c.project_id'))
    entries['project.db']=database.read_bytes()
    manifest=json.loads(entries['manifest.json']);manifest.update(schema='006',database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json']=json.dumps(manifest).encode()
    legacy=DATA/'backups/configuration-name-legacy-006.zip'
    with zipfile.ZipFile(legacy,'w') as z:
        for name,content in entries.items():z.writestr(name,content)
    assert client.get('/api/backups/'+legacy.name+'/preview').status_code==200
    response=client.post('/api/backups/'+legacy.name+'/restore',json={'confirmation':'替换当前业务数据'})
    assert response.status_code==200,response.text
    with closing(sqlite3.connect(DATA/'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='010'
        assert dict(db.execute('SELECT id,config_name FROM project_configurations'))==expected
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name,(columns,rows) in old.items():
            selected=','.join('"'+column+'"' for column in columns)
            assert db.execute('SELECT '+selected+' FROM "'+name+'" ORDER BY rowid').fetchall()==rows,name
    for project,row in [(p,active),(p,removed),(other,archived)]:
        assert client.get(path(project,row)).json()['config_name']==project['name']
    # Renaming the owning project must not silently rename configuration items.
    renamed=client.put('/api/projects/'+p['id'],json={'name':'更名后的所属项目','scope':p['scope'],
        'owner_id':p['owner_id'],'version':p['version'],'effective_date':today(),'reason':'项目更名'})
    assert renamed.status_code==200,renamed.text
    current=client.get(path(p,active)).json();assert current['config_name']==p['name']
    saved=client.put(path(p,active),json=data(p,version=current['version'],config_name='服务器IP'))
    assert saved.status_code==200,saved.text
    assert saved.json()['config_name']=='服务器IP' and saved.json()['project_id']==p['id']
    fresh=create_record(client,p,'configurations',data(p,config_name='数据库IP'))
    assert fresh.status_code==200 and fresh.json()['config_name']=='数据库IP'
