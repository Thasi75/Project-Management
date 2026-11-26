from uuid import uuid4
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, JSON, ForeignKey, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, Index
from .db import Base
from .config import now


def uid():
    return uuid4().hex


class Versioned:
    id = Column(String, primary_key=True, default=uid)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False, default=now)
    updated_at = Column(String, nullable=False, default=now)


class Person(Versioned, Base):
    __tablename__ = 'people'
    name = Column(String, nullable=False)
    team = Column(String, nullable=False, default='')
    notes = Column(String, nullable=False, default='')
    enabled = Column(Boolean, nullable=False, default=True)


class Project(Versioned, Base):
    __tablename__ = 'projects'
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    archived = Column(Boolean, nullable=False, default=False)
    payload = Column(JSON, nullable=False)


class Member(Base):
    __tablename__ = 'project_members'
    project_id = Column(String, ForeignKey('projects.id'), primary_key=True)
    person_id = Column(String, ForeignKey('people.id'), primary_key=True)
    # Profiles belong to a project; the legacy person ID only preserves historical links.
    name = Column(String, nullable=False)
    team = Column(String, nullable=False, default='')
    notes = Column(String, nullable=False, default='')
    enabled = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False, default=now)
    updated_at = Column(String, nullable=False, default=now)


class Module(Versioned, Base):
    __tablename__ = 'project_modules'
    project_id = Column(String, ForeignKey('projects.id'), nullable=False, index=True)
    name = Column(String, nullable=False)
    sort = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),)


class Scope(Base):
    __tablename__ = 'project_scope_versions'
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(String, ForeignKey('projects.id'), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    effective_date = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=now)
    reason = Column(String, nullable=False)
    change_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint('project_id', 'number'), UniqueConstraint('id', 'project_id'),
                      ForeignKeyConstraint(['change_id', 'project_id'], ['requirement_changes.id', 'requirement_changes.project_id']))


class Business(Versioned):
    project_id = Column(String, ForeignKey('projects.id'), nullable=False, index=True)
    code = Column(String, nullable=False, unique=True)
    deleted = Column(Boolean, nullable=False, default=False)
    payload = Column(JSON, nullable=False)


class Task(Business, Base):
    __tablename__ = 'tasks'
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    plan_start = Column(String, nullable=False)
    plan_end = Column(String, nullable=False, index=True)
    owner_id = Column(String, nullable=False)
    module_id = Column(String, nullable=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                      ForeignKeyConstraint(['owner_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                      ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']))


