from typing import Literal

from pydantic import Field

from ..models import Strict


class AgentError(Exception):
    """A safe, user-facing execution error; never include raw provider errors."""


class NewThread(Strict):
    title: str = Field(default='智能任务', min_length=1, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=64)
    provider: Literal['mimo', 'oss'] = 'mimo'
    scopes: list[Literal['library', 'schedule', 'memory']] = Field(default_factory=list, max_length=3)
    skills: list[str] = Field(default_factory=list, max_length=5)
    approval_policy: Literal['ask', 'deny'] = 'ask'


class StartTurn(Strict):
    prompt: str = Field(min_length=1, max_length=16000)
    request_id: str = Field(min_length=16, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    allow_external_processing: bool = False


class ApprovalDecision(Strict):
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: Literal['approve', 'deny']


class Query(Strict):
    query: str = Field(min_length=1, max_length=500)


class ReadFile(Strict):
    path: str = Field(min_length=1, max_length=240)


class WriteFile(ReadFile):
    content: str = Field(max_length=32000)
    expected_sha256: str = Field(default='', pattern=r'^$|^[0-9a-f]{64}$')


class Command(Strict):
    argv: list[str] = Field(min_length=1, max_length=40)


class LoadSkill(Strict):
    name: str = Field(min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9-]*$')


class Spawn(Strict):
    task: str = Field(min_length=1, max_length=6000)
    name: str = Field(min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_-]*$')


class AgentTarget(Strict):
    agent_id: str = Field(pattern=r'^[0-9a-f]{32}$')


class MessageAgent(AgentTarget):
    message: str = Field(min_length=1, max_length=3000)


class WaitAgents(Strict):
    agent_ids: list[str] = Field(min_length=1, max_length=3)
    timeout_seconds: int = Field(default=20, ge=0, le=30)


class Empty(Strict):
    pass


class MCPCall(Strict):
    server: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict = Field(default_factory=dict)


class MCPList(Strict):
    server: str = Field(min_length=1, max_length=64)
