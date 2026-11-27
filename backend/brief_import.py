"""Preview and commit imported reports without changing existing briefs."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, File, Header, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from . import models as m, schemas as sc, service as s
from .config import DATA, ROOT, config, now
from .db import Session, WRITE_LOCK, transaction
from .document_import import MAX_TEXT

router = APIRouter()
FORMAT = 'imported-markdown-v1'
MIMES = {'.pdf': 'application/pdf', '.doc': 'application/msword',
         '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class ImportBriefInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(pattern=r'^[a-f0-9]{32}$')
    title: str = Field(min_length=1, max_length=200)
    start: str
    end: str
    markdown: sc.RequiredMarkdown = Field(max_length=MAX_TEXT)

    @model_validator(mode='after')
    def validate_input(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError('请填写报告名称')
        sc.ReportInput(start=self.start, end=self.end)
        return self


def stage_folder(token):
    if not re.fullmatch(r'[a-f0-9]{32}', token):
        s.fail('导入预览不存在或已失效，请重新选择文件', 404)
    return DATA / 'staging' / ('brief-import-' + token)


def read_stage(pid, token):
    folder = stage_folder(token)
    if not (folder / 'manifest.json').is_file() or not (folder / 'converted.json').is_file():
        s.fail('导入预览不存在或已失效，请重新选择文件', 404)
    manifest = json.loads((folder / 'manifest.json').read_text('utf-8'))
    if manifest['project_id'] != pid:
        s.fail('导入报告不属于当前项目', 404)
    return folder, manifest, json.loads((folder / 'converted.json').read_text('utf-8'))


def clean_stage(folder):
    folder = folder.resolve()
    if folder.parent != (DATA / 'staging').resolve() or not re.fullmatch(r'brief-import-[a-f0-9]{32}', folder.name):
        raise ValueError('Invalid import staging path')
    shutil.rmtree(folder, ignore_errors=True)


@router.post('/api/projects/{pid}/brief-imports/preview')
def preview_report(pid: str, file: UploadFile = File(...)):
    with WRITE_LOCK, Session() as session:
        s.project(session, pid, True)
    filename = Path((file.filename or '').replace('\\', '/')).name
    extension = Path(filename).suffix.lower()
    if extension not in MIMES:
        s.fail('请选择 PDF 或 Word（.docx、.doc）报告', 415)
    token = m.uid()
    folder = stage_folder(token)
    folder.mkdir(parents=True)
    try:
        size, digest = 0, hashlib.sha256()
        with (folder / ('source' + extension)).open('xb') as target:
            for chunk in iter(lambda: file.file.read(1024 * 1024), b''):
                size += len(chunk)
                if size > min(50, int(config()['max_file_mb'])) * 1024 * 1024:
                    s.fail('报告超过单文件大小上限（最多 50 MB）', 413)
                digest.update(chunk)
                target.write(chunk)
        if not size:
            s.fail('报告文件为空', 422)
        manifest = {'project_id': pid, 'name': filename, 'extension': extension, 'size': size,
                    'sha256': digest.hexdigest(), 'created_at': now()}
        (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        try:
            completed = subprocess.run([sys.executable, '-m', 'backend.document_import', str(folder)], cwd=ROOT,
                                       capture_output=True, timeout=150,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            s.fail('报告转换超时，请拆分文档后重新导入', 422)
        if completed.returncode or not (folder / 'converted.json').is_file():
            error_file = folder / 'error.json'
            message = json.loads(error_file.read_text('utf-8'))['detail'] if error_file.is_file() else '报告转换失败，请检查文件后重试'
            s.fail(message, 422)
        result = json.loads((folder / 'converted.json').read_text('utf-8'))
        markdown = result['markdown']
        for asset in result['assets']:
            markdown = markdown.replace('import-asset:' + asset['id'], f'/api/projects/{pid}/brief-imports/{token}/assets/{asset["id"]}')
        return {'token': token, 'title': Path(filename).stem[:200], 'name': filename,
                'markdown': markdown, 'warnings': result['warnings'], 'images': len(result['assets'])}
    except Exception:
        clean_stage(folder)
        raise
    finally:
        file.file.close()


@router.get('/api/projects/{pid}/brief-imports/{token}/assets/{ident}')
def preview_image(pid: str, token: str, ident: str):
    with Session() as session:
        s.project(session, pid)
    folder, _, result = read_stage(pid, token)
    asset = next((asset for asset in result['assets'] if asset['id'] == ident), None)
    if asset is None:
        s.fail('图片不存在', 404)
    return FileResponse(folder / asset['file'], media_type='image/png')


@router.delete('/api/projects/{pid}/brief-imports/{token}')
def cancel_import(pid: str, token: str):
    folder = stage_folder(token)
    if (folder / 'manifest.json').is_file():
        info = json.loads((folder / 'manifest.json').read_text('utf-8'))
        if info['project_id'] != pid:
            s.fail('导入报告不属于当前项目', 404)
        clean_stage(folder)
    return {'ok': True}


def imported_content(markdown):
    return {'sections': [{'heading': '', 'paragraphs': [{'text': markdown, 'source_ids': []}]}]}


def validate_import_content(content):
    sections = content.get('sections', [])
    if len(sections) != 1 or sections[0]['heading'] != '' or len(sections[0]['paragraphs']) != 1:
        s.fail('导入报告须保留完整 Markdown 正文', 422)
    paragraph = sections[0]['paragraphs'][0]
    if paragraph['source_ids'] or not paragraph['text'].strip() or len(paragraph['text']) > MAX_TEXT:
        s.fail('报告正文为空、过长或引用格式不正确', 422)


@router.post('/api/projects/{pid}/brief-imports')
def commit_report(pid: str, body: ImportBriefInput, idempotency_key: str | None = Header(None)):
    if not idempotency_key or len(idempotency_key) > 200:
        s.fail('导入请求缺少有效标识，请关闭窗口后重试', 422)
    fingerprint = hashlib.sha256(json.dumps([pid, body.model_dump()], sort_keys=True).encode()).hexdigest()
    created_files = []
    with WRITE_LOCK:
        try:
            with transaction() as session:
                project = s.project(session, pid, True)
                previous = session.get(m.Idempotency, idempotency_key)
                if previous:
                    if previous.kind != 'brief_import' or previous.fingerprint != fingerprint:
                        s.fail('同一导入标识对应的内容发生变化，请重新导入', 409)
                    version = s.get(session, m.BriefVersion, previous.entity_id)
                    return {'brief': s.plain(s.get(session, m.Brief, version.brief_id)), 'version': s.plain(version)}
                folder, manifest, parsed = read_stage(pid, body.token)
                brief = m.Brief(project_id=pid, start=body.start, end=body.end, title=body.title)
                session.add(brief)
                session.flush()

                def attach(source, name, mime, description):
                    ident = m.uid()
                    relative = 'files/' + ident + source.suffix.lower()
                    target = DATA / relative
                    shutil.copyfile(source, target)
                    created_files.append(target)
                    data = target.read_bytes()
                    attachment = m.Attachment(id=ident, project_id=pid, name=name, path=relative, size=len(data), mime=mime,
                                              sha256=hashlib.sha256(data).hexdigest(), description=description)
                    session.add(attachment)
                    session.flush()
                    session.add(m.AttachmentLink(attachment_id=ident, kind='briefs', entity_id=brief.id, project_id=pid))
                    return attachment

                original = attach(folder / ('source' + manifest['extension']), manifest['name'], MIMES[manifest['extension']], '项目简报导入原文件')
                markdown = body.markdown
                assets = []
                for asset in parsed['assets']:
                    attachment = attach(folder / asset['file'], asset['name'], 'image/png', '项目简报导入图片')
                    old_url = f'/api/projects/{pid}/brief-imports/{body.token}/assets/{asset["id"]}'
                    markdown = markdown.replace(old_url, '/api/attachments/' + attachment.id + '/download')
                    assets.append(attachment.id)
                if re.search(r'/brief-imports/[a-f0-9]+/assets/|import-asset:', markdown):
                    s.fail('正文含有不属于此报告的临时图片，请重新预览后导入', 422)
                snapshot = {'format': FORMAT, 'project_id': pid, 'project_name': project.name, 'start': body.start, 'end': body.end, 'sources': {},
                            'import': {'name': manifest['name'], 'sha256': manifest['sha256'], 'original_id': original.id,
                                       'asset_ids': assets, 'warnings': parsed['warnings']}}
                version = m.BriefVersion(brief_id=brief.id, number=1, snapshot=snapshot, content=imported_content(markdown),
                                         model='', prompt_version='import-v1', source='报告导入')
                session.add(version)
                session.flush()
                session.add(m.Idempotency(key=idempotency_key, kind='brief_import', fingerprint=fingerprint, entity_id=version.id))
                result = {'brief': s.plain(brief), 'version': s.plain(version)}
        except Exception:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
    clean_stage(folder)
    return result


def image_resolver(snapshot):
    """Allow only images captured in this immutable import snapshot, never arbitrary paths/URLs."""
    allowed = set(snapshot.get('import', {}).get('asset_ids', []))

    def resolve(url):
        match = re.fullmatch(r'/api/attachments/([a-f0-9]{32})/download', url)
        if not match or match[1] not in allowed:
            return None
        with Session() as session:
            attachment = session.get(m.Attachment, match[1])
            if attachment is None or attachment.mime != 'image/png' or attachment.project_id != snapshot.get('project_id'):
                return None
            path = (DATA / attachment.path).resolve()
            return path if path.is_relative_to((DATA / 'files').resolve()) and path.is_file() else None
    return resolve
