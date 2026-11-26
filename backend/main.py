import hashlib
import asyncio
import json
import shutil
import re
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, quote
from fastapi import FastAPI, Request, UploadFile, File, Header, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError, BaseModel, ConfigDict, Field
from .config import ROOT, DATA, LOCAL, config, today, now, soffice_path
from .db import Session, transaction, WRITE_LOCK
from . import models as m, schemas as sc, service as s, maintenance as maintenance
from . import reporting
from .credentials import read_key, save_key
from .exports import export_brief
from .attachment_preview import preview_attachment
from .log_export import export_logs, MIME as XLSX_MIME

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='brief')


@asynccontextmanager
async def lifespan(app):
    maintenance.migrate()
    maintenance.clean_staging()
    with transaction() as session:
        for job in session.scalars(select(m.Job).where(m.Job.status.in_(['等待中', '生成中']))):
            job.status, job.error = '失败', '应用重启中断了生成，可以重试'
    yield
    executor.shutdown(wait=True)


app = FastAPI(title='项目实施交付工作台', version='1.0.0', lifespan=lifespan)
request_gate = asyncio.Lock()


@app.middleware('http')
async def coordinate_restore(request, call_next):
    # Single-user local requests finish their database work before a restore can replace files.
    # AI calls run outside this gate and only use short WRITE_LOCK transactions.
    # Preview captures its source under WRITE_LOCK before converting outside it.
    # A slow Office conversion must not block saves or health checks.
    if request.method == 'GET' and (re.fullmatch(r'/api/projects/[^/]+/attachments/[^/]+/preview', request.url.path)
                                     or re.fullmatch(r'/api/projects/[^/]+/communications/[^/]+/export/(docx|pdf)', request.url.path)):
        return await call_next(request)
    async with request_gate:
        return await call_next(request)


