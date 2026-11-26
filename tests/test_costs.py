import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import date, timedelta
from uuid import uuid4

import pytest
from backend import reporting,models as m
from backend.config import DATA, today
from backend.db import Session,transaction
from backend.schemas import ReportContent
from .conftest import create_record


ITEMS=['省际交通费','市内交通费','住宿费','业务招待费','Token','其他']


def data(**changes):
    return {'expense_date':'2026-11-05','expense_item':'省际交通费','amount':'10.20','notes':'差旅备注\n第二行',**changes}


def path(project,row):
    return f'/api/projects/{project["id"]}/records/costs/{row["id"]}'


def total(client,p):
    result=client.get('/api/metrics',params={'project_id':p['id']})
    assert result.status_code==200,result.text
    return result.json()['direct_cost']


def test_cost_categories_amount_normalization_and_notes(client,setup_project):
    p,_,_=setup_project('费用字段')
    assert total(client,p)=='0.00'
    for item,amount,expected in zip(ITEMS,['0',0.1,'1.20',2,'3.45','1.25'],['0.00','0.10','1.20','2.00','3.45','1.25']):
        response=create_record(client,p,'costs',data(expense_item=item,amount=amount))
        assert response.status_code==200,response.text
        row=response.json()
        assert row['amount']==expected and row['expense_item']==item
        assert row['expense_date']=='2026-11-05'
        assert row['notes']==data()['notes'] and row['project_id']==p['id']
        assert 'amount_cents' not in row
    assert total(client,p)=='8.00'


@pytest.mark.parametrize('changes',[
    {'amount':''},{'amount':None},{'amount':'  '},{'amount':True},
    {'amount':'-0.01'},{'amount':'1.001'},{'amount':'1.000'},
    {'amount':'NaN'},{'amount':'Infinity'},{'amount':'1e2'},
    {'amount':'100000000000000'},{'amount':'1,200.00'},
    {'expense_item':''},{'expense_item':None},{'expense_item':['其他']},{'expense_item':'机票'},
    {'expense_date':''},{'expense_date':None},{'expense_date':'   '},{'expense_date':'2026-02-30'},
    {'expense_date':'2026-1-1'},{'expense_date':(date.fromisoformat(today())+timedelta(days=1)).isoformat()},
])
def test_invalid_costs_rejected(client,setup_project,changes):
    p,_,_=setup_project('费用校验')
    assert create_record(client,p,'costs',data(**changes)).status_code==422
    assert total(client,p)=='0.00'


def test_cost_required_fields_and_project_isolation(client,setup_project):
    p,_,_=setup_project('费用甲');other,_,_=setup_project('费用乙')
    for field in ['expense_date','expense_item','amount']:
        body=data();body.pop(field)
        assert create_record(client,p,'costs',body).status_code==422
    row=create_record(client,p,'costs',data()).json()
    assert client.get(path(other,row)).status_code==422
    assert client.put(path(other,row),json=data(version=row['version'])).status_code==422
    assert client.post(path(other,row)+'/remove',json={'version':row['version'],'reason':'跨项目'}).status_code==422
    assert create_record(client,p,'costs',data(project_id=other['id'])).status_code==422
    assert total(client,other)=='0.00'
    missing=client.post('/api/projects/missing/records/costs',json=data(),headers={'Idempotency-Key':uuid4().hex})
    assert missing.status_code==404


