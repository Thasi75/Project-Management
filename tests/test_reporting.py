import copy
import pytest
import httpx
from sqlalchemy import select
from backend import reporting,models as m
from backend.db import Session,transaction
from backend.schemas import ReportContent
from .conftest import create_record,task_data
from .test_business import update


def test_period_history_scope_risk_and_snapshots(client,setup_project):
    p,person,module=setup_project('历史边界')
    task=create_record(client,p,'tasks',task_data(person,status='已完成',actual_start='2026-11-01',actual_end='2026-11-10',actual_deliverable='验收清单',effective_date='2026-11-10')).json()
    log=create_record(client,p,'logs',{'work_date':'2026-11-03','module_id':module['id'],'owner_id':person['id'],'content':'本期联调','task_id':task['id']}).json()
    change=create_record(client,p,'changes',{'title':'补录的需求','content':'补充库存字段','change_date':'2026-11-05'}).json()
    risk=create_record(client,p,'risks',{'description':'环境延迟','raised_date':'2026-11-02','status':'已关闭','closed_date':'2026-11-09','effective_date':'2026-11-09'}).json()
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    assert snap['metrics']['本期完成任务数']==0
    assert snap['sources'][task['code']]['status']=='进行中'
    assert snap['metrics']['期末未关闭风险数']==1
    assert snap['metrics']['期内关闭风险数']==0
    assert snap['counts']['changes']==1
    assert snap['sources'][change['code']]['content']=='补充库存字段'
    assert 'status' not in snap['sources'][change['code']]
    assert client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-11'}).json()['metrics']['本期完成任务数']==1
    update(client,p,'tasks',task,status='进行中',actual_end=None,effective_date='2026-11-12',reason='重开')
    earlier=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-11'}).json()
    assert earlier['sources'][task['code']]['status']=='已完成'
    assert earlier['metrics']['本期完成任务数']==1


def test_generation_versions_retry_export(client,setup_project,monkeypatch):
    p,person,module=setup_project('简报中文验证')
    create_record(client,p,'tasks',task_data(person))
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    content={'sections':[{'heading':h,'paragraphs':[{'text':'项目实施进展已记录，后续继续开展交付验证。','source_ids':['PROJECT']}]} for h in reporting.HEADINGS]}
    class FakeResponses:
        def parse(self,**kwargs):
            assert kwargs['store'] is False
            assert kwargs['text_format'] is ReportContent
            return type('Response',(),{'status':'completed','output_parsed':ReportContent.model_validate(content)})()
    monkeypatch.setattr(reporting,'read_key',lambda:'test-only')
    monkeypatch.setattr(reporting,'OpenAI',lambda **kwargs:type('FakeClient',(),{'responses':FakeResponses()})())
    with transaction() as session:
        b=m.Brief(project_id=p['id'],start='2026-11-01',end='2026-11-07',title='中文简报')
        session.add(b);session.flush()
        job=m.Job(project_id=p['id'],brief_id=b.id,status='等待中',model='test',snapshot=snap)
        session.add(job);session.flush();job_id=job.id
    reporting.run_job(job_id)
    with Session() as session:
        job=session.get(m.Job,job_id)
        assert job.status=='成功',job.error
        result_id=job.result_id
        brief=session.get(m.Brief,job.brief_id)
        version=brief.version
        bid=brief.id
    result=client.get('/api/brief-versions/'+result_id).json()
    content['sections'][0]['paragraphs'][0]['text']='人工补充后的中文内容。'
    edited=client.post('/api/briefs/'+bid+'/versions',json={'version':version,'base_version_id':result_id,'content':content})
    assert edited.status_code==200,edited.text
    assert client.get('/api/brief-versions/'+result_id).json()['content']!=edited.json()['content']
    assert client.get('/api/brief-versions/'+result_id+'/export/docx').status_code==200
    missing=client.get('/api/brief-versions/'+result_id+'/export/pdf')
    assert missing.status_code in (200,503)
    with transaction() as session:
        job=m.Job(project_id=p['id'],brief_id=bid,status='等待中',model='test',snapshot=snap)
        session.add(job);session.flush();failed_id=job.id
    monkeypatch.setattr(reporting,'read_key',lambda:'')
    reporting.run_job(failed_id)
    with Session() as session:
        assert session.get(m.Job,failed_id).status=='失败'
        assert len(list(session.scalars(select(m.BriefVersion).where(m.BriefVersion.brief_id==bid))))==2


