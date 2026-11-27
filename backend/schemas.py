from datetime import date, datetime
from decimal import Decimal
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AfterValidator, model_validator, field_validator
from .config import today


def nonblank_markdown(value):
    if not value.strip():
        raise ValueError('内容不能为空')
    return value


# Markdown indentation and trailing newlines are meaningful; only single-line
# values keep the application's automatic whitespace trimming.
MarkdownText = Annotated[str, StringConstraints(strip_whitespace=False)]
RequiredMarkdown = Annotated[MarkdownText, AfterValidator(nonblank_markdown)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int | None = None


class PersonInput(Input):
    name: str = Field(min_length=1, max_length=120)
    team: str = ''
    notes: MarkdownText = ''
    enabled: bool = True


class ModuleInput(Input):
    name: str = Field(min_length=1, max_length=120)
    sort: int = 0
    enabled: bool = True


class BusinessInput(Input):
    effective_date: str = Field(default_factory=today)
    reason: MarkdownText = ''

    @model_validator(mode='after')
    def dates(self):
        for key, value in self.model_dump().items():
            if key.endswith('_date') or key in ('plan_start', 'plan_end', 'actual_start', 'actual_end'):
                if value:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError('日期必须采用 YYYY-MM-DD 格式')
                    if key not in ('plan_start', 'plan_end', 'change_date') and value > today():
                        raise ValueError('业务生效日、实际日期和工作日期不能晚于今天')
        for start, end in [('plan_start', 'plan_end'), ('actual_start', 'actual_end')]:
            a, b = getattr(self, start, None), getattr(self, end, None)
            if a and b and b < a:
                raise ValueError('结束日期不能早于开始日期')
        return self


class ProjectInput(BusinessInput):
    name: str = Field(min_length=1, max_length=200)
    customer: str = ''
    owner_id: str | None = None
    plan_start: str | None = None
    plan_end: str | None = None
    status: Literal['未开始', '进行中', '暂停', '已完成'] = '未开始'
    scope: RequiredMarkdown = Field(min_length=1)
    exclusions: MarkdownText = ''
    deliverables: MarkdownText = ''
    acceptance: MarkdownText = ''
    notes: MarkdownText = ''
    # Older clients may submit the unchanged list; membership is now maintained via project people.
    member_ids: list[str] | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    change_id: str | None = None


class TaskInput(BusinessInput):
    name: str = Field(min_length=1, max_length=200)
    phase: str = ''
    module_id: str | None = None
    plan_start: str
    plan_end: str
    planned_deliverable: RequiredMarkdown = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    participant_ids: list[str] = Field(default_factory=list)
    actual_start: str | None = None
    actual_end: str | None = None
    actual_deliverable: MarkdownText = ''
    delivery_url: str = ''
    attachment_ids: list[str] = Field(default_factory=list)
    status: Literal['未开始', '进行中', '暂停', '已完成', '已取消'] = '未开始'
    change_ids: list[str] = Field(default_factory=list)
    notes: MarkdownText = ''

    @model_validator(mode='after')
    def state(self):
        if self.status in ('进行中', '暂停', '已完成') and not self.actual_start:
            raise ValueError('执行中的任务必须填写实际开始日期')
        if self.status == '已完成' and (not self.actual_end or not self.actual_deliverable.strip()):
            raise ValueError('完成任务必须填写实际结束日期和实际交付物')
        if self.status != '已完成' and self.actual_end:
            raise ValueError('只有已完成任务可以填写实际结束日期')
        if self.status == '未开始' and self.actual_start:
            raise ValueError('未开始任务不能填写实际开始日期')
        if self.delivery_url and not self.delivery_url.startswith(('https://', 'http://')):
            raise ValueError('交付链接必须以 https:// 或 http:// 开头')
        return self


class LogInput(BusinessInput):
    work_date: str = Field(default_factory=today)
    module_id: str | None = None
    owner_id: str = Field(min_length=1)
    participant_ids: list[str] = Field(default_factory=list)
    content: RequiredMarkdown = Field(min_length=1)
    details: MarkdownText = ''
    next_plan: MarkdownText = ''
    notes: MarkdownText = ''
    task_id: str | None = None

    @field_validator('module_id', mode='before')
    @classmethod
    def empty_module(cls, value):
        return None if value == '' else value


class CommunicationInput(BusinessInput):
    occurred_at: str
    location: str = ''
    subject: str = Field(min_length=1, max_length=200)
    module_id: str = Field(min_length=1)
    participant_ids: list[str] = Field(default_factory=list)
    host_id: str = Field(min_length=1)
    recorder_id: str = Field(min_length=1)
    summary: RequiredMarkdown = Field(min_length=1)
    details: MarkdownText = ''
    summary_height: int | None = Field(default=None, ge=80)
    details_height: int | None = Field(default=None, ge=80)

    @model_validator(mode='after')
    def communication_time(self):
        try:
            parsed = datetime.strptime(self.occurred_at, '%Y-%m-%d %H:%M:%S')
            if parsed.strftime('%Y-%m-%d %H:%M:%S') != self.occurred_at:
                raise ValueError()
        except ValueError:
            raise ValueError('沟通时间必须采用 YYYY-MM-DD HH:MM:SS 格式')
        if self.occurred_at[:10] > today():
            raise ValueError('沟通日期不能晚于今天')
        return self


class ResearchInput(BusinessInput):
    sequence: int | None = Field(default=None, ge=1, le=2147483647, strict=True)
    research_date: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    requirement: RequiredMarkdown = Field(min_length=1)
    source_id: str = Field(min_length=1)
    recorder_id: str = Field(min_length=1)
    importance: Literal['高', '中', '低'] = '中'
    responded: Literal['是', '否'] = '是'
    status: Literal['设计', '开发', '上线'] = '设计'
    solution: RequiredMarkdown = Field(min_length=1)
    notes: MarkdownText = ''

    is_interface: bool = Field(default=False, strict=True)
    integration_system: str = ''
    go_live_date: str | None = None

    @model_validator(mode='after')
    def interface_system_required(self):
        if self.is_interface and not self.integration_system:
            raise ValueError('接口为是时必须填写对接系统')
        if self.is_interface and self.status == '上线' and not self.go_live_date:
            raise ValueError('接口状态为上线时必须填写上线日期')
        return self


class ExternalInterfaceInput(Input):
    version: int = Field(ge=1, strict=True)
    status: Literal['设计', '开发', '上线']
    development_notes: MarkdownText = ''
    go_live_date: str | None = None

    @model_validator(mode='after')
    def launch_date(self):
        if self.status == '上线' and not self.go_live_date:
            raise ValueError('状态为上线时必须填写上线日期')
        if self.go_live_date:
            if date.fromisoformat(self.go_live_date).isoformat() != self.go_live_date:
                raise ValueError('上线日期必须采用 YYYY-MM-DD 格式')
            if self.go_live_date > today():
                raise ValueError('上线日期不能晚于今天')
        return self


class CodingWorkInput(BusinessInput):
    work_date: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    feature: str = Field(min_length=1, max_length=200)
    work_content: RequiredMarkdown = Field(min_length=1)
    duration_minutes: int = Field(ge=1, le=2147483647, strict=True)
    extra_time_notes: MarkdownText = ''


class ConfigurationInput(BusinessInput):
    config_name: str = Field(min_length=1, max_length=200)
    config_info: RequiredMarkdown = Field(min_length=1)
    config_date: str = Field(min_length=1)
    notes: MarkdownText = ''


class CostInput(BusinessInput):
    expense_date: str = Field(min_length=1)
    expense_item: Literal['省际交通费', '市内交通费', '住宿费', '业务招待费', 'Token', '其他']
    amount: str
    notes: MarkdownText = ''

    @field_validator('amount', mode='before')
    @classmethod
    def money(cls, value):
        text = str(value).strip()
        if not re.fullmatch(r'[0-9]{1,14}(?:\.[0-9]{1,2})?', text):
            raise ValueError('金额须为非负数，最多14位整数和两位小数，单位元')
        return format(Decimal(text), '.2f')


class ChangeInput(BusinessInput):
    change_date: str = Field(default_factory=today)
    title: str = Field(min_length=1, max_length=200)
    content: RequiredMarkdown = Field(min_length=1)
    original: MarkdownText = ''
    change_reason: MarkdownText = ''
    source: str = ''
    module_id: str | None = None
    impact: MarkdownText = ''
    scope_id: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)
    notes: MarkdownText = ''


