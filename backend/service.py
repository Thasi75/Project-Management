import hashlib
import json
from datetime import date
from decimal import Decimal
from sqlalchemy import select, delete, func, or_, cast, String
from fastapi import HTTPException
from . import models as m
from .config import today, now

KINDS = {'tasks': m.Task, 'logs': m.WorkLog, 'changes': m.Change, 'risks': m.Risk, 'communications': m.Communication, 'coding': m.CodingWork, 'configurations': m.Configuration, 'costs': m.Cost, 'research': m.Research}
PREFIX = {'tasks': 'T', 'logs': 'L', 'changes': 'C', 'risks': 'R', 'communications': 'M', 'coding': 'CODE', 'configurations': 'CFG', 'costs': 'COST', 'research': 'REQ'}
META = {'version', 'effective_date', 'reason'}
RELATIONS = {'participant_ids', 'attachment_ids', 'change_ids', 'task_ids'}
SCOPE_FIELDS = ('scope', 'exclusions', 'deliverables', 'acceptance')
COMMUNICATION_LOG_FIELDS = ('work_date', 'module_id', 'owner_id', 'participant_ids', 'content', 'details')


def fail(message, status=422):
    raise HTTPException(status, message)


def get(session, model, ident):
    obj = session.get(model, ident)
    if not obj:
        fail('记录不存在', 404)
    return obj


def project(session, ident, write=False):
    obj = get(session, m.Project, ident)
    if write and obj.archived:
        fail('项目已归档，恢复后才能修改', 409)
    return obj


def check_version(obj, version):
    if version is None or obj.version != version:
        fail('记录已被其他窗口修改，请刷新后重新编辑', 409)


def local_ref(session, model, ident, pid, allow_disabled=False):
    if not ident:
        return
    obj = get(session, model, ident)
    if obj.project_id != pid:
        fail('不能关联其他项目的记录')
    if not allow_disabled and (getattr(obj, 'deleted', False) or getattr(obj, 'removed', False) or not getattr(obj, 'enabled', True)):
        fail('不能新增关联已停用或移除的记录')
    return obj


def person_ref(session, ident, pid, allow_disabled=False):
    if not ident:
        return
    obj = session.get(m.Member, (pid, ident))
    if not obj:
        fail('负责人、责任人和参与人员必须来自本项目的人员资料')
    if not allow_disabled and not obj.enabled:
        fail('不能新增选择已停用人员')
    return obj


def person_profile(obj):
    result = plain(obj)
    result['id'] = result.pop('person_id')
    return result