def test_report_validation_rejects_unknown_sources_and_numbers():
    import pytest
    from fastapi import HTTPException
    snap={'sources':{'T-1':{'name':'任务','count':2}},'start':'2026-11-01','end':'2026-11-07'}
    content={'sections':[{'heading':h,'paragraphs':[]} for h in reporting.HEADINGS]}
    content['sections'][0]['paragraphs']=[{'text':'完成 999 项','source_ids':['T-1']}]
    with pytest.raises(HTTPException):reporting.validate_content(content,snap)
    content['sections'][0]['paragraphs']=[{'text':'完成','source_ids':['OTHER']}]
    with pytest.raises(HTTPException):reporting.validate_content(content,snap)


def test_backdated_completion_correction_and_reopen(client,setup_project):
    p,person,module=setup_project('日期更正')
    task=create_record(client,p,'tasks',task_data(person,status='已完成',actual_start='2026-11-01',actual_end='2026-11-10',actual_deliverable='交付记录',effective_date='2026-11-10')).json()
    corrected=update(client,p,'tasks',task,actual_end='2026-11-06',effective_date='2026-11-06',reason='更正误填完成日期').json()
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    assert snap['metrics']['本期完成任务数']==1
    assert snap['sources'][task['code']]['status']=='已完成'
    reopened=update(client,p,'tasks',corrected,status='进行中',actual_end=None,effective_date='2026-11-07',reason='缺陷重开').json()
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-08'}).json()
    assert snap['metrics']['本期完成任务数']==1
    assert snap['metrics']['期末已完成任务数']==0
    assert snap['sources'][task['code']]['status']=='进行中'


@pytest.mark.parametrize('failure,retryable,message', [
    ('timeout', True, '超时'), ('auth', False, '认证失败'),
    ('rate', True, '限流'), ('incomplete', True, '输出不完整'),
    ('connection', True, '检查网络或代理'), ('permission', True, '网络访问被系统权限阻止'),
])
def test_generation_failure_preserves_saved_versions(client,setup_project,monkeypatch,failure,retryable,message):
    from backend import main
    p,person,module=setup_project('失败保护'+failure)
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    content={'sections':[{'heading':h,'paragraphs':[]} for h in reporting.HEADINGS]}
    content['sections'][0]['paragraphs']=[{'text':'保留人工修订的内容。','source_ids':['PROJECT']}]
    with transaction() as session:
        b=m.Brief(project_id=p['id'],start='2026-11-01',end='2026-11-07',title='保留正文')
        session.add(b);session.flush();bid=b.id
        v=m.BriefVersion(brief_id=bid,number=1,snapshot=snap,content=content,model='test',source='人工修订')
        session.add(v);session.flush();vid=v.id
        job=m.Job(project_id=p['id'],brief_id=bid,status='等待中',model='test',snapshot=snap)
        session.add(job);session.flush();jid=job.id
    class FailedResponses:
        def parse(self,**kwargs):
            request=httpx.Request('POST','https://api.openai.com/v1/responses')
            if failure=='timeout': raise reporting.APITimeoutError(request=request)
            if failure=='connection': raise reporting.APIConnectionError(request=request)
            if failure=='permission':
                denied=OSError(10013,'secret must not appear')
                transport=httpx.ConnectError('secret must not appear',request=request)
                transport.__cause__=denied
                raise reporting.APIConnectionError(request=request) from transport
            if failure=='auth': raise reporting.AuthenticationError('secret must not appear',response=httpx.Response(401,request=request),body=None)
            if failure=='rate': raise reporting.RateLimitError('test',response=httpx.Response(429,request=request),body=None)
            return type('Response',(),{'status':'incomplete','output_parsed':None})()
    monkeypatch.setattr(reporting,'read_key',lambda:'test-only')
    monkeypatch.setattr(reporting,'OpenAI',lambda **kwargs:type('FakeClient',(),{'responses':FailedResponses()})())
    monkeypatch.setattr(main.executor,'submit',lambda *args:None)
    reporting.run_job(jid)
    jobs=client.get('/api/projects/'+p['id']+'/jobs').json()
    assert jobs[0]['status']=='失败' and jobs[0]['retryable']==retryable
    assert message in jobs[0]['error'] and 'secret' not in jobs[0]['error']
    assert client.get('/api/brief-versions/'+vid).json()['content']==content
    if retryable:
        for attempt in (2,3):
            assert client.post('/api/jobs/'+jid+'/retry').status_code==200
            reporting.run_job(jid)
            assert client.get('/api/projects/'+p['id']+'/jobs').json()[0]['attempts']==attempt
    assert client.post('/api/jobs/'+jid+'/retry').status_code==409
    with Session() as session:
        assert len(list(session.scalars(select(m.BriefVersion).where(m.BriefVersion.brief_id==bid))))==1


