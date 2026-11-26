"""Export the same filtered work logs as the list, without pagination."""
import io
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime

import xlsxwriter
from sqlalchemy import select

from . import models as m, service as s
from .config import now

COLUMNS = [('日志编号', 16), ('工作日期', 13), ('功能模块', 20), ('责任人', 14),
           ('参与人员', 24), ('关联任务', 28), ('工作内容', 40), ('工作详情', 60),
           ('后续安排', 40), ('备注', 32), ('日志来源', 30)]
MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def export_logs(session, pid, **filters):
    project = s.project(session, pid)
    for key in ('start', 'end'):
        if filters.get(key):
            try:
                if date.fromisoformat(filters[key]).isoformat() != filters[key]:
                    raise ValueError()
            except ValueError:
                s.fail('筛选日期必须采用 YYYY-MM-DD 格式')
    if filters.get('start') and filters.get('end') and filters['start'] > filters['end']:
        s.fail('开始日期不能晚于结束日期')
    people = {p.person_id: p.name for p in session.scalars(select(m.Member).where(m.Member.project_id == pid))}
    modules = {p.id: p.name for p in session.scalars(select(m.Module).where(m.Module.project_id == pid))}
    tasks = {p.id: p.name for p in session.scalars(select(m.Task).where(m.Task.project_id == pid))}
    participants = defaultdict(list)
    for person in session.scalars(select(m.Participant).where(m.Participant.project_id == pid, m.Participant.kind == 'logs').order_by(m.Participant.person_id)):
        participants[person.entity_id].append(people.get(person.person_id, ''))
    sources = {c.log_id: c.payload.get('subject', '') for c in session.scalars(select(m.Communication).where(m.Communication.project_id == pid))}
    records = list(session.scalars(s.business_query(session, pid, 'logs', **filters)))
    if len(records) > 1048572:
        s.fail('日志数量超过 Excel 单表上限，请缩小日期范围后导出')
    rows = []
    for record in records:
        data = record.payload or {}
        row = [record.code, datetime.combine(date.fromisoformat(record.work_date), datetime.min.time()),
               modules.get(record.module_id, ''), people.get(record.owner_id, ''),
               '、'.join(filter(None, participants[record.id])), tasks.get(record.task_id, ''),
               data.get('content', ''), data.get('details', ''), data.get('next_plan', ''), data.get('notes', ''),
               '项目沟通：' + sources[record.id] if record.id in sources else '手工登记']
        for (label, _), value in zip(COLUMNS, row):
            if isinstance(value, str) and len(value) > 32767:
                s.fail(f'日志 {record.code} 的“{label}”超过 Excel 单元格 32767 字符上限，请缩短内容后导出')
        rows.append(row)
    generated_at = datetime.fromisoformat(now())
    selected_filters = []
    for key, label, mapping in [('q', '关键词', None), ('module_id', '功能模块', modules),
                                ('owner_id', '责任人', people), ('task_id', '关联任务', tasks)]:
        if filters.get(key):
            selected_filters.append(label + '：' + (mapping.get(filters[key], '无匹配项') if mapping is not None else filters[key]))
    if filters.get('start') or filters.get('end'):
        selected_filters.append('工作日期：' + (filters.get('start') or '不限') + ' 至 ' + (filters.get('end') or '不限'))
    summary = f'共 {len(rows)} 条 · 导出时间 {generated_at:%Y-%m-%d %H:%M:%S}（北京时间） · ' + ('；'.join(selected_filters) or '全部工作日志')
    content = build_workbook(project.name, summary, rows)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project.name).strip(' .')[:80] or '项目'
    return content, f'{name}_工作日志_{generated_at:%Y%m%d_%H%M%S}.xlsx', len(rows)


def line_count(value, width):
    """Estimate wrapped lines without inflating row height for short CJK text."""
    return sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in line) / width))
               for line in str(value).split('\n'))


def build_workbook(project_name, summary, rows, columns=COLUMNS, title_name='工作日志'):
    buffer = io.BytesIO()
    # Explicit text writes keep user content such as '=...' as text, not formulas.
    with xlsxwriter.Workbook(buffer, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False}) as book:
        book.set_properties({'title': project_name + ' · ' + title_name, 'author': '交付工作台'})
        sheet = book.add_worksheet(title_name)
        base = {'font_name': 'Microsoft YaHei', 'font_size': 10, 'valign': 'top', 'text_wrap': True}
        title = book.add_format({**base, 'font_size': 18, 'bold': True, 'font_color': '#1E3A5F', 'valign': 'vcenter'})
        subtitle = book.add_format({**base, 'font_color': '#64748B', 'valign': 'vcenter'})
        header = book.add_format({**base, 'bold': True, 'bg_color': '#2563EB', 'font_color': '#FFFFFF', 'valign': 'vcenter'})
        formats = [book.add_format({**base, 'bg_color': color, 'bottom': 1, 'bottom_color': '#E2E8F0'}) for color in ('#FFFFFF', '#EFF6FF')]
        dates = [book.add_format({**base, 'bg_color': color, 'num_format': 'yyyy-mm-dd', 'bottom': 1, 'bottom_color': '#E2E8F0'}) for color in ('#FFFFFF', '#EFF6FF')]
        sheet.hide_gridlines(2)
        sheet.set_zoom(85)
        sheet.merge_range(0, 0, 0, len(columns)-1, '', title)
        sheet.write_string(0, 0, project_name + ' · ' + title_name, title)
        sheet.set_row(0, 36)
        sheet.merge_range(1, 0, 1, len(columns)-1, '', subtitle)
        sheet.write_string(1, 0, summary, subtitle)
        sheet.set_row(1, max(28, min(90, line_count(summary, 180)*16)))
        sheet.set_row(2, 8)
        sheet.set_row(3, 28)
        for col, (label, width) in enumerate(columns):
            sheet.set_column(col, col, width)
            sheet.write_string(3, col, label, header)
        for index, values in enumerate(rows):
            row = index + 4
            for col, value in enumerate(values):
                if isinstance(value, datetime):
                    sheet.write_datetime(row, col, value, dates[index % 2])
                elif isinstance(value, (int, float)):
                    sheet.write_number(row, col, value, formats[index % 2])
                else:
                    sheet.write_string(row, col, value or '', formats[index % 2])
            height = max(line_count(value, width-2) for value, (_, width) in zip(values, columns) if not isinstance(value, datetime))
            sheet.set_row(row, min(409, max(30, height*16+8)))
        sheet.freeze_panes(4, 2)
        sheet.autofilter(3, 0, max(3, len(rows)+3), len(columns)-1)
        sheet.set_landscape()
        sheet.set_paper(8)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(3)
    return buffer.getvalue()