@app.middleware('http')
async def local_access(request, call_next):
    host = request.url.hostname
    if host not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    if request.url.path.startswith('/api'):
        origin = request.headers.get('origin')
        allowed_origin = origin == str(request.base_url).rstrip('/') or origin in ('http://127.0.0.1:5173', 'http://localhost:5173')
        if origin and not allowed_origin:
            return JSONResponse({'detail': '不允许跨来源访问'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-pm-client') != 'workbench':
            return JSONResponse({'detail': '请求缺少本机工作台标识'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    if request.method in ('POST', 'PUT', 'DELETE') and response.status_code < 300 and request.url.path.startswith('/api') and not any(p in request.url.path for p in ('/backups', '/settings', '/report-preview')):
        try:
            await __import__('starlette.concurrency', fromlist=['run_in_threadpool']).run_in_threadpool(maintenance.auto_backup)
        except Exception:
            response.headers['X-Backup-Warning'] = 'failed'
    return response


@app.exception_handler(RequestValidationError)
async def request_error(request, exc):
    errors = ['.'.join(str(x) for x in e['loc'][1:]) + '：' + e['msg'].replace('Value error, ', '') for e in exc.errors()]
    return JSONResponse({'detail': '；'.join(errors)}, status_code=422)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': '关联数据不一致或重复，请刷新后重试'}, status_code=409)


def validate(schema, body):
    try:
        return schema.model_validate(body).model_dump()
    except ValidationError as error:
        s.fail('；'.join('.'.join(str(x) for x in e['loc']) + '：' + e['msg'].replace('Value error, ', '') for e in error.errors()))


@app.get('/api/health')
def health():
    return {'ok': True, 'app_id': 'delivery-workbench', 'today': today(), 'version': '1.0.0', 'timezone': 'Asia/Shanghai'}


@app.get('/api/projects')
def projects(include_archived: bool = False):
    with Session() as session:
        query = select(m.Project).order_by(m.Project.updated_at.desc())
        if not include_archived:
            query = query.where(m.Project.archived == False)
        return [s.serialize(session, p) for p in session.scalars(query)]


@app.post('/api/projects')
def create_project(body: sc.ProjectInput):
    with transaction() as session:
        return s.save_project(session, body.model_dump())


@app.put('/api/projects/{pid}')
def update_project(pid: str, body: sc.ProjectInput):
    with transaction() as session:
        return s.save_project(session, body.model_dump(), pid)


@app.post('/api/projects/{pid}/archive')
def archive_project(pid: str, body: sc.ArchiveInput):
    with transaction() as session:
        proj = s.project(session, pid)
        s.check_version(proj, body.version)
        proj.archived = body.archived
        proj.version += 1
        return s.serialize(session, proj)


@app.get('/api/projects/{pid}/scopes')
def scopes(pid: str):
    with Session() as session:
        s.project(session, pid)
        return [s.serialize(session, x) for x in session.scalars(select(m.Scope).where(m.Scope.project_id == pid).order_by(m.Scope.number.desc()))]


@app.get('/api/projects/{pid}/people')
def people(pid: str):
    with Session() as session:
        s.project(session, pid)
        return [s.person_profile(x) for x in session.scalars(select(m.Member).where(m.Member.project_id == pid).order_by(m.Member.enabled.desc(), m.Member.name, m.Member.person_id))]


@app.post('/api/projects/{pid}/people')
def create_person(pid: str, body: sc.PersonInput):
    with transaction() as session:
        s.project(session, pid, True)
        fields = body.model_dump(exclude={'version'})
        identity = m.Person(**fields)
        session.add(identity)
        session.flush()
        profile = m.Member(project_id=pid, person_id=identity.id, **fields)
        session.add(profile)
        session.flush()
        return s.person_profile(profile)


@app.put('/api/projects/{pid}/people/{ident}')
def update_person(pid: str, ident: str, body: sc.PersonInput):
    with transaction() as session:
        s.project(session, pid, True)
        person = s.get(session, m.Member, (pid, ident))
        s.check_version(person, body.version)
        for k, v in body.model_dump(exclude={'version'}).items():
            setattr(person, k, v)
        person.version += 1
        person.updated_at = now()
        return s.person_profile(person)


@app.get('/api/people')
@app.post('/api/people')
@app.put('/api/people/{ident}')
def retired_global_people(ident: str | None = None):
    s.fail('人员资料已按项目独立维护，请刷新页面后在项目概况中操作', 410)


@app.get('/api/projects/{pid}/modules')
def modules(pid: str):
    with Session() as session:
        s.project(session, pid)
        return [s.plain(x) for x in session.scalars(select(m.Module).where(m.Module.project_id == pid).order_by(m.Module.sort, m.Module.name))]


@app.post('/api/projects/{pid}/modules')
def create_module(pid: str, body: sc.ModuleInput):
    with transaction() as session:
        s.project(session, pid, True)
        module = m.Module(project_id=pid, **body.model_dump(exclude={'version'}))
        session.add(module)
        session.flush()
        return s.plain(module)


@app.put('/api/projects/{pid}/modules/{ident}')
def update_module(pid: str, ident: str, body: sc.ModuleInput):
    with transaction() as session:
        s.project(session, pid, True)
        module = s.local_ref(session, m.Module, ident, pid, True)
        s.check_version(module, body.version)
        for k, v in body.model_dump(exclude={'version'}).items():
            setattr(module, k, v)
        module.version += 1
        module.updated_at = now()
        return s.plain(module)


@app.get('/api/metrics')
def metrics(project_id: str | None = None):
    with Session() as session:
        if project_id:
            s.project(session, project_id)
        return s.metrics(session, project_id)


@app.get('/api/records/{kind}')
def list_records(kind: str, project_id: str | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 q: str = '', status: str = '', owner_id: str = '', module_id: str = '', task_id: str = '', phase: str = '', start: str = '', end: str = '', host_id: str = '', expense_item: str = '', importance: str = '', responded: str = '', source_id: str = '', recorder_id: str = ''):
    if kind not in s.KINDS:
        s.fail('功能不存在', 404)
    with Session() as session:
        return s.list_business(session, project_id, kind, page, size, q=q, status=status, owner_id=owner_id, module_id=module_id, task_id=task_id, phase=phase, start=start, end=end, host_id=host_id, expense_item=expense_item, importance=importance, responded=responded, source_id=source_id, recorder_id=recorder_id)


@app.get('/api/projects/{pid}/logs/export')
def export_work_logs(pid: str, q: str = '', owner_id: str = '', module_id: str = '', task_id: str = '', start: str = '', end: str = ''):
    with Session() as session:
        content, filename, count = export_logs(session, pid, q=q, owner_id=owner_id, module_id=module_id, task_id=task_id, start=start, end=end)
    return Response(content, media_type=XLSX_MIME, headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename), 'X-Export-Count': str(count)})


@app.get('/api/projects/{pid}/communications/{ident}/export/{extension}')
def export_project_communication(pid: str, ident: str, extension: str, version: int | None = Query(None, ge=1)):
    from .communication_export import communication_snapshot, export_communication
    if extension not in ('docx', 'pdf'):
        s.fail('不支持的导出格式', 422)
    with WRITE_LOCK, Session() as session:
        snapshot = communication_snapshot(session, pid, ident, version)
    path = export_communication(snapshot, extension)
    mime = 'application/pdf' if extension == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return FileResponse(path, filename=path.name, media_type=mime)


@app.get('/api/projects/{pid}/research/next-sequence')
def next_research_sequence(pid: str):
    with Session() as session:
        return {'sequence': s.next_research_sequence(session, pid)}


@app.get('/api/projects/{pid}/research/export')
def export_requirements_research(pid: str, q: str = '', module_id: str = '', status: str = '', start: str = '', end: str = '',
                                 importance: str = '', responded: str = '', source_id: str = '', recorder_id: str = ''):
    from .research_export import export_research
    with Session() as session:
        content, filename, count = export_research(session, pid, q=q, module_id=module_id, status=status, start=start, end=end,
            importance=importance, responded=responded, source_id=source_id, recorder_id=recorder_id)
    return Response(content, media_type=XLSX_MIME, headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename), 'X-Export-Count': str(count)})