def test_large_input_batches_preserve_every_character(monkeypatch):
    import json
    monkeypatch.setattr(reporting,'config',lambda:{'batch_chars':4000})
    oversized={'content':'长篇联调记录'*3000,'name':'超长来源'}
    snap={'sources':{'PROJECT':{'name':'验证'},'METRICS':{},'L-LONG':oversized,'L-LAST':{'content':'最后一条记录'}}}
    parts=list(reporting.batches(snap))
    assert len(parts)>2
    chunks=[part['L-LONG']['text'] for part in parts if 'L-LONG' in part]
    assert ''.join(chunks)==json.dumps(oversized,ensure_ascii=False)
    assert parts[-1]['L-LAST']==snap['sources']['L-LAST']


def test_missing_pdf_component_keeps_word_available(client,setup_project,monkeypatch):
    from backend import exports
    p,person,module=setup_project('缺失转换组件')
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    with transaction() as session:
        b=m.Brief(project_id=p['id'],start='2026-11-01',end='2026-11-07',title='导出保护')
        session.add(b);session.flush()
        v=m.BriefVersion(brief_id=b.id,number=1,snapshot=snap,content={'sections':[{'heading':h,'paragraphs':[]} for h in reporting.HEADINGS]},model='test',source='验收')
        session.add(v);session.flush();vid=v.id
    monkeypatch.setattr(exports,'soffice_path',lambda:'')
    assert client.get('/api/brief-versions/'+vid+'/export/docx').status_code==200
    result=client.get('/api/brief-versions/'+vid+'/export/pdf')
    assert result.status_code==503 and 'Word 仍可导出' in result.json()['detail']


