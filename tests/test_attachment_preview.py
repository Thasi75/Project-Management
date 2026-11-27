import base64
import io
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from docx import Document

from backend import attachment_preview as preview
from backend.config import DATA, soffice_path


def add_file(client, pid, name, content, acceptance=True):
    response = client.post('/api/attachments/upload', params={'project_id': pid, 'is_acceptance': acceptance},
                           files={'file': (name, content, 'application/octet-stream')})
    assert response.status_code == 200, response.text
    return response.json()


def url(project, file):
    return f'/api/projects/{project["id"]}/attachments/{file["id"]}/preview'


def document_bytes():
    buffer = io.BytesIO()
    doc = Document()
    doc.add_heading('验收材料预览', 0)
    doc.add_paragraph('Word 文档的中文内容与表格。')
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = '项目'
    table.cell(1, 0).text = '验收测试'
    table.cell(1, 1).text = '通过'
    doc.save(buffer)
    return buffer.getvalue()


def test_pdf_image_csv_and_plain_text_preview_are_read_only(client, setup_project):
    project, _, _ = setup_project('预览只读')
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6gX8AAAAASUVORK5CYII=')
    for name, content, mime in [('签章.png', png, 'image/png'), ('材料.pdf', b'%PDF-1.4\n%%EOF', 'application/pdf'),
                                ('文字.txt', '<script>alert(1)</script>'.encode(), 'text/plain')]:
        file = add_file(client, project['id'], name, content)
        response = client.get(url(project, file))
        assert response.status_code == 200, response.text
        assert response.content == content and response.headers['content-type'].startswith(mime)
        assert response.headers['content-disposition'] == 'inline'
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert client.get('/api/attachments/' + file['id'] + '/download').content == content
        current = next(row for row in client.get(f'/api/projects/{project["id"]}/attachments').json() if row['id'] == file['id'])
        assert current['version'] == file['version'] and current['updated_at'] == file['updated_at']
    file = add_file(client, project['id'], '数据.csv', '名称,内容\r\n中文,"带逗号,及\n换行"\r\n'.encode('gb18030'))
    result = client.get(url(project, file)).json()
    assert result == {'rows': [['名称', '内容'], ['中文', '带逗号,及\n换行']], 'truncated': False}
    file = add_file(client, project['id'], '大表.csv', ('A,B\n' * 1002).encode())
    result = client.get(url(project, file)).json()
    assert len(result['rows']) == 1000 and result['truncated'] is True


def test_preview_scope_removed_missing_unsupported_and_archived(client, setup_project):
    project, _, _ = setup_project('预览范围')
    other, _, _ = setup_project('其他项目')
    file = add_file(client, project['id'], '材料.pdf', b'%PDF-1.4\n%%EOF')
    assert client.get(url(other, file)).status_code == 404
    hidden = add_file(client, project['id'], '普通.pdf', b'%PDF-1.4', acceptance=False)
    assert client.get(url(project, hidden)).status_code == 200
    assert client.get(url(other, hidden)).status_code == 404
    current = next(row for row in client.get('/api/projects/' + project['id'] + '/attachments').json() if row['id'] == hidden['id'])
    assert current['is_acceptance'] is False and current['version'] == hidden['version']
    staged = client.post('/api/attachments/upload?is_acceptance=true', files={'file': ('暂存.pdf', b'%PDF-1.4')}).json()
    assert client.get(url(project, staged)).status_code == 404
    removed = client.put('/api/attachments/' + file['id'], json={'version': file['version'], 'removed': True}).json()
    assert client.get(url(project, removed)).status_code == 404
    client.put('/api/attachments/' + file['id'], json={'version': removed['version'], 'removed': False})
    bad = add_file(client, project['id'], '损坏.pdf', b'not a PDF')
    assert client.get(url(project, bad)).status_code == 422
    archive = add_file(client, project['id'], '压缩.zip', b'PK')
    assert client.get(url(project, archive)).status_code == 415
    missing = add_file(client, project['id'], '缺失.pdf', b'%PDF-1.4')
    (DATA / missing['path']).unlink()
    assert client.get(url(project, missing)).status_code == 404
    (DATA / missing['path']).write_bytes(b'%PDF-1.4')
    client.post('/api/projects/' + project['id'] + '/archive', json={'version': project['version'], 'archived': True}).raise_for_status()
    assert client.get(url(project, file)).status_code == 200