SCHEMAS = {'tasks': sc.TaskInput, 'logs': sc.LogInput, 'changes': sc.ChangeInput, 'risks': sc.RiskInput, 'communications': sc.CommunicationInput, 'configurations': sc.ConfigurationInput, 'costs': sc.CostInput, 'research': sc.ResearchInput}


@app.get('/api/projects/{pid}/records/{kind}/{ident}')
def get_record(pid: str, kind: str, ident: str):
    if kind not in SCHEMAS:
        s.fail('功能不存在', 404)
    with Session() as session:
        s.project(session, pid)
        return s.serialize(session, s.local_ref(session, s.KINDS[kind], ident, pid, True))


@app.post('/api/projects/{pid}/records/{kind}')
def create_record(pid: str, kind: str, body: dict, idempotency_key: str = Header(..., min_length=8, max_length=128)):
    if kind not in SCHEMAS:
        s.fail('功能不存在', 404)
    data = validate(SCHEMAS[kind], body)
    with transaction() as session:
        return s.save_business(session, pid, kind, data, key=idempotency_key)


@app.put('/api/projects/{pid}/records/{kind}/{ident}')
def update_record(pid: str, kind: str, ident: str, body: dict):
    if kind not in SCHEMAS:
        s.fail('功能不存在', 404)
    data = validate(SCHEMAS[kind], body)
    with transaction() as session:
        return s.save_business(session, pid, kind, data, ident)


@app.post('/api/projects/{pid}/records/{kind}/{ident}/transition')
def transition_record(pid: str, kind: str, ident: str, body: dict):
    if kind not in ('tasks', 'risks'):
        s.fail('此台账不提供状态流转', 404)
    return update_record(pid, kind, ident, body)


@app.post('/api/projects/{pid}/records/{kind}/{ident}/remove')
def remove_record(pid: str, kind: str, ident: str, body: sc.RemoveInput):
    if kind not in SCHEMAS:
        s.fail('功能不存在', 404)
    with transaction() as session:
        return s.remove_business(session, pid, kind, ident, body.model_dump())


@app.get('/api/projects/{pid}/history/{kind}/{ident}')
def history(pid: str, kind: str, ident: str):
    with Session() as session:
        s.project(session, pid)
        return [s.plain(x) for x in session.scalars(select(m.Revision).where(m.Revision.project_id == pid, m.Revision.kind == kind, m.Revision.entity_id == ident).order_by(m.Revision.id.desc()))]


@app.get('/api/projects/{pid}/attachments')
def attachments(pid: str, acceptance_only: bool = False):
    with Session() as session:
        s.project(session, pid)
        result = []
        query = select(m.Attachment).where(m.Attachment.project_id == pid)
        if acceptance_only:
            query = query.where(m.Attachment.is_acceptance == True, m.Attachment.removed == False)
        for item in session.scalars(query.order_by(m.Attachment.created_at.asc(), m.Attachment.id)):
            result.append({**s.plain(item), 'references': [s.plain(x) for x in session.scalars(select(m.AttachmentLink).where(m.AttachmentLink.attachment_id == item.id))]})
        return result


