"""Export one saved communication without changing business records."""
import hashlib
import json
import re
import tempfile
from pathlib import Path
from threading import Lock

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from sqlalchemy import select

from . import models as m, service as s
from .config import DATA
from .exports import document_pdf

LAYOUT_VERSION = 2
PDF_LOCK = Lock()


def communication_snapshot(session, pid, ident, version=None):
    project = s.project(session, pid)
    communication = s.local_ref(session, m.Communication, ident, pid, True)
    if communication.deleted:
        s.fail('已移除的沟通记录不能导出', 404)
    if version is not None:
        s.check_version(communication, version)
    record = s.serialize(session, communication)
    people = {p.person_id: p for p in session.scalars(select(m.Member).where(m.Member.project_id == pid))}

    def person(ident):
        profile = people.get(ident)
        if profile is None:
            return '未登记人员'
        return profile.name + ('（' + profile.team.strip() + '）' if profile.team.strip() else '')

    module = session.get(m.Module, record.get('module_id')) if record.get('module_id') else None
    return {'id': communication.id, 'version': communication.version, 'project': project.name,
            'subject': record['subject'], 'occurred_at': record['occurred_at'],
            'location': record.get('location') or '未填写',
            'module': module.name if module else '未指定模块',
            'host': person(record['host_id']), 'recorder': person(record['recorder_id']),
            'participants': [person(ident) for ident in record['participant_ids']],
            'summary': record['summary'], 'details': record.get('details', '')}


def font(style, name, size):
    style.font.name = name
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), name)


def build_document(snapshot, target):
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.3)
    section.left_margin = section.right_margin = Cm(2.5)
    normal = document.styles['Normal']
    font(normal, '仿宋', 12)
    normal.paragraph_format.line_spacing = 1.4
    normal.paragraph_format.space_after = Pt(6)
    font(document.styles['Title'], '黑体', 18)
    document.styles['Title'].paragraph_format.space_after = Pt(12)
    font(document.styles['Heading 1'], '黑体', 13)
    document.styles['Heading 1'].paragraph_format.space_before = Pt(12)
    document.styles['Heading 1'].paragraph_format.space_after = Pt(6)
    # Avoid inherited theme accents and title borders.
    for name in ('Title', 'Heading 1'):
        props = document.styles[name].element.get_or_add_rPr()
        color = props.find(qn('w:color'))
        if color is not None:
            for attr in ('themeColor', 'themeTint', 'themeShade'):
                color.attrib.pop(qn('w:' + attr), None)
    for border in list(document.styles.element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)
    document.add_paragraph('项目沟通记录', 'Title')
    for label, value in [('项目', snapshot['project']), ('主题', snapshot['subject']),
                         ('时间', snapshot['occurred_at']), ('地点', snapshot['location']),
                         ('功能模块', snapshot['module']),
                         ('参与人员', '、'.join(snapshot['participants']) or '未登记'),
                         ('主持人', snapshot['host']), ('记录人', snapshot['recorder'])]:
        p = document.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(label + '：')
        run.bold = True
        p.add_run(value)
    for heading, content in [('沟通概况', snapshot['summary']), ('沟通详情', snapshot['details'])]:
        if not content.strip():
            continue
        document.add_paragraph(heading, 'Heading 1')
        # Preserve literal text, blank lines and indentation; no Markdown interpretation.
        for line in content.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            document.add_paragraph(line)
    footer = section.footer.paragraphs[0]
    footer.alignment = 1
    font(document.styles['Footer'], '宋体', 9)
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    document.save(target)


def export_communication(snapshot, extension):
    if extension not in ('docx', 'pdf'):
        s.fail('不支持的导出格式', 422)
    digest = hashlib.sha256(json.dumps([LAYOUT_VERSION, snapshot], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    folder = DATA / 'exports' / 'communications' / snapshot['id'] / digest
    folder.mkdir(parents=True, exist_ok=True)
    def safe_name(value):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:50] or '项目沟通'
    name = safe_name(snapshot['project']) + '_' + safe_name(snapshot['subject'])
    name += '_' + snapshot['occurred_at'][:10] + '_V' + str(snapshot['version'])
    document = folder / (name + '.docx')
    if not document.is_file():
        with tempfile.TemporaryDirectory(prefix='communication-', dir=folder) as work:
            pending = Path(work) / 'record.docx'
            build_document(snapshot, pending)
            pending.replace(document)
    if extension == 'docx':
        return document
    with PDF_LOCK:
        return document_pdf(document)
