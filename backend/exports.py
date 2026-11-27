import re
import hashlib
import subprocess
import tempfile
from uuid import uuid4
from pathlib import Path
from docxtpl import DocxTemplate
from docx import Document
from .config import DATA, ROOT, soffice_path
from .service import fail
from .markdown_export import append_markdown, RENDER_VERSION


def export_brief(brief, version, extension):
    if extension not in ('docx', 'pdf'):
        fail('不支持的导出格式')
    snap = version.snapshot
    imported = snap.get('format') == 'imported-markdown-v1'
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', brief.title if imported else snap['project_name'])[:80]
    name += '_' + brief.start + '_' + brief.end + '_V' + str(version.number)
    # Version ID prevents collisions across regenerated briefs for the same period.
    template_path = ROOT / 'templates' / 'brief.docx'
    # Refresh old exports when the document template changes.
    template_revision = hashlib.sha256(template_path.read_bytes() + RENDER_VERSION.encode() + b'import-export-1').hexdigest()[:12]
    folder = DATA / 'exports' / version.id / template_revision
    folder.mkdir(parents=True, exist_ok=True)
    document = folder / (name + '.docx')
    if not document.exists():
        if imported:
            from docx.shared import Inches, Pt
            from docx.oxml.ns import qn
            from .brief_import import image_resolver
            rendered = Document()
            section = rendered.sections[0]
            section.page_width, section.page_height = Inches(8.5), Inches(11)
            normal = rendered.styles['Normal']
            normal.font.name = '宋体'
            normal.font.size = Pt(11)
            normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), '宋体')
            normal.paragraph_format.space_after = Pt(6)
            rendered.core_properties.title = brief.title
            rendered.core_properties.author = 'FDE交付工作台'
            for section in version.content['sections']:
                for paragraph in section['paragraphs']:
                    append_markdown(rendered, paragraph['text'], image_resolver=image_resolver(snap))
            rendered.save(document)
        else:
            template = DocxTemplate(template_path)
            sections = []
            sources = {}
            for section in version.content['sections']:
                paragraphs = []
                for p in section['paragraphs']:
                    if p['text'].strip():
                        marker = 'PMMARKDOWN' + uuid4().hex
                        sources[marker] = p['text']
                        paragraphs.append({'text': marker})
                if paragraphs:
                    sections.append({'heading': '一二三四五六七八九十'[len(sections)] + '、' + section['heading'], 'paragraphs': paragraphs})
            template.render({'project': snap['project_name'], 'start': chinese_date(brief.start), 'end': chinese_date(brief.end),
                             'sections': sections}, autoescape=True)
            template.save(document)
            rendered = Document(document)
            for paragraph in list(rendered.paragraphs):
                if paragraph.text.strip() in sources:
                    append_markdown(rendered, sources[paragraph.text.strip()], anchor=paragraph)
            rendered.save(document)
    if extension == 'docx':
        return document
    return document_pdf(document)


def document_pdf(document):
    folder = document.parent
    executable = soffice_path()
    if not executable or not Path(executable).is_file():
        fail('未找到 LibreOffice 转换组件。请在设置中填写 soffice.exe 路径；Word 仍可导出。', 503)
    output = document.with_suffix('.pdf')
    def complete_pdf():
        if not output.is_file():
            return False
        try:
            import pypdfium2 as pdfium
            data = output.read_bytes()
            if not data.startswith(b'%PDF-') or not data.rstrip().endswith(b'%%EOF'):
                return False
            with pdfium.PdfDocument(data) as pdf:
                return len(pdf) > 0
        except (OSError, ValueError, RuntimeError):
            return False

    if not complete_pdf():
        output.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix='lo-', dir=DATA / 'exports', ignore_cleanup_errors=True) as profile:
            try:
                result = subprocess.run([executable, '-env:UserInstallation=' + Path(profile).as_uri(), '--headless', '--convert-to', 'pdf', '--outdir', str(folder), str(document)], capture_output=True, timeout=90,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                # Windows Office can finish the file before its launcher exits.
                # Only accept a fully closed, readable PDF; partial files must not be cached.
                if complete_pdf():
                    return output
                output.unlink(missing_ok=True)
                fail('PDF 转换超时，请重试；Word 文件已保留。', 503)
            except OSError:
                fail('PDF 转换超时或无法启动，请检查转换组件；Word 文件已保留。', 503)
            if result.returncode != 0 or not complete_pdf():
                output.unlink(missing_ok=True)
                fail('PDF 转换失败，请检查 LibreOffice 和中文字体配置。', 503)
    return output


def chinese_date(value):
    year, month, day = value.split('-')
    return f'{year}年{int(month)}月{int(day)}日'