class RiskInput(BusinessInput):
    description: RequiredMarkdown = Field(min_length=1)
    level: Literal['低', '中', '高'] = '中'
    raised_date: str = Field(default_factory=today)
    owner_id: str | None = None
    task_id: str | None = None
    response: MarkdownText = ''
    status: Literal['待处理', '处理中', '已关闭'] = '待处理'
    closed_date: str | None = None
    notes: MarkdownText = ''

    @model_validator(mode='after')
    def state(self):
        if self.status == '已关闭' and not self.closed_date:
            raise ValueError('关闭风险必须填写关闭日期')
        if self.status != '已关闭' and self.closed_date:
            raise ValueError('未关闭风险不能填写关闭日期')
        if self.closed_date and self.closed_date < self.raised_date:
            raise ValueError('关闭日期不能早于提出日期')
        return self


class VersionInput(Input):
    version: int


class ArchiveInput(VersionInput):
    archived: bool


class RemoveInput(VersionInput):
    effective_date: str = Field(default_factory=today)
    reason: RequiredMarkdown = Field(min_length=1)


class AttachmentInput(VersionInput):
    description: MarkdownText = ''
    removed: bool = False


class AttachmentAcceptanceInput(VersionInput):
    is_acceptance: bool


class ReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: str
    end: str
    brief_id: str | None = None

    @model_validator(mode='after')
    def dates(self):
        date.fromisoformat(self.start)
        date.fromisoformat(self.end)
        if self.start > self.end or self.end > today():
            raise ValueError('报告开始日不得晚于结束日，结束日不得晚于今天')
        return self


class Paragraph(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str
    source_ids: list[str]


class Section(BaseModel):
    model_config = ConfigDict(extra='forbid')
    heading: str
    paragraphs: list[Paragraph]


class ReportContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sections: list[Section]


class EditBriefInput(VersionInput):
    base_version_id: str
    content: ReportContent
