import re
import hashlib
import subprocess
import tempfile
from pathlib import Path
from docxtpl import DocxTemplate
from .config import DATA, ROOT, soffice_path
from .service import fail


def export_brief(brief, version, extension):
    if extension not in ('docx', 'pdf'):
        fail('不支持的导出格式')
    snap = version.snapshot
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', snap['project_name'])[:80]
    name += '_' + brief.start + '_' + brief.end + '_V' + str(version.number)
    # Version ID prevents collisions across regenerated briefs for the same period.
    template_path = ROOT / 'templates' / 'brief.docx'
    # Refresh old exports when the document template changes.
    template_revision = hashlib.sha256(template_path.read_bytes()).hexdigest()[:12]
    folder = DATA / 'exports' / version.id / template_revision
    folder.mkdir(parents=True, exist_ok=True)
    document = folder / (name + '.docx')
    if not document.exists():
        template = DocxTemplate(template_path)
        sections = []
        for section in version.content['sections']:
            paragraphs = [{'text': p['text']} for p in section['paragraphs'] if p['text'].strip()]
            if paragraphs:
                sections.append({'heading': '一二三四五六七八九十'[len(sections)] + '、' + section['heading'], 'paragraphs': paragraphs})
        template.render({'project': snap['project_name'], 'start': chinese_date(brief.start), 'end': chinese_date(brief.end),
                         'sections': sections}, autoescape=True)
        template.save(document)
    if extension == 'docx':
        return document
    return document_pdf(document)


def document_pdf(document):
    folder = document.parent
    executable = soffice_path()
    if not executable or not Path(executable).is_file():
        fail('未找到 LibreOffice 转换组件。请在设置中填写 soffice.exe 路径；Word 仍可导出。', 503)
    output = document.with_suffix('.pdf')
    if not output.exists():
        with tempfile.TemporaryDirectory(prefix='lo-', dir=DATA / 'exports', ignore_cleanup_errors=True) as profile:
            try:
                result = subprocess.run([executable, '-env:UserInstallation=' + Path(profile).as_uri(), '--headless', '--convert-to', 'pdf', '--outdir', str(folder), str(document)], capture_output=True, timeout=90,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (subprocess.TimeoutExpired, OSError):
                fail('PDF 转换超时或无法启动，请检查转换组件；Word 文件已保留。', 503)
            if result.returncode != 0 or not output.exists():
                fail('PDF 转换失败，请检查 LibreOffice 和中文字体配置。', 503)
    return output


def chinese_date(value):
    year, month, day = value.split('-')
    return f'{year}年{int(month)}月{int(day)}日'