@pytest.mark.parametrize('final_error', [False, True])
def test_multiple_batches_are_synthesized_before_saving(client,setup_project,monkeypatch,final_error):
    import json
    p,person,module=setup_project('整篇统稿')
    snap=client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':'2026-11-07'}).json()
    calls=[]
    def content(text):
        return ReportContent(sections=[{'heading':h,'paragraphs':[{'text':text,'source_ids':['PROJECT']}]} for h in reporting.HEADINGS])
    class Responses:
        def parse(self,**kwargs):
            payload=json.loads(kwargs['input'][1]['content'])
            calls.append(payload)
            if 'drafts' in payload:
                assert len(payload['drafts'])==2
                assert all('材料整理' in d['sections'][0]['paragraphs'][0]['text'] for d in payload['drafts'])
                if final_error: raise reporting.APIConnectionError(request=httpx.Request('POST','https://api.openai.com/v1/responses'))
                parsed=content('项目各项工作有序推进，重点交付情况如下。')
            else:
                parsed=content('材料整理：已开展实施工作。')
            return type('Response',(),{'status':'completed','output_parsed':parsed})()
    monkeypatch.setattr(reporting,'batches',lambda s:iter([s['sources'],s['sources']]))
    monkeypatch.setattr(reporting,'read_key',lambda:'test-only')
    monkeypatch.setattr(reporting,'OpenAI',lambda **kwargs:type('Client',(),{'responses':Responses()})())
    with transaction() as session:
        brief=m.Brief(project_id=p['id'],start=snap['start'],end=snap['end'],title='统稿验证')
        session.add(brief);session.flush()
        old=m.BriefVersion(brief_id=brief.id,number=1,snapshot=snap,content=content('既有正文保留。').model_dump(),model='test',source='人工编辑')
        session.add(old)
        job=m.Job(project_id=p['id'],brief_id=brief.id,status='等待中',model='test',snapshot=snap)
        session.add(job);session.flush();jid,bid=job.id,brief.id
    reporting.run_job(jid)
    assert len(calls)==3
    with Session() as session:
        job=session.get(m.Job,jid)
        versions=list(session.scalars(select(m.BriefVersion).where(m.BriefVersion.brief_id==bid).order_by(m.BriefVersion.number)))
        assert versions[0].content['sections'][0]['paragraphs'][0]['text']=='既有正文保留。'
        assert len(versions)==(1 if final_error else 2)
        assert job.status==('失败' if final_error else '成功')
        if not final_error:
            assert versions[-1].content['sections'][0]['paragraphs'][0]['text']=='项目各项工作有序推进，重点交付情况如下。'
            assert versions[-1].snapshot['batch_count']==2
            assert versions[-1].snapshot['report_style']=='formal-v2'


def test_historical_report_progress_uses_planned_days(client,setup_project):
    p,person,module=setup_project('简报计划天数进度')
    completed=create_record(client,p,'tasks',task_data(person,plan_end='2026-11-03',status='已完成',actual_start='2026-11-01',actual_end='2026-11-03',actual_deliverable='交付文档',effective_date='2026-11-03')).json()
    create_record(client,p,'tasks',task_data(person,plan_start='2026-11-04',plan_end='2026-11-04'))
    def preview(end):
        return client.post('/api/projects/'+p['id']+'/report-preview',json={'start':'2026-11-01','end':end}).json()['metrics']
    assert preview('2026-11-02')['项目进度']=='0%'
    assert preview('2026-11-03')['项目进度']=='75%'
    assert preview('2026-11-03')['任务完成率']=='50.0%'
    update(client,p,'tasks',completed,status='进行中',actual_end=None,effective_date='2026-11-05',reason='重新处理')
    assert preview('2026-11-03')['项目进度']=='75%'
    assert preview('2026-11-05')['项目进度']=='0%'


def test_natural_chinese_dates_still_validate_numbers():
    from fastapi import HTTPException
    snap={'sources':{'PROJECT':{'name':'项目'}},'start':'2026-07-02','end':'2026-07-09'}
    content={'sections':[{'heading':h,'paragraphs':[]} for h in reporting.HEADINGS]}
    content['sections'][0]['paragraphs']=[{'text':'报告期间为2026年7月2日至7月9日。','source_ids':['PROJECT']}]
    reporting.validate_content(content,snap)
    content['sections'][0]['paragraphs'][0]['text']='完成999项。'
    content['sections'][1]['paragraphs']=[{'text':'开展888次测试。','source_ids':['PROJECT']}]
    with pytest.raises(HTTPException) as caught:reporting.validate_content(content,snap)
    assert '999' in caught.value.model_feedback and '888' in caught.value.model_feedback