@app.post('/api/attachments/upload')
def upload(file: UploadFile = File(...), project_id: str | None = None, is_acceptance: bool = False):
    filename = Path((file.filename or 'unnamed').replace('\\', '/')).name
    extension = Path(filename).suffix.lower()
    conf = config()
    if extension not in [x.strip().lower() for x in conf['extensions'].split(',')]:
        s.fail('不支持此文件类型；可在设置中调整白名单')
    ident = m.uid()
    relative = 'files/' + ident + extension
    path = DATA / relative
    size, digest = 0, hashlib.sha256()
    with WRITE_LOCK:
        try:
            with transaction() as session:
                if project_id:
                    s.project(session, project_id, True)
                with path.open('xb') as target:
                    for chunk in iter(lambda: file.file.read(1024 * 1024), b''):
                        size += len(chunk)
                        if size > int(conf['max_file_mb']) * 1024 * 1024:
                            s.fail('文件超过单文件大小上限')
                        digest.update(chunk)
                        target.write(chunk)
                item = m.Attachment(id=ident, project_id=project_id, name=filename, path=relative, size=size, mime=file.content_type or 'application/octet-stream', sha256=digest.hexdigest(), is_acceptance=is_acceptance)
                session.add(item)
                session.flush()
                return s.plain(item)
        except Exception:
            path.unlink(missing_ok=True)
            raise


@app.delete('/api/attachments/staged/{ident}')
def cancel_upload(ident: str):
    with transaction() as session:
        attachment = s.get(session, m.Attachment, ident)
        if attachment.project_id:
            s.fail('已绑定项目的附件不能按暂存清理')
        (DATA / attachment.path).unlink(missing_ok=True)
        session.delete(attachment)
        return {'ok': True}


@app.get('/api/attachments/{ident}/download')
def download(ident: str):
    with Session() as session:
        attachment = s.get(session, m.Attachment, ident)
        path = DATA / attachment.path
        if not path.is_file():
            s.fail('附件文件缺失，请从备份恢复', 404)
        return FileResponse(path, filename=attachment.name, media_type='application/octet-stream')


@app.get('/api/projects/{pid}/attachments/{ident}/preview')
def attachment_preview(pid: str, ident: str):
    content, media_type = preview_attachment(pid, ident)
    return Response(content, media_type=media_type, headers={'Content-Disposition': 'inline'})


@app.put('/api/attachments/{ident}')
def update_attachment(ident: str, body: sc.AttachmentInput):
    with transaction() as session:
        item = s.get(session, m.Attachment, ident)
        if item.project_id:
            s.project(session, item.project_id, True)
        s.check_version(item, body.version)
        item.description, item.removed = body.description, body.removed
        item.version += 1
        return s.plain(item)


@app.put('/api/attachments/{ident}/acceptance')
def update_attachment_acceptance(ident: str, body: sc.AttachmentAcceptanceInput):
    with transaction() as session:
        item = s.get(session, m.Attachment, ident)
        if item.project_id:
            s.project(session, item.project_id, True)
        s.check_version(item, body.version)
        if item.removed and body.is_acceptance:
            s.fail('请先恢复附件，再设为验收材料', 409)
        item.is_acceptance = body.is_acceptance
        item.version += 1
        item.updated_at = now()
        return s.plain(item)


@app.post('/api/projects/{pid}/report-preview')
def report_preview(pid: str, body: sc.ReportInput):
    with Session() as session:
        return reporting.snapshot(session, pid, body.start, body.end)


@app.post('/api/projects/{pid}/generate')
def generate(pid: str, body: sc.ReportInput):
    with transaction() as session:
        proj = s.project(session, pid, True)
        if session.scalar(select(m.Job.id).where(m.Job.project_id == pid, m.Job.status.in_(['等待中', '生成中']))):
            s.fail('该项目已有生成任务，请稍候', 409)
        snap = reporting.snapshot(session, pid, body.start, body.end)
        if body.brief_id:
            brief = s.local_ref(session, m.Brief, body.brief_id, pid)
            if (brief.start, brief.end) != (body.start, body.end):
                s.fail('重新生成必须保持简报日期范围')
        else:
            brief = m.Brief(project_id=pid, start=body.start, end=body.end, title=proj.name + ' 项目简报')
            session.add(brief)
            session.flush()
        job = m.Job(project_id=pid, brief_id=brief.id, status='等待中', model=config()['model'], snapshot=snap)
        session.add(job)
        session.flush()
        result = s.plain(job)
    executor.submit(reporting.run_job, result['id'])
    return result


