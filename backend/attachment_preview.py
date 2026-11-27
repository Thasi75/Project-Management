"""Local, read-only previews. Original attachments and business rows never change."""
import hashlib
import csv
import io
import json
from itertools import islice
import subprocess
import tempfile
from pathlib import Path
from threading import BoundedSemaphore

from .config import DATA, soffice_path
from .db import Session, WRITE_LOCK
from . import models as m, service as s

IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.gif': 'image/gif', '.webp': 'image/webp'}
OFFICE_TYPES = {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
CONVERSION_SLOT = BoundedSemaphore(1)


def decode_text(content):
    encodings = ['utf-16'] if content.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    s.fail('无法识别文本编码，请下载原文件查看', 422)


def preview_attachment(pid, ident):
    # This endpoint bypasses the long-lived request gate. Capture an immutable
    # snapshot under the same lock used by restore, then release it before conversion.
    with WRITE_LOCK, Session() as session:
        s.project(session, pid)
        item = s.get(session, m.Attachment, ident)
        if item.project_id != pid or item.removed:
            s.fail('当前项目中找不到这份附件，请刷新列表', 404)
        path = (DATA / item.path).resolve()
        if not path.is_relative_to((DATA / 'files').resolve()) or not path.is_file():
            s.fail('附件文件缺失，请从备份恢复', 404)
        extension = Path(item.name).suffix.lower()
        if extension not in IMAGE_TYPES and extension not in OFFICE_TYPES | {'.pdf', '.txt', '.md', '.csv'}:
            s.fail('此文件类型暂不支持预览，请下载原文件查看', 415)
        content = path.read_bytes()
    if extension in IMAGE_TYPES:
        return content, IMAGE_TYPES[extension]
    if extension == '.pdf':
        if b'%PDF-' not in content[:1024]:
            s.fail('PDF 文件损坏或格式不正确，请下载原文件检查', 422)
        return content, 'application/pdf'
    if extension in {'.txt', '.md', '.csv'}:
        if len(content) > 2 * 1024 * 1024:
            s.fail('文本文件较大，请下载原文件查看', 413)
        text = decode_text(content)
        if extension == '.csv':
            try:
                rows = list(islice(csv.reader(io.StringIO(text)), 1001))
            except csv.Error:
                s.fail('无法读取 CSV 表格，请下载原文件检查', 422)
            truncated = len(rows) > 1000 or any(len(row) > 100 for row in rows)
            return json.dumps({'rows': [row[:100] for row in rows[:1000]], 'truncated': truncated}, ensure_ascii=False).encode('utf-8'), 'application/json'
        return text.encode('utf-8'), 'text/plain'
    return office_pdf(content, extension), 'application/pdf'


def office_pdf(content, extension):
    cache = DATA / 'previews' / 'v1'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(content + extension.encode()).hexdigest() + '.pdf')
    if target.is_file():
        return target.read_bytes()
    executable = soffice_path()
    if not executable or not Path(executable).is_file():
        s.fail('未找到文档转换组件，请在设置与维护中配置 LibreOffice，或下载原文件查看', 503)
    if not CONVERSION_SLOT.acquire(blocking=False):
        s.fail('另一份文档正在生成预览，请稍后重试', 503)
    try:
        if target.is_file():
            return target.read_bytes()
        # On Windows LibreOffice can briefly retain profile files while exiting.
        # A cleanup race must not turn a successfully generated PDF into HTTP 500.
        with tempfile.TemporaryDirectory(prefix='convert-', dir=cache, ignore_cleanup_errors=True) as folder:
            work = Path(folder)
            source = work / ('source' + extension)
            source.write_bytes(content)
            profile = work / 'profile'
            (profile / 'user').mkdir(parents=True)
            # Disable macros and external-link updates in the disposable profile.
            (profile / 'user' / 'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop><prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
</oor:items>''', encoding='utf-8')
            console_executable = Path(executable).with_suffix('.com')
            runner = str(console_executable) if console_executable.is_file() else executable
            command = [runner, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
                       '--nodefault', '--norestore', '--convert-to', 'pdf', '--outdir', str(work), str(source)]
            try:
                result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                # Windows may retain the launcher after the output is complete.
                # Avoid pipe reader threads and only accept a fully readable PDF.
                output = work / 'source.pdf'
                try:
                    import pypdfium2 as pdfium
                    data = output.read_bytes()
                    if not data.rstrip().endswith(b'%%EOF'):
                        raise ValueError('Incomplete PDF')
                    with pdfium.PdfDocument(data) as document:
                        if not len(document):
                            raise ValueError('Empty PDF')
                except (OSError, ValueError, RuntimeError):
                    s.fail('文档预览生成超时，请重试或下载原文件查看', 503)
                output.replace(target)
                return data
            except OSError:
                s.fail('文档预览生成超时或无法启动，请重试或下载原文件查看', 503)
            output = work / 'source.pdf'
            if result.returncode != 0 or not output.is_file() or not output.read_bytes().startswith(b'%PDF-'):
                s.fail('无法预览此文档，文件可能已加密或损坏，请下载原文件查看', 422)
            result_bytes = output.read_bytes()
            output.replace(target)
            return result_bytes
    finally:
        CONVERSION_SLOT.release()