class WorkLog(Business, Base):
    __tablename__ = 'work_logs'
    work_date = Column(String, nullable=False, index=True)
    module_id = Column(String, nullable=True)
    owner_id = Column(String, nullable=False)
    task_id = Column(String, nullable=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                      ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']),
                      ForeignKeyConstraint(['owner_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                      ForeignKeyConstraint(['task_id', 'project_id'], ['tasks.id', 'tasks.project_id']))


class Communication(Business, Base):
    __tablename__ = 'communications'
    occurred_at = Column(String, nullable=False, index=True)
    host_id = Column(String, nullable=False)
    recorder_id = Column(String, nullable=False)
    log_id = Column(String, nullable=False, unique=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                     ForeignKeyConstraint(['host_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                     ForeignKeyConstraint(['recorder_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                     ForeignKeyConstraint(['log_id', 'project_id'], ['work_logs.id', 'work_logs.project_id']))


class Research(Business, Base):
    __tablename__ = 'requirement_research'
    sequence = Column(Integer, nullable=False, index=True)
    research_date = Column(String, nullable=False, index=True)
    module_id = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    recorder_id = Column(String, nullable=False)
    importance = Column(String, nullable=False)
    responded = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                     ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']),
                     ForeignKeyConstraint(['source_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                     ForeignKeyConstraint(['recorder_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
                     CheckConstraint('sequence >= 1 AND sequence <= 2147483647', name='ck_research_sequence'),
                     CheckConstraint("importance IN ('高','中','低')", name='ck_research_importance'),
                     CheckConstraint("responded IN ('是','否')", name='ck_research_responded'),
                     CheckConstraint("status IN ('设计','开发','上线')", name='ck_research_status'))


class Configuration(Business, Base):
    __tablename__ = 'project_configurations'
    config_name = Column(String, nullable=False)
    config_date = Column(String, nullable=False, index=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),)


class Cost(Business, Base):
    __tablename__ = 'project_costs'
    expense_date = Column(String, nullable=True, index=True)
    expense_item = Column(String, nullable=False, index=True)
    amount_cents = Column(BigInteger, nullable=False)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                     CheckConstraint('amount_cents >= 0 AND amount_cents <= 9999999999999999', name='ck_cost_amount'),
                     CheckConstraint("expense_item IN ('省际交通费','市内交通费','住宿费','业务招待费','Token','其他')", name='ck_cost_expense_item'))


class Change(Business, Base):
    __tablename__ = 'requirement_changes'
    change_date = Column(String, nullable=False, index=True)
    module_id = Column(String, nullable=True)
    scope_id = Column(String, nullable=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                      ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']),
                      ForeignKeyConstraint(['scope_id', 'project_id'], ['project_scope_versions.id', 'project_scope_versions.project_id']))


class Risk(Business, Base):
    __tablename__ = 'risks'
    status = Column(String, nullable=False, index=True)
    raised_date = Column(String, nullable=False, index=True)
    task_id = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    __table_args__ = (UniqueConstraint('id', 'project_id'),
                      ForeignKeyConstraint(['task_id', 'project_id'], ['tasks.id', 'tasks.project_id']),
                      ForeignKeyConstraint(['owner_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']))


class Participant(Base):
    __tablename__ = 'participants'
    kind = Column(String, primary_key=True)
    entity_id = Column(String, primary_key=True)
    person_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    __table_args__ = (ForeignKeyConstraint(['person_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),)


class ChangeTask(Base):
    __tablename__ = 'change_task_links'
    change_id = Column(String, primary_key=True)
    task_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    __table_args__ = (ForeignKeyConstraint(['task_id', 'project_id'], ['tasks.id', 'tasks.project_id']),
                      ForeignKeyConstraint(['change_id', 'project_id'], ['requirement_changes.id', 'requirement_changes.project_id']))


class Attachment(Versioned, Base):
    __tablename__ = 'attachments'
    project_id = Column(String, ForeignKey('projects.id'), nullable=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False, unique=True)
    size = Column(Integer, nullable=False)
    mime = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    description = Column(String, nullable=False, default='')
    removed = Column(Boolean, nullable=False, default=False)
    is_acceptance = Column(Boolean, nullable=False, default=False, server_default='0')
    __table_args__ = (UniqueConstraint('id', 'project_id'),)


class AttachmentLink(Base):
    __tablename__ = 'attachment_links'
    attachment_id = Column(String, primary_key=True)
    kind = Column(String, primary_key=True)
    entity_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    __table_args__ = (ForeignKeyConstraint(['attachment_id', 'project_id'], ['attachments.id', 'attachments.project_id']),)


class Revision(Base):
    __tablename__ = 'entity_revisions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey('projects.id'), nullable=False)
    kind = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    effective_date = Column(String, nullable=False)
    recorded_at = Column(String, nullable=False, default=now)
    reason = Column(String, nullable=False)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=False)
    patch = Column(JSON, nullable=False)
    __table_args__ = (Index('ix_revision_history', 'project_id', 'kind', 'entity_id', 'effective_date'),)


class Idempotency(Base):
    __tablename__ = 'idempotency_keys'
    key = Column(String, primary_key=True)
    fingerprint = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)


class Brief(Versioned, Base):
    __tablename__ = 'briefs'
    project_id = Column(String, ForeignKey('projects.id'), nullable=False, index=True)
    start = Column(String, nullable=False)
    end = Column(String, nullable=False)
    title = Column(String, nullable=False)


class BriefVersion(Base):
    __tablename__ = 'brief_versions'
    id = Column(String, primary_key=True, default=uid)
    brief_id = Column(String, ForeignKey('briefs.id'), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False, default=now)
    snapshot = Column(JSON, nullable=False)
    content = Column(JSON, nullable=False)
    model = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False, default='brief-v1')
    source = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('brief_id', 'number'),)


class Job(Versioned, Base):
    __tablename__ = 'generation_jobs'
    project_id = Column(String, ForeignKey('projects.id'), nullable=False, index=True)
    brief_id = Column(String, ForeignKey('briefs.id'), nullable=False)
    status = Column(String, nullable=False)
    error = Column(String, nullable=False, default='')
    retryable = Column(Boolean, nullable=False, default=True)
    attempts = Column(Integer, nullable=False, default=1)
    model = Column(String, nullable=False)
    snapshot = Column(JSON, nullable=False)
    result_id = Column(String, ForeignKey('brief_versions.id'), nullable=True)
