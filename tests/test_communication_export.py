import io
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from docx import Document
from backend import exports
from .conftest import create_record
from .test_communications import data, get, remove
from .test_business import update


def url(project, record, extension='docx'):
    return f'/api/projects/{project["id"]}/communications/{record["id"]}/export/{extension}'


def text(response):
    assert response.status_code == 200, response.text
    return '\n'.join(p.text for p in Document(io.BytesIO(response.content)).paragraphs)


def test_export_saved_content_fields_and_download_name(client, setup_project):
    project, host, _ = setup_project('沟通导出中文项目')
    second = client.post(f'/api/projects/{project["id"]}/people', json={'name':'张老师','team':'医务部'}).json()
    payload = data(host, subject='现场 / 需求 <核对> & 确认', summary='概况第一行\n概况第二行',
                   details='首行\n  保留前导空格\n\n含 <XML> & 内容\t制表符\n最后一行', participant_ids=[host['id'],second['id']])
    record = create_record(client, project, 'communications', payload).json()
    before = get(client, project, 'communications', record['id']).json()
    history = client.get(f'/api/projects/{project["id"]}/history/communications/{record["id"]}').json()
    response = client.get(url(project, record), params={'version':record['version']})
    content = text(response)
    from docx.oxml.ns import qn
    document = Document(io.BytesIO(response.content))
    assert not list(document.styles.element.iter(qn('w:pBdr')))
    for expected in [project['name'],payload['subject'],payload['occurred_at'],payload['location'],'项目公共事务',
                     '主持人：'+host['name'],'记录人：'+host['name'],'张老师（医务部）',payload['summary'],payload['details']]:
        assert expected in content
    assert 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in response.headers['content-type']
    name = unquote(response.headers['content-disposition'].split("filename*=utf-8''")[1])
    assert name.endswith('.docx') and '/' not in name and '<' not in name
    assert client.get(url(project, record)).content == response.content
    assert get(client, project, 'communications', record['id']).json() == before
    assert client.get(f'/api/projects/{project["id"]}/history/communications/{record["id"]}').json() == history


def test_updated_content_profiles_and_stale_version(client, setup_project):
    project, host, _ = setup_project('沟通导出更新')
    record = create_record(client, project, 'communications', data(host)).json()
    original = text(client.get(url(project, record)))
    revised = update(client, project, 'communications', record, details='修改后的最新详情').json()
    assert client.get(url(project, record), params={'version':record['version']}).status_code == 409
    assert '修改后的最新详情' in text(client.get(url(project, revised)))
    response = client.put(f'/api/projects/{project["id"]}/people/{host["id"]}',json={'version':host['version'],'name':'已改名主持人','team':'新团队','enabled':False})
    assert response.status_code == 200,response.text
    latest = text(client.get(url(project, revised)))
    assert '已改名主持人（新团队）' in latest and latest != original


def test_archived_empty_participants_details_and_project_isolation(client, setup_project):
    project, host, _ = setup_project('归档沟通导出')
    other, _, _ = setup_project('其他项目')
    record = create_record(client, project, 'communications', data(host,participant_ids=[],location='',details='')).json()
    assert client.get(url(other,record)).status_code == 422
    assert client.get(url(project,record,'txt')).status_code == 422
    response = client.post(f'/api/projects/{project["id"]}/archive',json={'version':project['version'],'archived':True})
    assert response.status_code == 200,response.text
    content = text(client.get(url(project,record)))
    assert '参与人员：未登记' in content and '地点：未填写' in content
    assert '沟通详情' not in content


def test_removed_communication_cannot_export(client,setup_project):
    project,host,_=setup_project('已移除沟通导出')
    record=create_record(client,project,'communications',data(host)).json()
    assert remove(client,project,'communications',record).status_code==200
    assert client.get(url(project,record)).status_code==404


def test_pdf_component_missing_and_conversion_failure_keep_word(client,setup_project,monkeypatch):
    project,host,_=setup_project('沟通PDF异常')
    record=create_record(client,project,'communications',data(host)).json()
    monkeypatch.setattr(exports,'soffice_path',lambda:'')
    response=client.get(url(project,record,'pdf'))
    assert response.status_code==503 and 'Word 仍可导出' in response.json()['detail']
    assert client.get(url(project,record)).status_code==200
    monkeypatch.setattr(exports,'soffice_path',lambda:__file__)
    monkeypatch.setattr(exports.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    response=client.get(url(project,record,'pdf'))
    assert response.status_code==503 and 'PDF 转换失败' in response.json()['detail']
    assert client.get(url(project,record)).status_code==200


def test_slow_export_does_not_block_workbench_or_modify_captured_content(client,setup_project,monkeypatch,tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from backend import communication_export
    project,host,_=setup_project('导出时工作台仍可使用')
    record=create_record(client,project,'communications',data(host)).json()
    started,finish=threading.Event(),threading.Event()
    captured=[]
    def slow(snapshot,extension):
        captured.append(snapshot)
        started.set()
        assert finish.wait(10)
        target=tmp_path/'export.pdf';target.write_bytes(b'%PDF-1.4')
        return target
    monkeypatch.setattr(communication_export,'export_communication',slow)
    with ThreadPoolExecutor() as pool:
        request=pool.submit(client.get,url(project,record,'pdf'))
        assert started.wait(5)
        try:
            health=pool.submit(client.get,'/api/health')
            assert health.result(timeout=3).status_code==200
            save=pool.submit(update,client,project,'communications',record,summary='导出期间另存的新概况')
            assert save.result(timeout=3).status_code==200
        finally:finish.set()
        assert request.result().status_code==200
    assert captured[0]['summary']==record['summary']