def test_office_failure_busy_timeout_and_cache(client, setup_project, monkeypatch, tmp_path):
    project, _, _ = setup_project('文档转换异常')
    file = add_file(client, project['id'], '异常.docx', b'unique-bad-docx')
    monkeypatch.setattr(preview, 'soffice_path', lambda: '')
    assert client.get(url(project, file)).status_code == 503
    monkeypatch.setattr(preview, 'soffice_path', lambda: str(Path(__file__)))
    preview.CONVERSION_SLOT.acquire()
    try:
        assert client.get(url(project, file)).status_code == 503
    finally:
        preview.CONVERSION_SLOT.release()
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('test', 90)
    monkeypatch.setattr(preview.subprocess, 'run', timeout)
    assert client.get(url(project, file)).status_code == 503
    monkeypatch.setattr(preview.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert client.get(url(project, file)).status_code == 422
    calls = []
    def convert(command, **kwargs):
        calls.append(command)
        work = Path(command[-1]).parent
        (work / 'source.pdf').write_bytes(b'%PDF-1.4\nconverted')
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(preview.subprocess, 'run', convert)
    assert client.get(url(project, file)).content.startswith(b'%PDF-')
    assert client.get(url(project, file)).content.startswith(b'%PDF-')
    assert len(calls) == 1
    assert not list((DATA / 'previews' / 'v1').glob('convert-*'))
    assert client.get('/api/attachments/' + file['id'] + '/download').content == b'unique-bad-docx'


def test_conversion_does_not_block_other_requests(client, setup_project, monkeypatch):
    project, _, _ = setup_project('转换不阻塞')
    file = add_file(client, project['id'], '较慢.docx', b'slow')
    started, finish = threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        assert finish.wait(10)
        return b'%PDF-1.4'
    monkeypatch.setattr(preview, 'office_pdf', slow)
    with ThreadPoolExecutor() as pool:
        request = pool.submit(client.get, url(project, file))
        assert started.wait(5)
        try:
            health = pool.submit(client.get, '/api/health')
            assert health.result(timeout=3).status_code == 200
            save = pool.submit(client.put, '/api/attachments/' + file['id'], json={'version': file['version'], 'description': '转换期间更新'})
            assert save.result(timeout=3).status_code == 200
        finally:
            finish.set()
        assert request.result().status_code == 200


def test_finished_pdf_survives_launcher_timeout(client, setup_project, monkeypatch):
    project, _, _ = setup_project('转换已完成后超时')
    file = add_file(client, project['id'], '普通附件.docx', b'finished-timeout', acceptance=False)
    data = (Path(__file__).parent / 'fixtures/brief_import/sample.pdf').read_bytes()
    monkeypatch.setattr(preview, 'soffice_path', lambda: str(Path(__file__)))
    calls = []
    def convert(command, **kwargs):
        calls.append(command)
        assert kwargs['stdout'] == subprocess.DEVNULL and kwargs['stderr'] == subprocess.DEVNULL
        (Path(command[-1]).parent / 'source.pdf').write_bytes(data)
        raise subprocess.TimeoutExpired(command, 90)
    monkeypatch.setattr(preview.subprocess, 'run', convert)
    assert client.get(url(project, file)).content == data
    assert client.get(url(project, file)).content == data
    assert len(calls) == 1


@pytest.mark.skipif(not soffice_path(), reason='LibreOffice is not installed')
def test_real_word_conversion(client, setup_project):
    project, _, _ = setup_project('真实 Word 预览')
    content = document_bytes()
    file = add_file(client, project['id'], '中文.docx', content)
    response = client.get(url(project, file))
    assert response.status_code == 200, response.text[:300]
    assert response.content.startswith(b'%PDF-') and len(response.content) > 1000
    assert client.get(url(project, file)).content == response.content
    assert client.get('/api/attachments/' + file['id'] + '/download').content == content