@app.get('/api/projects/{pid}/briefs')
def briefs(pid: str, page: int = Query(1, ge=1)):
    with Session() as session:
        s.project(session, pid)
        result = []
        for brief in session.scalars(select(m.Brief).where(m.Brief.project_id == pid).order_by(m.Brief.start.asc(), m.Brief.end.asc(), m.Brief.created_at.asc(), m.Brief.id).offset((page-1)*20).limit(20)):
            versions = list(session.scalars(select(m.BriefVersion).where(m.BriefVersion.brief_id == brief.id).order_by(m.BriefVersion.number.desc())))
            result.append({**s.plain(brief), 'versions': [{k: v for k, v in s.plain(x).items() if k not in ('snapshot', 'content')} for x in versions]})
        return {'items': result, 'total': session.scalar(select(func.count()).select_from(m.Brief).where(m.Brief.project_id == pid))}


@app.get('/api/projects/{pid}/jobs')
def jobs(pid: str):
    with Session() as session:
        s.project(session, pid)
        return [{k: v for k, v in s.plain(x).items() if k != 'snapshot'} for x in session.scalars(select(m.Job).where(m.Job.project_id == pid).order_by(m.Job.created_at.desc()).limit(20))]


@app.post('/api/jobs/{ident}/retry')
def retry_job(ident: str):
    with transaction() as session:
        job = s.get(session, m.Job, ident)
        s.project(session, job.project_id, True)
        if job.status != '失败' or job.attempts >= 3 or not job.retryable:
            s.fail('此任务不可重试；请修正配置后重新生成', 409)
        job.status, job.error = '等待中', ''
        job.attempts += 1
    executor.submit(reporting.run_job, ident)
    return {'ok': True}


@app.get('/api/brief-versions/{ident}')
def brief_version(ident: str):
    with Session() as session:
        return s.plain(s.get(session, m.BriefVersion, ident))


@app.post('/api/briefs/{ident}/versions')
def edit_brief(ident: str, body: sc.EditBriefInput):
    with transaction() as session:
        brief = s.get(session, m.Brief, ident)
        s.project(session, brief.project_id, True)
        s.check_version(brief, body.version)
        source = s.get(session, m.BriefVersion, body.base_version_id)
        if source.brief_id != ident:
            s.fail('正文版本不属于当前简报')
        content = body.content.model_dump()
        reporting.validate_content(content, source.snapshot, numbers=False)
        number = (session.scalar(select(func.max(m.BriefVersion.number)).where(m.BriefVersion.brief_id == ident)) or 0) + 1
        result = m.BriefVersion(brief_id=ident, number=number, snapshot=source.snapshot, content=content, model=source.model, source='人工编辑')
        session.add(result)
        brief.version += 1
        session.flush()
        return s.plain(result)


@app.get('/api/brief-versions/{ident}/export/{extension}')
def export(ident: str, extension: str):
    with Session() as session:
        version = s.get(session, m.BriefVersion, ident)
        brief = s.get(session, m.Brief, version.brief_id)
        path = export_brief(brief, version, extension)
    return FileResponse(path, filename=path.name)


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(min_length=1, max_length=100)
    max_file_mb: int = Field(50, ge=1, le=2048)
    backup_keep: int = Field(14, ge=1, le=365)
    extensions: str = Field(min_length=1)
    soffice: str = ''
    api_key: str | None = None


@app.get('/api/settings')
def settings():
    result = config()
    result.update(api_key_configured=bool(read_key()), pdf_available=bool(soffice_path() and Path(soffice_path()).is_file()), data_path=str(DATA), auto_backup_note='应用运行期间，每日首次成功数据变更后自动备份；应用关闭时不运行。')
    return result


@app.put('/api/settings')
def save_settings(body: SettingsInput):
    with WRITE_LOCK:
        if body.api_key is not None:
            save_key(body.api_key)
        data = {**config(), **body.model_dump(exclude={'api_key'})}
        pending = LOCAL / 'settings.tmp'
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
        pending.replace(LOCAL / 'settings.json')
    return settings()


@app.get('/api/backups')
def backups():
    return [{'name': p.name, 'size': p.stat().st_size} for p in sorted((DATA / 'backups').glob('*.zip'), reverse=True)]


@app.post('/api/backups')
def create_backup():
    return maintenance.make_backup()


@app.get('/api/backups/{name}/download')
def download_backup(name: str):
    return FileResponse(maintenance.backup_path(name), filename=name)


@app.get('/api/backups/{name}/preview')
def preview_backup(name: str):
    import tempfile
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        return maintenance.inspect_backup(name, Path(tmp))


class RestoreInput(BaseModel):
    confirmation: str


@app.post('/api/backups/{name}/restore')
def restore(name: str, body: RestoreInput):
    if body.confirmation != '替换当前业务数据':
        s.fail('请明确确认替换当前业务数据')
    return maintenance.restore_backup(name)


dist = ROOT / 'frontend' / 'dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