def test_cost_exact_total_edit_remove_idempotency_and_archive(client,setup_project):
    p,_,_=setup_project('精确汇总');other,_,_=setup_project('其他项目费用')
    key=uuid4().hex
    a=create_record(client,p,'costs',data(amount='0.10'),key).json()
    assert create_record(client,p,'costs',data(amount='0.1'),key).json()['id']==a['id']
    assert create_record(client,p,'costs',data(amount='0.20'),key).status_code==409
    b=create_record(client,p,'costs',data(amount='0.20')).json()
    create_record(client,other,'costs',data(amount='999.99'))
    assert total(client,p)=='0.30'
    response=client.put(path(p,a),json=data(expense_date='2026-11-06',expense_item='Token',amount='1.01',version=a['version']))
    assert response.status_code==200,response.text
    updated=response.json();assert total(client,p)=='1.21'
    assert client.put(path(p,a),json=data(version=a['version'])).status_code==409
    history=client.get(f'/api/projects/{p["id"]}/history/costs/{a["id"]}').json()
    assert history[0]['before']['amount']=='0.10' and history[0]['after']['amount']=='1.01'
    assert history[0]['before']['expense_date']=='2026-11-05' and history[0]['after']['expense_date']=='2026-11-06'
    assert history[0]['after']['expense_item']=='Token'
    assert client.post(path(p,b)+'/remove',json={'version':b['version'],'reason':'误登记'}).status_code==200
    assert total(client,p)=='1.01'
    assert client.get(path(p,b)).json()['deleted']
    assert client.post(f'/api/projects/{p["id"]}/archive',json={'version':p['version'],'archived':True}).status_code==200
    assert total(client,p)=='1.01' and client.get(path(p,updated)).status_code==200
    assert create_record(client,p,'costs',data()).status_code==409
    assert client.put(path(p,updated),json=data(version=updated['version'])).status_code==409
    assert client.post(path(p,updated)+'/remove',json={'version':updated['version'],'reason':'测试'}).status_code==409


def test_cost_total_all_pages_independent_of_filters_and_large_amounts(client,setup_project):
    p,_,_=setup_project('费用分页')
    rows=[create_record(client,p,'costs',data(amount='1.01',expense_item=ITEMS[i%5],notes='字面 %_' if i==0 else f'费用备注{i}')).json() for i in range(25)]
    def listing(**filters):
        r=client.get('/api/records/costs',params={'project_id':p['id'],**filters});assert r.status_code==200,r.text
        return r.json()
    first=listing();assert first['total']==25 and len(first['items'])==20
    assert first['items'][0]['id']==rows[0]['id']
    assert len(listing(page=2)['items'])==5
    assert listing(expense_item='住宿费')['total']==5
    assert listing(q='%_')['items'][0]['id']==rows[0]['id']
    assert listing(q='不存在')['total']==0
    assert total(client,p)=='25.25'
    huge,_,_=setup_project('大额精度')
    for _ in range(2):
        r=create_record(client,huge,'costs',data(amount='99999999999999.99'))
        assert r.status_code==200,r.text
        assert r.json()['amount']=='99999999999999.99'
    assert total(client,huge)=='199999999999999.98'
    with Session() as session:
        stored=session.get(m.Cost,r.json()['id'])
        assert isinstance(stored.amount_cents,int) and stored.amount_cents==9999999999999999


def test_costs_excluded_from_report_sources_metrics_and_model_input(client,setup_project,monkeypatch):
    p,_,_=setup_project('费用不进入简报')
    period={'start':'2026-11-01','end':'2026-11-07'}
    def snapshot():
        r=client.post(f'/api/projects/{p["id"]}/report-preview',json=period);assert r.status_code==200,r.text
        return r.json()
    before=snapshot()
    row=create_record(client,p,'costs',data(expense_item='Token',amount='9876.54',notes='只用于成本台账的独特备注')).json()
    after=snapshot()
    assert {k:v for k,v in before.items() if k!='captured_at'}=={k:v for k,v in after.items() if k!='captured_at'}
    assert row['code'] not in after['sources'] and 'costs' not in after['counts']
    assert 'direct_cost' not in after['metrics'] and '项目直接成本' not in after['metrics']
    assert total(client,p)=='9876.54'
    content={'sections':[{'heading':h,'paragraphs':[{'text':'项目实施范围已确认。','source_ids':['PROJECT']}] if h=='项目概况' else []} for h in reporting.HEADINGS]}
    seen=[]
    class Responses:
        def parse(self,**kwargs):
            text=json.dumps(kwargs['input'],ensure_ascii=False)
            for forbidden in [row['code'],'9876.54','只用于成本台账的独特备注','direct_cost','expense_date','expense_item','amount_cents','Token']:
                assert forbidden not in text
            seen.append(text)
            return type('Response',(),{'status':'completed','output_parsed':ReportContent.model_validate(content)})()
    monkeypatch.setattr(reporting,'read_key',lambda:'test-only')
    monkeypatch.setattr(reporting,'OpenAI',lambda **kwargs:type('Client',(),{'responses':Responses()})())
    with transaction() as session:
        brief=m.Brief(project_id=p['id'],title='不含费用的简报',**period);session.add(brief);session.flush()
        job=m.Job(project_id=p['id'],brief_id=brief.id,status='等待中',model='test',snapshot=copy.deepcopy(after));session.add(job);session.flush();jid=job.id
    reporting.run_job(jid)
    with Session() as session:
        job=session.get(m.Job,jid);assert job.status=='成功',job.error
        stored=session.get(m.BriefVersion,job.result_id)
        assert row['code'] not in stored.snapshot['sources'] and stored.content==content
    assert seen