def plain(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def serialize(session, obj):
    result = plain(obj)
    result.update(result.pop('payload', {}) or {})
    if isinstance(obj, m.Research):
        result.setdefault('is_interface', False)
        result.setdefault('integration_system', '')
        result.setdefault('development_notes', '')
        result.setdefault('go_live_date', None)
    if isinstance(obj, m.Cost):
        result['amount'] = money_string(result.pop('amount_cents'))
    if isinstance(obj, m.Project):
        result['member_ids'] = list(session.scalars(select(m.Member.person_id).where(m.Member.project_id == obj.id)))
        scopes = list(session.scalars(select(m.Scope).where(m.Scope.project_id == obj.id).order_by(m.Scope.number)))
        result['scope_number'] = scopes[-1].number if scopes else 0
        result['attachment_ids'] = list(session.scalars(select(m.Attachment.id).where(m.Attachment.project_id == obj.id, m.Attachment.removed == False)))
    kind = next((k for k, model in KINDS.items() if isinstance(obj, model)), None)
    if kind:
        if kind in ('tasks', 'logs', 'communications'):
            result['participant_ids'] = list(session.scalars(select(m.Participant.person_id).where(m.Participant.kind == kind, m.Participant.entity_id == obj.id)))
        if kind in ('tasks', 'changes'):
            result['attachment_ids'] = list(session.scalars(select(m.AttachmentLink.attachment_id).where(m.AttachmentLink.kind == kind, m.AttachmentLink.entity_id == obj.id)))
        if kind == 'tasks':
            result['change_ids'] = list(session.scalars(select(m.ChangeTask.change_id).where(m.ChangeTask.task_id == obj.id)))
        if kind == 'changes':
            result['task_ids'] = list(session.scalars(select(m.ChangeTask.task_id).where(m.ChangeTask.change_id == obj.id)))
        if kind == 'logs':
            source = session.scalar(select(m.Communication).where(m.Communication.log_id == obj.id))
            if source:
                result['communication_id'] = source.id
                result['communication_subject'] = source.payload['subject']
        if kind == 'communications' and not result.get('module_id'):
            # Legacy communications may already have a module assigned on their log.
            linked = session.get(m.WorkLog, obj.log_id)
            if linked and linked.module_id:
                result['module_id'] = linked.module_id
    return result


def record(session, pid, kind, ident, before, after, effective, reason, corrections=None):
    patch = {k: v for k, v in after.items() if k not in ('version', 'updated_at', 'created_at') and (before is None or before.get(k) != v)}
    if corrections:
        patch['_corrections'] = corrections
    revision = m.Revision(project_id=pid, kind=kind, entity_id=ident, before=before, after=after,
                          patch=patch, effective_date=effective, reason=reason or '登记')
    session.add(revision)
    return revision


def create_scope(session, obj, data, reason):
    last = session.scalar(select(func.max(m.Scope.number)).where(m.Scope.project_id == obj.id)) or 0
    local_ref(session, m.Change, data.get('change_id'), obj.id)
    session.add(m.Scope(project_id=obj.id, number=last + 1, effective_date=data['effective_date'],
                        reason=reason or '初始范围', change_id=data.get('change_id'), payload={k: data[k] for k in SCOPE_FIELDS}))


def save_project(session, data, ident=None):
    obj = project(session, ident, True) if ident else m.Project(id=m.uid(), code='P-' + m.uid()[:8].upper())
    old = serialize(session, obj) if ident else None
    if old:
        check_version(obj, data['version'])
    ids = old['member_ids'] if old else []
    if data.get('member_ids') is not None and sorted(data['member_ids']) != sorted(ids):
        fail('请在项目概况的人员资料中维护本项目人员；不能从其他项目添加或移除成员')
    person_ref(session, data.get('owner_id'), obj.id, bool(old and old.get('owner_id') == data.get('owner_id')))
    obj.name, obj.status = data['name'], data['status']
    obj.payload = {k: v for k, v in data.items() if k not in META | {'member_ids', 'attachment_ids', 'change_id', 'name', 'status'}}
    if old:
        obj.version += 1
    obj.updated_at = now()
    session.add(obj)
    session.flush()
    for aid in data['attachment_ids']:
        attachment = get(session, m.Attachment, aid)
        if attachment.project_id and attachment.project_id != obj.id:
            fail('附件属于其他项目')
        attachment.project_id = obj.id
    session.flush()
    if not old or any(old[k] != data[k] for k in SCOPE_FIELDS):
        if old and not data['reason']:
            fail('修改范围必须填写修订原因')
        create_scope(session, obj, data, data['reason'])
    if not old:
        session.add(m.Module(project_id=obj.id, name='项目公共事务', sort=0))
    session.flush()
    result = serialize(session, obj)
    record(session, obj.id, 'projects', obj.id, old, result, data['effective_date'], data['reason'])
    return result


def validate_refs(session, pid, kind, data, old):
    for key, model in [('module_id', m.Module), ('task_id', m.Task), ('scope_id', m.Scope)]:
        if key in data:
            local_ref(session, model, data[key], pid, bool(old and old.get(key) == data[key]))
    if 'owner_id' in data:
        person_ref(session, data['owner_id'], pid, bool(old and old.get('owner_id') == data['owner_id']))
    if kind in ('communications', 'research'):
        for field in (('host_id', 'recorder_id') if kind == 'communications' else ('source_id', 'recorder_id')):
            person_ref(session, data[field], pid, bool(old and old.get(field) == data[field]))
    for key, model in [('attachment_ids', m.Attachment), ('change_ids', m.Change), ('task_ids', m.Task)]:
        for ident in data.get(key, []):
            local_ref(session, model, ident, pid, bool(old and ident in old.get(key, [])))
    participants = data.get('participant_ids', [])
    if len(participants) != len(set(participants)):
        fail('参与人员不能重复')
    for ident in participants:
        person_ref(session, ident, pid, bool(old and ident in old.get('participant_ids', [])))
    for key in RELATIONS:
        if key in data and len(set(data[key])) != len(data[key]):
            fail('关联记录不能重复')


def validate_task(old, data):
    if not old:
        return
    previous, state = old['status'], data['status']
    allowed = {'未开始': ['进行中', '已完成', '已取消'], '进行中': ['暂停', '已完成', '已取消'],
               '暂停': ['进行中', '已完成', '已取消'], '已完成': ['进行中'],
               '已取消': ['进行中' if old.get('actual_start') else '未开始']}
    if state != previous and state not in allowed[previous]:
        fail('不允许该状态转换')
    changed = any(old.get(k) != data.get(k) for k in ['status', 'plan_start', 'plan_end', 'actual_start', 'actual_end'])
    if changed and not data['reason']:
        fail('状态、计划或实际日期修改必须填写原因')
    if previous == '已完成' and state == '进行中':
        if data['effective_date'] < old['actual_end']:
            fail('重新打开日期不能早于此前完成日期')
        if not data['actual_deliverable']:
            data['actual_deliverable'] = old['actual_deliverable']
    if data.get('actual_start') and data['effective_date'] < data['actual_start'] and state in ('进行中', '暂停'):
        fail('状态生效日期不能早于实际开始日期')


def sync_relations(session, obj, kind, data):
    pid = obj.project_id
    if kind in ('tasks', 'logs', 'communications'):
        session.execute(delete(m.Participant).where(m.Participant.kind == kind, m.Participant.entity_id == obj.id))
        for person_id in data.get('participant_ids', []):
            session.add(m.Participant(kind=kind, entity_id=obj.id, person_id=person_id, project_id=pid))
    if kind in ('tasks', 'changes'):
        session.execute(delete(m.AttachmentLink).where(m.AttachmentLink.kind == kind, m.AttachmentLink.entity_id == obj.id))
        for aid in data.get('attachment_ids', []):
            session.add(m.AttachmentLink(kind=kind, entity_id=obj.id, attachment_id=aid, project_id=pid))
        column = m.ChangeTask.task_id if kind == 'tasks' else m.ChangeTask.change_id
        session.execute(delete(m.ChangeTask).where(column == obj.id))
        for ident in data.get('change_ids' if kind == 'tasks' else 'task_ids', []):
            session.add(m.ChangeTask(project_id=pid, task_id=obj.id if kind == 'tasks' else ident,
                                    change_id=ident if kind == 'tasks' else obj.id))


def save_business(session, pid, kind, data, ident=None, key=None, from_communication=False):
    project(session, pid, True)
    model = KINDS[kind]
    fingerprint = hashlib.sha256(json.dumps([pid, kind, data], sort_keys=True).encode()).hexdigest()
    if not ident and key:
        previous = session.get(m.Idempotency, key)
        if previous:
            if previous.fingerprint != fingerprint or previous.kind != kind:
                fail('提交标识已用于其他内容，请刷新后重试', 409)
            return serialize(session, get(session, model, previous.entity_id))
    obj = local_ref(session, model, ident, pid) if ident else model(id=m.uid(), project_id=pid, code=PREFIX[kind] + '-' + m.uid()[:8].upper())
    old = serialize(session, obj) if ident else None
    if old:
        check_version(obj, data['version'])
    if kind == 'logs' and old and old.get('communication_id') and not from_communication:
        for field in COMMUNICATION_LOG_FIELDS:
            before, after = old.get(field), data.get(field)
            if field == 'participant_ids':
                before, after = sorted(before or []), sorted(after or [])
            if before != after:
                fail('该日志由项目沟通同步生成，请在项目沟通中修改日期、功能模块、责任人、参与人员、工作内容及详情', 409)
    if kind == 'research' and data.get('sequence') is None:
        data = {**data, 'sequence': old['sequence'] if old else next_research_sequence(session, pid)}
    if kind == 'research':
        # This detail is edited only through the restricted external-interface endpoint.
        data = {**data, 'development_notes': old.get('development_notes', '') if old else ''}
    validate_refs(session, pid, kind, data, old)
    if kind == 'communications':
        from .schemas import LogInput
        linked = local_ref(session, m.WorkLog, obj.log_id, pid) if old else None
        previous_log = serialize(session, linked) if linked else {}
        log_data = {key: previous_log[key] for key in LogInput.model_fields if key in previous_log}
        log_data.update(work_date=data['occurred_at'][:10], module_id=data['module_id'], owner_id=data['host_id'],
                        participant_ids=data['participant_ids'], content=data['summary'], details=data['details'],
                        effective_date=data['effective_date'], reason=data['reason'] or '项目沟通同步')
        log_data = LogInput.model_validate(log_data).model_dump()
        linked_result = save_business(session, pid, 'logs', log_data, linked.id if linked else None, from_communication=True)
        obj.log_id = linked_result['id']
    if kind == 'tasks':
        validate_task(old, data)
    corrections = []
    if old and kind in ('tasks', 'risks'):
        date_fields = ('actual_start', 'actual_end') if kind == 'tasks' else ('raised_date', 'closed_date')
        for field in date_fields:
            if old.get(field) and data.get(field) and old[field] != data[field]:
                corrections.append({'field': field, 'old': old[field], 'new': data[field]})
    if kind == 'costs':
        data = dict(data)
        data['amount_cents'] = int(Decimal(data.pop('amount')) * 100)
    obj.payload = {k: v for k, v in data.items() if k not in META | RELATIONS and k not in obj.__table__.columns.keys()}
    for k, value in data.items():
        if k in obj.__table__.columns.keys() and k not in META:
            setattr(obj, k, value)
    obj.updated_at = now()
    if old:
        obj.version += 1
    session.add(obj)
    session.flush()
    sync_relations(session, obj, kind, data)
    session.flush()
    result = serialize(session, obj)
    effective = data['effective_date']
    if kind == 'tasks':
        # Record plan, execution start and completion on their own business dates.
        baseline = dict(result)
        if not old:
            baseline.update(status='未开始', actual_start=None, actual_end=None, actual_deliverable='', delivery_url='', attachment_ids=[])
            record(session, pid, kind, obj.id, None, baseline, min(effective, data['plan_start'], data.get('actual_start') or effective), data['reason'])
        else:
            baseline = dict(old)
        if result.get('actual_start') and (not old or not old.get('actual_start')):
            started = {**baseline, 'status': '进行中', 'actual_start': result['actual_start'], 'actual_end': None}
            record(session, pid, kind, obj.id, baseline, started, result['actual_start'], data['reason'] or '补录实际开始')
            baseline = started
        if result['status'] == '已完成':
            effective = result['actual_end']
        record(session, pid, kind, obj.id, baseline, result, effective, data['reason'], corrections)
    elif kind == 'risks':
        if not old:
            baseline = {**result, 'status': '待处理', 'closed_date': None}
            record(session, pid, kind, obj.id, None, baseline, result['raised_date'], data['reason'])
            old = baseline
        record(session, pid, kind, obj.id, old, result, result.get('closed_date') or effective, data['reason'], corrections)
    else:
        record(session, pid, kind, obj.id, old, result, effective, data['reason'])
    if not ident and key:
        session.add(m.Idempotency(key=key, fingerprint=fingerprint, kind=kind, entity_id=obj.id))
    return result


def remove_business(session, pid, kind, ident, data, from_communication=False):
    project(session, pid, True)
    obj = local_ref(session, KINDS[kind], ident, pid)
    check_version(obj, data['version'])
    if date.fromisoformat(data['effective_date']).isoformat() > today():
        fail('移除日期不能在未来')
    old = serialize(session, obj)
    if kind == 'logs' and old.get('communication_id') and not from_communication:
        fail('该日志由项目沟通同步生成，请在项目沟通中移除，系统会同步移除日志', 409)
    if kind == 'communications':
        linked = local_ref(session, m.WorkLog, obj.log_id, pid)
        remove_business(session, pid, 'logs', linked.id, {**data, 'version': linked.version}, from_communication=True)
    obj.deleted = True
    obj.version += 1
    obj.updated_at = now()
    result = serialize(session, obj)
    record(session, pid, kind, ident, old, result, data['effective_date'], data['reason'])
    return result


def next_research_sequence(session, pid):
    project(session, pid)
    number = (session.scalar(select(func.max(m.Research.sequence)).where(m.Research.project_id == pid)) or 0) + 1
    if number > 2147483647:
        fail('自动序号已达上限，请手工填写有效序号')
    return number


def external_interface(session, pid, ident, write=False):
    project(session, pid, write)
    obj = local_ref(session, m.Research, ident, pid)
    if not obj.payload.get('is_interface', False):
        fail('该需求已不属于外部接口，请刷新列表', 409)
    return obj


def update_external_interface(session, pid, ident, data):
    obj = external_interface(session, pid, ident, True)
    check_version(obj, data['version'])
    old = serialize(session, obj)
    obj.status = data['status']
    obj.payload = {**obj.payload, 'development_notes': data['development_notes'], 'go_live_date': data['go_live_date']}
    obj.version += 1
    obj.updated_at = now()
    session.flush()
    result = serialize(session, obj)
    record(session, pid, 'research', ident, old, result, today(), '维护外部接口')
    return result


def business_query(session, pid, kind, **filters):
    model = KINDS[kind]
    query = select(model).where(model.deleted == False)
    if pid:
        project(session, pid)
        query = query.where(model.project_id == pid)
    else:
        query = query.join(m.Project).where(m.Project.archived == False)
    if kind == 'research' and filters.get('is_interface') is not None:
        query = query.where(func.coalesce(model.payload['is_interface'].as_boolean(), False) == filters['is_interface'])
    if filters.get('status_ne'):
        if kind not in ('tasks', 'risks', 'research'):
            fail('此列表不支持排除状态筛选')
        query = query.where(model.status != filters['status_ne'])
    if filters.get('overdue'):
        if kind != 'tasks':
            fail('仅任务支持逾期筛选')
        query = query.where(model.status.not_in(('已完成', '已取消')), model.plan_end < today())
    for field in ('status', 'owner_id', 'module_id', 'task_id', 'phase', 'host_id', 'expense_item', 'importance', 'responded', 'source_id', 'recorder_id'):
        if filters.get(field):
            if field == 'task_id' and kind == 'changes':
                query = query.where(model.id.in_(select(m.ChangeTask.change_id).where(m.ChangeTask.task_id == filters[field])))
            else:
                column = getattr(model, field, None)
                if column is None:
                    column = model.payload[field].as_string()
                query = query.where(column == filters[field])
    date_field = {'logs': 'work_date', 'changes': 'change_date', 'risks': 'raised_date', 'tasks': 'plan_start', 'communications': 'occurred_at', 'configurations': 'config_date', 'costs': 'expense_date', 'research': 'research_date', 'coding': 'work_date'}[kind]
    if filters.get('start'):
        query = query.where(getattr(model, 'plan_end' if kind == 'tasks' else date_field) >= filters['start'])
    if filters.get('end'):
        end = filters['end'] + ' 23:59:59' if kind == 'communications' else filters['end']
        query = query.where(getattr(model, date_field) <= end)
    if filters.get('q'):
        text_fields = {'tasks': ('planned_deliverable', 'actual_deliverable', 'notes', 'phase'),
                       'logs': ('content', 'details', 'next_plan', 'notes'),
                       'changes': ('title', 'content', 'original', 'change_reason', 'source', 'impact', 'notes'),
                       'risks': ('description', 'response', 'notes'),
                       'communications': ('subject', 'location', 'summary', 'details'),
                       'configurations': ('config_info', 'notes'), 'coding': ('feature', 'work_content', 'extra_time_notes'), 'costs': ('notes',), 'research': ('requirement', 'integration_system', 'solution', 'notes', 'development_notes')}[kind]
        query = query.where(or_(*[model.payload[field].as_string().contains(filters['q'], autoescape=True) for field in text_fields],
                               model.code.contains(filters['q'], autoescape=True),
                               model.name.contains(filters['q'], autoescape=True) if kind == 'tasks' else False,
                               model.config_name.contains(filters['q'], autoescape=True) if kind == 'configurations' else False,
                               model.feature.contains(filters['q'], autoescape=True) if kind == 'coding' else False))
    date_column = getattr(model, date_field)
    # All dated lists (and log exports) sort oldest first before pagination.
    # Unknown legacy expense dates belong after dated records.
    if kind == 'research':
        return query.order_by(model.sequence.asc(), date_column.asc(), model.created_at.asc(), model.id)
    return query.order_by(date_column.asc().nulls_last(), model.created_at.asc(), model.id)


def list_business(session, pid, kind, page=1, size=20, **filters):
    query = business_query(session, pid, kind, **filters)
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    query = query.offset((page-1)*size).limit(size)
    return {'items': [serialize(session, x) for x in session.scalars(query)], 'total': total, 'page': page, 'size': size}


def progress_percent(plans):
    """Inclusive planned days, including canceled tasks; round half up."""
    durations = [((date.fromisoformat(end) - date.fromisoformat(start)).days + 1, status)
                 for start, end, status in plans]
    planned = sum(days for days, _ in durations)
    completed = sum(days for days, status in durations if status == '已完成')
    return (completed * 200 + planned) // (2 * planned) if planned else 0


def money_string(cents):
    return f'{cents // 100}.{cents % 100:02d}'


def metrics(session, pid=None):
    query = select(m.Task).where(m.Task.deleted == False)
    risks = select(m.Risk).where(m.Risk.deleted == False, m.Risk.status != '已关闭')
    changes = select(m.Change).where(m.Change.deleted == False)
    costs = select(m.Cost.amount_cents).where(m.Cost.deleted == False)
    unlaunched_interfaces = business_query(session, pid, 'research', is_interface=True, status_ne='上线')
    coding_query = business_query(session, pid, 'coding').order_by(None).with_only_columns(m.CodingWork.duration_minutes)
    coding_minutes = int(session.scalar(select(func.coalesce(func.sum(coding_query.subquery().c.duration_minutes), 0))))
    if pid:
        query, risks, changes = query.where(m.Task.project_id == pid), risks.where(m.Risk.project_id == pid), changes.where(m.Change.project_id == pid)
        costs = costs.where(m.Cost.project_id == pid)
    else:
        query = query.join(m.Project).where(m.Project.archived == False)
        risks = risks.join(m.Project).where(m.Project.archived == False)
        changes = changes.join(m.Project).where(m.Project.archived == False)
        costs = costs.join(m.Project).where(m.Project.archived == False)
    tasks = list(session.scalars(query))
    valid = [t for t in tasks if t.status != '已取消']
    complete = sum(t.status == '已完成' for t in valid)
    project_progress = progress_percent((t.plan_start, t.plan_end, t.status) for t in tasks)
    return {'total': len(tasks), 'completed': complete, 'valid': len(valid),
            'project_progress': project_progress,
            'coding_minutes': coding_minutes, 'coding_hours': coding_minutes // 60,
            'direct_cost': money_string(sum(session.scalars(costs))),
            'not_started': sum(t.status == '未开始' for t in tasks),
            'unlaunched_interfaces': session.scalar(select(func.count()).select_from(unlaunched_interfaces.order_by(None).subquery())),
            'overdue': sum(t.status not in ('已完成', '已取消') and t.plan_end < today() for t in tasks),
            'risks': session.scalar(select(func.count()).select_from(risks.subquery())),
            'changes': session.scalar(select(func.count()).select_from(changes.subquery())),
            'completion_rate': round(complete / len(valid) * 100, 1) if valid else None}
