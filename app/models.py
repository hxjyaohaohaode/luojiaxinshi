from datetime import date, datetime, time
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Strict):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_.@+-]+$')
    password: str = Field(min_length=1, max_length=128)


class Register(Login):
    invite: str = Field(default='', max_length=100)
    display_name: str = Field(min_length=1, max_length=40)
    account_kind: Literal['username','student_id','employee_id','phone'] = 'username'
    campus_role: Literal['student','teacher','staff','other'] = 'student'
    accepted_terms: bool = False

    @field_validator('password')
    @classmethod
    def strong_password(cls, value):
        if len(value) < 12:
            raise ValueError('密码至少 12 个字符')
        return value


class Profile(Strict):
    preferred_name: str = Field(default='', max_length=30)
    campus_area: str = Field(default='', max_length=80)
    interests: str = Field(default='', max_length=500)
    available_time: str = Field(default='', max_length=300)
    response_detail: Literal['concise','balanced','detailed'] = 'balanced'
    response_style: Literal['warm','direct','academic'] = 'warm'
    response_preferences: str = Field(default='', max_length=600)
    avatar_tone: Literal['forest','blue','plum','amber'] = 'forest'
    campus_role: Literal['student','teacher','staff','other'] = 'student'
    school: str = Field(default='武汉大学', max_length=80)
    student_id: str = Field(default='', max_length=40)
    employee_id: str = Field(default='', max_length=40)
    phone: str = Field(default='', max_length=30)
    wechat: str = Field(default='', max_length=40)
    qq: str = Field(default='', max_length=20)
    goals: str = Field(default='', max_length=1000)
    level: str = Field(default='', max_length=40)
    grade: str = Field(default='', max_length=40)
    college: str = Field(default='', max_length=80)
    major: str = Field(default='', max_length=80)
    semester: str = Field(default='', max_length=40)
    semester_start: str = Field(default='', max_length=10)
    week_starts_on: Literal[0,1] = 1

    @field_validator('semester_start')
    @classmethod
    def semester_date(cls, value):
        if value and (len(value) != 10 or date.fromisoformat(value).isoformat() != value or not 2000 <= date.fromisoformat(value).year <= 2100):
            raise ValueError('学期第一周日期须为 2000 至 2100 年之间的有效日期')
        return value


class ProfilePatch(Strict):
    changes: Profile
    expected: Profile

    @model_validator(mode='after')
    def same_fields(self):
        if self.changes.model_fields_set != self.expected.model_fields_set:
            raise ValueError('每项资料修改都需要对应的原值，请重新打开表单')
        return self


class Recover(Login):
    recovery_code: str = Field(min_length=20,max_length=100)

    @field_validator('password')
    @classmethod
    def strong_password(cls,value):
        if len(value)<12:
            raise ValueError('密码至少 12 个字符')
        return value


class Evidence(Strict):
    source_id: str = Field(min_length=1, max_length=40)
    locator: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=1600)


class Fact(Strict):
    value: str = Field(default='', max_length=2000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)


class DraftPlan(Strict):
    action_kind: Literal['unclassified','required','optional','verification'] = 'unclassified'
    depends_on: list[int] = Field(default_factory=list,max_length=30)
    conditions: list[str] = Field(default_factory=list,max_length=8)

    @field_validator('depends_on',mode='before')
    @classmethod
    def valid_indexes(cls,value):
        if not isinstance(value,list) or any(type(i) is not int or not 0<=i<30 for i in value):
            raise ValueError('前置步骤须为有效的步骤序号')
        return list(dict.fromkeys(value))

    @field_validator('conditions')
    @classmethod
    def bounded_conditions(cls,value):
        if any(not 2<=len(item.strip())<=400 for item in value):raise ValueError('每项外部条件须为 2 至 400 字')
        return list(dict.fromkeys(item.strip() for item in value))


class ConfirmPlan(DraftPlan):
    participation: Literal['undecided','joined','declined'] = 'undecided'
    workflow_version: int | None = Field(default=None,ge=0)


class ActionCondition(Strict):
    id: str = Field(min_length=1,max_length=60,pattern=r'^[a-zA-Z0-9_.:-]+$')
    text: str = Field(min_length=2,max_length=400)
    state: Literal['unknown','met','not_met'] = 'unknown'
    note: str = Field(default='',max_length=1500)

    @model_validator(mode='after')
    def needs_verification_note(self):
        if self.state!='unknown' and len(self.note)<2:raise ValueError('核实条件时请记录实际依据')
        return self


