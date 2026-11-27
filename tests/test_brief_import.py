import copy
import io
import uuid
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select

from backend import models as m
from backend.brief_import import FORMAT, stage_folder
from backend.config import DATA, soffice_path
from backend.db import Session, transaction

FIXTURES = Path(__file__).parent / 'fixtures/brief_import'


@pytest.mark.parametrize('complete', [True, False])
def test_pdf_launcher_timeout_checks_finished_output(tmp_path, monkeypatch, complete):
    import subprocess
    from fastapi import HTTPException
    from backend import exports
    document = tmp_path / 'report.docx'
    Document().save(document)
    output = document.with_suffix('.pdf')
    output.write_bytes(b'%PDF-incomplete-cache')
    executable = tmp_path / 'soffice.exe'
    executable.touch()
    monkeypatch.setattr(exports, 'soffice_path', lambda: str(executable))

    def convert(*args, **kwargs):
        assert not output.exists(), 'Incomplete cached output must be rebuilt'
        output.write_bytes((FIXTURES / 'sample.pdf').read_bytes() if complete else b'%PDF-partial')
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

    monkeypatch.setattr(exports.subprocess, 'run', convert)
    if complete:
        assert exports.document_pdf(document) == output
        assert exports.document_pdf(document) == output
    else:
        with pytest.raises(HTTPException) as caught:
            exports.document_pdf(document)
        assert caught.value.status_code == 503 and not output.exists()


def test_doc_launcher_timeout_accepts_only_readable_document(tmp_path, monkeypatch):
    import json
    import subprocess
    from backend import document_import
    executable = tmp_path / 'soffice.exe'
    executable.touch()
    monkeypatch.setattr(document_import, 'soffice_path', lambda: str(executable))
    (tmp_path / 'source.doc').write_bytes((FIXTURES / 'sample.doc').read_bytes())
    (tmp_path / 'manifest.json').write_text(json.dumps({'extension': '.doc'}))

    def convert(*args, **kwargs):
        (tmp_path / 'source.docx').write_bytes((FIXTURES / 'sample.docx').read_bytes())
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

    monkeypatch.setattr(document_import.subprocess, 'run', convert)
    assert '接口联调' in document_import.convert(tmp_path)['markdown']


def preview(client, pid, filename='sample.docx', content=None):
    return client.post(f'/api/projects/{pid}/brief-imports/preview',
                       files={'file': (filename, content if content is not None else (FIXTURES / filename).read_bytes())})


def body(result):
    return {'token': result['token'], 'title': '导入报告验收', 'start': '2026-11-01', 'end': '2026-11-27', 'markdown': result['markdown']}


def commit(client, pid, data, key=None):
    return client.post(f'/api/projects/{pid}/brief-imports', json=data, headers={'Idempotency-Key': key or uuid.uuid4().hex})


def test_word_import_preview_commit_edit_and_exports(client, setup_project):
    project, _, _ = setup_project('报告导入项目')
    pid = project['id']
    response = preview(client, pid)
    assert response.status_code == 200, response.text
    converted = response.json()
    text = converted['markdown']
    assert '# 实施交付报告导入验收' in text
    assert '# 一、交付进展' in text and '## 2.1 后续安排' in text
    assert '**接口联调**' in text and '- 确认需求范围' in text
    assert '| 接口测试 | 通过 |' in text and converted['images'] == 1
    assert client.get(f'/api/projects/{pid}/briefs').json()['total'] == 0
    data, key = body(converted), uuid.uuid4().hex
    created = commit(client, pid, data, key)
    assert created.status_code == 200, created.text
    result = created.json()
    brief, version = result['brief'], result['version']
    assert version['snapshot']['format'] == FORMAT and version['source'] == '报告导入'
    assert not stage_folder(converted['token']).exists()
    assert commit(client, pid, data, key).json() == result
    assert commit(client, pid, {**data, 'title': '不同报告'}, key).status_code == 409
    assert client.get(f'/api/projects/{pid}/briefs').json()['total'] == 1
    original = client.get('/api/attachments/' + version['snapshot']['import']['original_id'] + '/download')
    assert original.content == (FIXTURES / 'sample.docx').read_bytes()
    asset_ids = version['snapshot']['import']['asset_ids']
    assert asset_ids
    for asset_id in asset_ids:
        assert client.get('/api/attachments/' + asset_id + '/download').content.startswith(b'\x89PNG')
    visible_ids = {item['id'] for item in client.get(f'/api/projects/{pid}/attachments').json()}
    assert not visible_ids.intersection(asset_ids)
    assert version['snapshot']['import']['original_id'] in visible_ids
    # A manually uploaded image with the same name remains a normal attachment.
    manual = client.post('/api/attachments/upload', params={'project_id': pid}, files={'file': ('第1页图片1.png', (FIXTURES / 'diagram.png').read_bytes(), 'image/png')})
    assert manual.status_code == 200, manual.text
    assert manual.json()['id'] in {item['id'] for item in client.get(f'/api/projects/{pid}/attachments').json()}
    word = client.get('/api/brief-versions/' + version['id'] + '/export/docx')
    assert word.status_code == 200, word.text[:100]
    document = Document(io.BytesIO(word.content))
    assert len(document.tables) == 1 and len(document.inline_shapes) == 1
    assert '接口测试' in document.tables[0].cell(1, 0).text
    assert '一、一、交付进展' not in '\n'.join(p.text for p in document.paragraphs)
    changed = copy.deepcopy(version['content'])
    changed['sections'][0]['paragraphs'][0]['text'] += '\n\n人工补充内容。'
    saved = client.post('/api/briefs/' + brief['id'] + '/versions', json={
        'version': brief['version'], 'base_version_id': version['id'], 'content': changed})
    assert saved.status_code == 200, saved.text
    assert saved.json()['number'] == 2
    assert client.get('/api/brief-versions/' + version['id']).json()['content'] == version['content']
    assert client.post('/api/projects/' + pid + '/generate', json={'start': data['start'], 'end': data['end'], 'brief_id': brief['id']}).status_code == 422
    if soffice_path():
        pdf = client.get('/api/brief-versions/' + saved.json()['id'] + '/export/pdf')
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-'), pdf.text[:100]


