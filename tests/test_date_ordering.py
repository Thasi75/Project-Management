from datetime import date, timedelta
import pytest
from backend import models as m
from backend.db import transaction
from .conftest import create_record, task_data
from .test_communications import data as communication_data
from .test_acceptance_materials import upload


@pytest.mark.parametrize('kind,field',[
    ('tasks','plan_start'),('communications','occurred_at'),('logs','work_date'),
    ('configurations','config_date'),('changes','change_date'),('risks','raised_date'),('costs','expense_date')])
def test_business_dates_oldest_first_across_pages_and_filters(client,setup_project,kind,field):
    project,person,module=setup_project('日期顺序-'+kind)
    dates=['2026-11-05','2026-11-01','2026-11-03','2026-11-03']
    bodies={
        'tasks':task_data(person,phase='日期顺序'),
        'communications':communication_data(person,subject='日期顺序'),
        'logs':{'owner_id':person['id'],'content':'日期顺序'},
        'configurations':{'config_name':'日期顺序','config_info':'配置内容'},
        'changes':{'title':'日期顺序','content':'变更内容'},
        'risks':{'description':'日期顺序'},
        'costs':{'expense_item':'Token','amount':'1.00','notes':'日期顺序'},
    }
    rows=[]
    for index,day in enumerate(dates):
        value=day+(' 08:00:00' if index!=2 else ' 12:00:00') if kind=='communications' else day
        body={**bodies[kind],field:value}
        if kind=='tasks':body['plan_end']=day
        response=create_record(client,project,kind,body);assert response.status_code==200,response.text
        rows.append(response.json())
    expected=[rows[i]['id'] for i in ([1,3,2,0] if kind=='communications' else [1,2,3,0])]
    def listing(**filters):
        r=client.get('/api/records/'+kind,params={'project_id':project['id'],'size':2,**filters});assert r.status_code==200,r.text
        return r.json()
    pages=[listing(page=page) for page in [1,2]]
    assert all(page['total']==4 for page in pages)
    assert [row['id'] for page in pages for row in page['items']]==expected
    assert [row['id'] for row in listing(start='2026-11-03',end='2026-11-03',q='日期顺序')['items']]==expected[1:3]


def test_unknown_expense_dates_follow_dated_records(client,setup_project):
    project,_,_=setup_project('未登记费用日期末尾')
    with transaction() as session:
        legacy=m.Cost(project_id=project['id'],code='COST-UNKNOWN-DATE',expense_item='其他',
                      amount_cents=100,expense_date=None,payload={})
        session.add(legacy);session.flush();legacy_id=legacy.id
    dated=create_record(client,project,'costs',{'expense_date':'2026-11-01','expense_item':'Token','amount':'2.00'}).json()
    r=client.get('/api/records/costs',params={'project_id':project['id']}).json()
    assert [row['id'] for row in r['items']]==[dated['id'],legacy_id]
    assert client.get('/api/metrics',params={'project_id':project['id']}).json()['direct_cost']=='3.00'


def test_acceptance_upload_time_oldest_first(client,setup_project):
    project,_,_=setup_project('验收时间顺序')
    files=[upload(client,project['id'],name=f'材料-{i}.pdf',acceptance=True) for i in range(3)]
    dates=['2026-11-05T08:00:00+08:00','2026-11-01T10:00:00+08:00','2026-11-01T09:00:00+08:00']
    with transaction() as session:
        for file,day in zip(files,dates):session.get(m.Attachment,file['id']).created_at=day
    for suffix in ['', '?acceptance_only=true']:
        response=client.get('/api/projects/'+project['id']+'/attachments'+suffix)
        assert response.status_code==200,response.text
        assert [row['id'] for row in response.json()]==[files[i]['id'] for i in [2,1,0]]


def test_briefs_sorted_by_report_period_before_pagination_and_latest_version_kept(client,setup_project):
    project,_,_=setup_project('简报日期顺序')
    other,_,_=setup_project('其他项目简报')
    ids=[]
    with transaction() as session:
        for offset in range(24,-1,-1):
            day=(date(2026,10,1)+timedelta(days=offset)).isoformat()
            brief=m.Brief(project_id=project['id'],start=day,end=day,title='日期顺序')
            session.add(brief);session.flush();ids.append(brief.id)
        session.add(m.Brief(project_id=other['id'],start='2026-09-01',end='2026-09-02',title='其他项目'))
        for number in [1,2]:
            session.add(m.BriefVersion(brief_id=ids[-1],number=number,snapshot={},content={},model='test',source='manual'))
    pages=[client.get(f'/api/projects/{project["id"]}/briefs',params={'page':page}).json() for page in [1,2]]
    assert all(page['total']==25 for page in pages)
    assert [row['id'] for page in pages for row in page['items']]==list(reversed(ids))
    assert [v['number'] for v in pages[0]['items'][0]['versions']]==[2,1]