class TaskData(Strict):
    title: str = Field(min_length=1, max_length=160)
    details: str = Field(default='', max_length=3000)
    scope: Literal['personal','other','uncertain'] = 'personal'
    due_date: str | None = None
    due_time: str | None = None
    deadline_text: str = Field(default='', max_length=500)
    planned_at: str | None = None
    reminder_at: str | None = None
    deadline_confirmed: bool = False
    materials: list[str] = Field(default_factory=list, max_length=30)
    submission: str = Field(default='', max_length=1000)
    location: str = Field(default='', max_length=500)
    contact: str = Field(default='', max_length=500)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
    deadline_evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    resolution_note: str = Field(default='', max_length=1500)
    notes: str = Field(default='', max_length=3000)
    origin: Literal['ai','manual'] = 'manual'

    @field_validator('due_date')
    @classmethod
    def valid_date(cls, v):
        if v is not None and (len(v) != 10 or date.fromisoformat(v).isoformat() != v):
            raise ValueError('日期须为 YYYY-MM-DD')
        return v

    @field_validator('due_time')
    @classmethod
    def valid_time(cls, v):
        if v is not None and (len(v) != 5 or time.fromisoformat(v).strftime('%H:%M') != v):
            raise ValueError('时刻须为 HH:MM')
        return v

    @field_validator('planned_at','reminder_at')
    @classmethod
    def valid_datetime(cls, v):
        if v is not None:
            parsed = datetime.fromisoformat(v)
            if parsed.tzinfo is None:
                raise ValueError('时间必须包含时区')
            return parsed.isoformat(timespec='seconds')
        return v

    @field_validator('materials','uncertainties')
    @classmethod
    def bounded_items(cls, v):
        if any(len(s)>500 for s in v):
            raise ValueError('单项内容不能超过 500 字')
        return v

    @model_validator(mode='after')
    def dates_match(self):
        if self.due_time and not self.due_date:
            raise ValueError('截止时刻必须同时指定日期')
        return self


class Extraction(Strict):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(max_length=1500)
    applicability: Literal['matches_known','not_matching','needs_review']
    applicability_reason: str = Field(max_length=2000)
    facts: dict[str, Fact]
    tasks: list[TaskData] = Field(max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    plans: dict[int,DraftPlan] = Field(default_factory=dict,max_length=30)


DraftIndex = Annotated[int, Field(strict=True, ge=0, le=29)]


class IssueResolution(Strict):
    issue_index: int = Field(strict=True, ge=0, le=23)
    action: Literal['changed','excluded','acknowledged','disagreed']
    note: str = Field(default='',max_length=700)
    task_indices: list[DraftIndex] = Field(default_factory=list,max_length=30)


class ReviewObservation(Strict):
    """Untrusted browser observation, never an end-to-end or verified study time."""
    method: Literal['visible_idle_60s_v1']
    active_ms: int = Field(strict=True,ge=0,le=28_800_000)
    editing_ms: int = Field(strict=True,ge=0,le=28_800_000)

    @model_validator(mode='after')
    def editing_is_part_of_review(self):
        if self.editing_ms>self.active_ms:
            raise ValueError('编辑区活跃时间不能超过页面活跃时间')
        return self


class Confirm(Strict):
    version: int = Field(ge=1)
    tasks: list[TaskData] = Field(min_length=1, max_length=30)
    reviewed: Literal[True]
    replacements: dict[int, str] = Field(default_factory=dict)
    target_versions: dict[str, int] = Field(default_factory=dict)
    plans: dict[int,ConfirmPlan] = Field(default_factory=dict,max_length=30)
    quality_resolution: str = Field(default='',max_length=2000)
    source_indices: list[DraftIndex | None] = Field(default_factory=list,max_length=30)
    issue_resolutions: list[IssueResolution] = Field(default_factory=list,max_length=24)
    manual_quality_reviewed: bool = Field(default=False,strict=True)
    review_observation: ReviewObservation | None = None


class Version(Strict):
    version: int = Field(ge=1)


class Generate(Version):
    allow_external_processing: Literal[True]
    processing_mode: Literal['configured','fast'] = 'configured'


class TaskUpdate(Version):
    data: TaskData
    status: Literal['pending','done','cancelled']
    reason: str = Field(min_length=1, max_length=500)


class PasswordChange(Strict):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class CalendarRequest(Strict):
    task_ids: list[str] = Field(min_length=1,max_length=100)
    versions: dict[str,int]


class EditCache(Strict):
    revision: int = Field(ge=0)
    payload: dict | None


def safe_url(value):
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or len(value)>2000:
        raise ValueError('来源链接须是有效的 http(s) 地址')
    return value