def test_cost_backup_roundtrip_and_schema_005_upgrade(client,setup_project,tmp_path):
    p,_,_=setup_project('费用备份');row=create_record(client,p,'costs',data()).json()
    backup=client.post('/api/backups').json();assert backup['schema']=='009'
    assert client.put(path(p,row),json=data(version=row['version'],amount='30.00')).status_code==200
    assert client.post('/api/backups/'+backup['name']+'/restore',json={'confirmation':'替换当前业务数据'}).status_code==200
    assert client.get(path(p,row)).json()==row and total(client,p)=='10.20'
    with zipfile.ZipFile(DATA/'backups'/backup['name']) as z:entries={name:z.read(name) for name in z.namelist()}
    database=tmp_path/'legacy-005.db';database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        db.execute('ALTER TABLE project_configurations DROP COLUMN config_name')
        db.execute('DROP TABLE project_costs')
        db.execute("DELETE FROM entity_revisions WHERE kind='costs'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='costs'")
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='005'");db.commit()
        old_columns={name:[c[1] for c in db.execute('PRAGMA table_info("'+name+'")')] for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old_tables={name:db.execute('SELECT * FROM "'+name+'"').fetchall() for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")}
    entries['project.db']=database.read_bytes()
    manifest=json.loads(entries['manifest.json']);manifest.update(schema='005',database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json']=json.dumps(manifest).encode()
    legacy=DATA/'backups/cost-legacy-005.zip'
    with zipfile.ZipFile(legacy,'w') as z:
        for name,content in entries.items():z.writestr(name,content)
    assert client.get('/api/backups/'+legacy.name+'/preview').status_code==200
    restored=client.post('/api/backups/'+legacy.name+'/restore',json={'confirmation':'替换当前业务数据'})
    assert restored.status_code==200,restored.text
    with closing(sqlite3.connect(DATA/'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='009'
        assert db.execute('SELECT count(*) FROM project_costs').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name,rows in old_tables.items():
            columns=','.join('"'+column+'"' for column in old_columns[name])
            assert db.execute('SELECT '+columns+' FROM "'+name+'"').fetchall()==rows,name
    assert total(client,p)=='0.00'
    assert create_record(client,p,'costs',data()).status_code==200


def test_cost_occurrence_date_sorting_and_inclusive_filter(client,setup_project):
    p,_,_=setup_project('费用发生日期')
    late=create_record(client,p,'costs',data(expense_date='2026-11-07',expense_item='Token',amount='0.10')).json()
    early=create_record(client,p,'costs',data(expense_date='2026-11-01',amount='0.20')).json()
    middle=create_record(client,p,'costs',data(expense_date='2026-11-05',expense_item='Token',amount='1.00')).json()
    def listing(**filters):
        r=client.get('/api/records/costs',params={'project_id':p['id'],**filters});assert r.status_code==200,r.text
        return r.json()['items']
    assert [r['id'] for r in listing()]==[early['id'],middle['id'],late['id']]
    assert [r['id'] for r in listing(start='2026-11-05',end='2026-11-07')]==[middle['id'],late['id']]
    assert [r['id'] for r in listing(start='2026-11-05',end='2026-11-05')]==[middle['id']]
    assert [r['id'] for r in listing(expense_item='Token')]==[middle['id'],late['id']]
    assert listing(start='2026-11-08')==[]
    assert total(client,p)=='1.30'


def test_cost_schema_007_keeps_legacy_amounts_and_unknown_dates(client,setup_project,tmp_path):
    p,_,_=setup_project('历史费用日期')
    active=create_record(client,p,'costs',data(amount='12.34')).json()
    removed=create_record(client,p,'costs',data(amount='1.23')).json()
    assert client.post(path(p,removed)+'/remove',json={'version':removed['version'],'reason':'重复'}).status_code==200
    backup=client.post('/api/backups').json()
    with zipfile.ZipFile(DATA/'backups'/backup['name']) as z:
        entries={name:z.read(name) for name in z.namelist()}
    database=tmp_path/'legacy-007.db';database.write_bytes(entries['project.db'])
    with closing(sqlite3.connect(database)) as db:
        # Build a genuine pre-change expense table in this synthetic backup.
        db.execute('''CREATE TABLE legacy_costs (
            id VARCHAR PRIMARY KEY, project_id VARCHAR NOT NULL REFERENCES projects(id),
            code VARCHAR NOT NULL UNIQUE, deleted BOOLEAN NOT NULL, payload JSON NOT NULL,
            version INTEGER NOT NULL, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL,
            expense_item VARCHAR NOT NULL, amount_cents BIGINT NOT NULL,
            UNIQUE(id,project_id),
            CONSTRAINT ck_cost_amount CHECK(amount_cents >= 0 AND amount_cents <= 9999999999999999),
            CONSTRAINT ck_cost_expense_item CHECK(expense_item IN ('省际交通费','市内交通费','住宿费','业务招待费','其他')))''')
        db.execute('''INSERT INTO legacy_costs
            SELECT id,project_id,code,deleted,payload,version,created_at,updated_at,
                   CASE expense_item WHEN 'Token' THEN '其他' ELSE expense_item END,amount_cents FROM project_costs''')
        db.execute('DROP TABLE project_costs')
        db.execute('ALTER TABLE legacy_costs RENAME TO project_costs')
        db.execute('CREATE INDEX ix_project_costs_project_id ON project_costs(project_id)')
        db.execute('CREATE INDEX ix_project_costs_expense_item ON project_costs(expense_item)')
        db.execute('DROP TABLE requirement_research')
        db.execute("DELETE FROM entity_revisions WHERE kind='research'")
        db.execute("DELETE FROM idempotency_keys WHERE kind='research'")
        db.execute("UPDATE alembic_version SET version_num='007'");db.commit()
        before={name:([c[1] for c in db.execute('PRAGMA table_info("'+name+'")')],
                      db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall())
                for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('sqlite_sequence','alembic_version')")}
    entries['project.db']=database.read_bytes()
    manifest=json.loads(entries['manifest.json']);manifest.update(schema='007',database_sha256=hashlib.sha256(entries['project.db']).hexdigest())
    entries['manifest.json']=json.dumps(manifest).encode()
    legacy=DATA/'backups/cost-date-legacy-007.zip'
    with zipfile.ZipFile(legacy,'w') as z:
        for name,content in entries.items():z.writestr(name,content)
    assert client.get('/api/backups/'+legacy.name+'/preview').status_code==200
    response=client.post('/api/backups/'+legacy.name+'/restore',json={'confirmation':'替换当前业务数据'})
    assert response.status_code==200,response.text
    with closing(sqlite3.connect(DATA/'project.db')) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='009'
        assert db.execute('SELECT count(*) FROM project_costs WHERE expense_date IS NOT NULL').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for name,(columns,rows) in before.items():
            selected=','.join('"'+column+'"' for column in columns)
            assert db.execute('SELECT '+selected+' FROM "'+name+'" ORDER BY rowid').fetchall()==rows,name
    for row in [active,removed]:
        legacy_row=client.get(path(p,row)).json()
        assert legacy_row['expense_date'] is None and legacy_row['amount']==row['amount']
    assert total(client,p)=='12.34'
    saved=client.put(path(p,active),json=data(expense_date='2026-11-01',expense_item='Token',amount='12.34',version=active['version']))
    assert saved.status_code==200,saved.text
    assert saved.json()['expense_date']=='2026-11-01' and saved.json()['expense_item']=='Token'
    assert total(client,p)=='12.34'