@pytest.mark.parametrize('filename', ['sample.pdf', 'scan.pdf', 'sample.doc'])
def test_other_formats(client, setup_project, filename):
    if filename.endswith('.doc') and not soffice_path():
        pytest.skip('LibreOffice is not installed')
    project, _, _ = setup_project(filename)
    response = preview(client, project['id'], filename)
    assert response.status_code == 200, response.text
    converted = response.json()
    if filename == 'scan.pdf':
        assert converted['images'] == 1
        assert any('不可直接编辑' in warning for warning in converted['warnings'])
    else:
        assert '交付进展' in converted['markdown'] and '接口测试' in converted['markdown']
        assert '| --- | --- |' in converted['markdown']
    response = commit(client, project['id'], body(converted))
    assert response.status_code == 200, response.text
    word = client.get('/api/brief-versions/' + response.json()['version']['id'] + '/export/docx')
    assert word.status_code == 200
    assert len(Document(io.BytesIO(word.content)).inline_shapes) >= 1


def test_isolation_archive_cancel_and_bad_files(client, setup_project):
    project, _, _ = setup_project('导入隔离')
    other, _, _ = setup_project('其他项目')
    pid = project['id']
    assert preview(client, pid, 'bad.txt', b'no').status_code == 415
    assert preview(client, pid, 'bad.pdf', b'not a PDF').status_code == 422
    assert preview(client, pid, 'bad.docx', b'not Word').status_code == 422
    converted = preview(client, pid).json()
    data = body(converted)
    assert commit(client, other['id'], data).status_code == 404
    assert commit(client, pid, {**data, 'end': '9999-01-01'}).status_code == 422
    assert commit(client, pid, {**data, 'markdown': '   '}).status_code == 422
    image_url = converted['markdown'].split('](')[-1].split(')')[0]
    assert client.get(image_url).status_code == 200
    assert client.get(image_url.replace(pid, other['id'])).status_code == 404
    assert client.delete(f'/api/projects/{other["id"]}/brief-imports/{converted["token"]}').status_code == 404
    with transaction() as session:
        session.get(m.Project, pid).archived = True
    assert preview(client, pid).status_code == 409
    assert commit(client, pid, data).status_code == 409
    assert client.delete(f'/api/projects/{pid}/brief-imports/{converted["token"]}').status_code == 200
    assert not stage_folder(converted['token']).exists()
    with Session() as session:
        assert not list(session.scalars(select(m.Brief).where(m.Brief.project_id == pid)))
        assert not list(session.scalars(select(m.Attachment).where(m.Attachment.project_id == pid)))


def test_tampered_asset_rolls_back_without_files(client, setup_project):
    project, _, _ = setup_project('导入回滚')
    pid = project['id']
    converted = preview(client, pid).json()
    before = set((DATA / 'files').iterdir())
    data = body(converted)
    data['markdown'] += '\n![](/api/projects/other/brief-imports/' + 'a' * 32 + '/assets/' + 'b' * 32 + ')'
    assert commit(client, pid, data).status_code == 422
    assert set((DATA / 'files').iterdir()) == before
    assert client.get(f'/api/projects/{pid}/briefs').json()['total'] == 0