def test_export_legacy_report_uses_clean_template_and_fresh_cache(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from docx import Document
    from backend import exports
    monkeypatch.setattr(exports,'DATA',tmp_path)
    version=SimpleNamespace(id='legacy-version',number=1,snapshot={'project_name':'正式简报验证','metrics':{'本期日志数':133},'warnings':['内部完整性提示']},
        content={'sections':[{'heading':h,'paragraphs':[{'text':'本期完成系统部署与用户培训。','source_ids':['T-SECRET']}]} for h in reporting.HEADINGS]})
    brief=SimpleNamespace(start='2026-07-02',end='2026-11-25')
    old=tmp_path/'exports'/'legacy-version'
    old.mkdir(parents=True)
    (old/'正式简报验证_2026-07-02_2026-11-25_V1.docx').write_bytes(b'stale cached export')
    output=exports.export_brief(brief,version,'docx')
    document=Document(output)
    text='\n'.join(p.text for p in document.paragraphs)
    assert '2026年7月2日至2026年11月25日' in text
    assert '一、项目概况' in text and '七、后续计划' in text
    assert all(term not in text for term in ('T-SECRET','来源','资料完整性','内部完整性提示','正文版本','生成日期','本期日志数','未记录'))
    assert not document.tables
    assert output.parent!=old


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_model_repairs_unsupported_numbers_without_disabling_validation(repair_succeeds):
    from types import SimpleNamespace
    from fastapi import HTTPException
    snap={'start':'2026-11-01','end':'2026-11-07','sources':{'METRICS':{'本期完成任务数':3}}}
    calls=[]
    class Responses:
        def parse(self,**kwargs):
            calls.append(copy.deepcopy(kwargs['input']))
            value='3' if len(calls)==2 and repair_succeeds else '999'
            parsed=ReportContent(sections=[{'heading':h,'paragraphs':[{'text':'本期完成'+value+'项任务。','source_ids':['METRICS']}]} for h in reporting.HEADINGS])
            return SimpleNamespace(status='completed',output_parsed=parsed)
    client=SimpleNamespace(responses=Responses())
    if repair_succeeds:
        result=reporting.compose(client,'test',snap,{'sources':snap['sources']},final=True)
        assert result['sections'][0]['paragraphs'][0]['text']=='本期完成3项任务。'
    else:
        with pytest.raises(HTTPException):reporting.compose(client,'test',snap,{'sources':snap['sources']},final=True)
    assert len(calls)==2
    assert '999' in calls[1][-1]['content'] and '不存在的数字' in calls[1][-1]['content']


def test_confirmed_erroneous_status_revision_is_voided_without_changing_audit():
    from types import SimpleNamespace
    revisions=[
        SimpleNamespace(id=1,effective_date='2026-08-06',patch={'status':'待处理'},reason='登记'),
        SimpleNamespace(id=2,effective_date='2026-11-25',patch={'status':'处理中'},reason='误填生效日'),
        SimpleNamespace(id=3,effective_date='2026-08-15',patch={'status':'已关闭','closed_date':'2026-08-15'},reason='补录关闭'),
        SimpleNamespace(id=4,effective_date='2026-11-25',patch={'_void_revisions':[2]},reason='用户确认八月关闭且未重新打开'),
    ]
    before=copy.deepcopy([r.patch for r in revisions])
    assert reporting.replay(revisions,'2026-08-14')['status']=='待处理'
    assert reporting.replay(revisions,'2026-08-15')['status']=='已关闭'
    assert reporting.replay(revisions,'2026-11-25')['status']=='已关闭'
    assert [r.patch for r in revisions]==before
    assert sum(e['patch'].get('status')=='已关闭' for e in reporting.effective_events(revisions))==1
    revisions.append(SimpleNamespace(id=5,effective_date='2026-11-25',patch={'status':'处理中','closed_date':None},reason='后续确实重新打开'))
    assert reporting.replay(revisions,'2026-11-25')['status']=='处理中'
