"""Export all filtered requirements research using the list's query and ordering."""
import re
from datetime import date, datetime
from sqlalchemy import select
from . import models as m, service as s
from .config import now
from .log_export import build_workbook

COLUMNS = [('序号', 8), ('编号', 16), ('日期', 13), ('功能模块', 24), ('需求描述', 56),
           ('需求来源', 16), ('记录人', 16), ('重要性', 10), ('是否响应', 12),
           ('状态', 10), ('解决思路', 56), ('备注', 36)]


def export_research(session, pid, **filters):
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
    records = list(session.scalars(s.business_query(session, pid, 'research', **filters)))
    if len(records) > 1048572:
        s.fail('调研数量超过 Excel 单表上限，请缩小日期范围后导出')
    rows = []
    for record in records:
        row = [record.sequence, record.code, datetime.combine(date.fromisoformat(record.research_date), datetime.min.time()),
               modules[record.module_id], record.payload['requirement'], people[record.source_id],
               people[record.recorder_id], record.importance, record.responded, record.status,
               record.payload['solution'], record.payload.get('notes', '')]
        for (label, _), value in zip(COLUMNS, row):
            if isinstance(value, str) and len(value) > 32767:
                s.fail(f'调研 {record.code} 的“{label}”超过 Excel 单元格 32767 字符上限，请缩短内容后导出')
        rows.append(row)
    selected = []
    for key, label, mapping in [('q', '关键词', None), ('module_id', '功能模块', modules),
                                ('status', '状态', None), ('importance', '重要性', None),
                                ('responded', '是否响应', None), ('source_id', '需求来源', people),
                                ('recorder_id', '记录人', people)]:
        if filters.get(key):
            selected.append(label + '：' + (mapping.get(filters[key], '无匹配项') if mapping is not None else filters[key]))
    if filters.get('start') or filters.get('end'):
        selected.append('日期：' + (filters.get('start') or '不限') + ' 至 ' + (filters.get('end') or '不限'))
    generated = datetime.fromisoformat(now())
    summary = f'共 {len(rows)} 条 · 导出时间 {generated:%Y-%m-%d %H:%M:%S}（北京时间） · ' + ('；'.join(selected) or '全部需求调研')
    content = build_workbook(project.name, summary, rows, columns=COLUMNS, title_name='需求调研')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project.name).strip(' .')[:80] or '项目'
    return content, f'{name}_需求调研_{generated:%Y%m%d_%H%M%S}.xlsx', len(rows)
