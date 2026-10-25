from dataclasses import dataclass,field
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv, dotenv_values
from .usage_limits import UsageLimits

ROOT = Path(__file__).resolve().parent.parent


def load_environment(path):
    values=dotenv_values(path)
    load_dotenv(path)
    # Desktop launchers can inherit an old key from their parent process. The
    # explicitly maintained local .env owns this credential. Production keeps
    # injected environment precedence; other settings retain their old behavior.
    if os.getenv('APP_ENV','local')=='local' and 'MIMO_API_KEY' in values:
        os.environ['MIMO_API_KEY']=values['MIMO_API_KEY'] or ''


load_environment(ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path
    origin: str = "http://127.0.0.1:8765"
    production: bool = False
    ai_base_url: str = "https://api.xiaomimimo.com/v1"
    ai_model: str = "mimo-v2.6-pro"
    ai_api_key: str = ""
    ai_timeout: int = 180
    ai_daily_limit: int = 1000
    qq_bot_app_id: str = ''
    qq_bot_secret: str = ''
    wechat_publisher_app_id: str = ''
    wechat_publisher_secret: str = ''
    genui_enabled: bool = True
    genui_debug: bool = False
    genui_ai_label: str = 'AI 生成内容'
    genui_tier: str = 'auto'
    ai_supports_json: bool = True
    ai_supports_tools: bool = False
    ai_context_tokens: int = 1000000
    genui_limits: dict = field(default_factory=dict)
    asr_model: str = 'mimo-v2.5-asr'
    tts_model: str = 'mimo-v2.5-tts'
    voice_design_model: str = 'mimo-v2.5-tts-voicedesign'
    voice_clone_model: str = 'mimo-v2.5-tts-voiceclone'
    tts_voice: str = 'mimo_default'
    ai_grounding: bool = True
    ai_summary_model: str = 'mimo-v2.6-flash'
    ai_composition_model: str = 'mimo-v2.6-pro'
    ai_output_tokens: int = 131072
    ai_workflow_timeout: int = 1800
    registration_mode: str = 'public'
    notice_input_tokens: int = 868928
    ai_stage_summaries: bool = False
    notice_semantic_review: bool = True
    notice_review_model: str = 'mimo-v2.6-flash'
    notice_fast_enabled: bool = False
    agent_enabled: bool = True
    agent_context_bytes: int = 2000000
    agent_oss_url: str = 'http://127.0.0.1:11434/v1'
    agent_oss_model: str = ''
    agent_oss_context_tokens: int = 32768
    agent_sandbox_image: str = ''
    agent_mcp_servers: dict = field(default_factory=dict)
    # 声音复刻默认关闭，需要部署方建立被复刻人书面授权流程后再开启。
    voice_clone_enabled: bool = False
    # 隐私政策中展示的运营者与联系方式，部署时在 .env 中填写。
    usage_limits: UsageLimits = field(default_factory=UsageLimits)
    operator_name: str = '珞珈信使项目团队'
    operator_contact: str = ''

    @classmethod
    def from_env(cls):
        data = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
        if not data.is_absolute():
            data = ROOT / data
        result = cls(data.resolve(), os.getenv("APP_ORIGIN", "http://127.0.0.1:8765").rstrip("/"),
                     os.getenv("APP_ENV", "local") == "production",
                     os.getenv("MIMO_BASE_URL", cls.ai_base_url).strip().rstrip("/"),
                     os.getenv("MIMO_TEXT_MODEL", cls.ai_model).strip(), os.getenv("MIMO_API_KEY", "").strip(),
                     int(os.getenv("AI_TIMEOUT_SECONDS", "180")), int(os.getenv("AI_DAILY_LIMIT", "1000")))
        result.usage_limits=UsageLimits.parse(os.getenv('USAGE_LIMITS_JSON','{}'))
        result.registration_mode=os.getenv('REGISTRATION_MODE','public').strip().lower()
        result.operator_name=os.getenv('OPERATOR_NAME',cls.operator_name).strip()[:80] or cls.operator_name
        result.operator_contact=os.getenv('OPERATOR_CONTACT','').strip()[:120]
        result.voice_clone_enabled=os.getenv('VOICE_CLONE_ENABLED','false').strip().lower() in {'true','1','yes'}
        result.agent_enabled=os.getenv('AGENT_ENABLED','true').strip().lower() in {'true','1','yes'}
        result.agent_context_bytes=int(os.getenv('AGENT_CONTEXT_BYTES',str(cls.agent_context_bytes)))
        if not 24000 <= result.agent_context_bytes <= 2000000:
            raise ValueError('AGENT_CONTEXT_BYTES 须为 24000—2000000')
        from .agent_runtime.providers import loopback_url
        from .agent_runtime.mcp import validate_servers
        result.agent_oss_url=loopback_url(os.getenv('AGENT_OSS_URL',cls.agent_oss_url).strip())
        result.agent_oss_model=os.getenv('AGENT_OSS_MODEL','').strip()
        result.agent_oss_context_tokens=int(os.getenv('AGENT_OSS_CONTEXT_TOKENS','32768'))
        if not 8192 <= result.agent_oss_context_tokens <= 1000000:
            raise ValueError('AGENT_OSS_CONTEXT_TOKENS 须为 8192—1000000，且不能超过本地服务实际配置')
        result.agent_sandbox_image=os.getenv('AGENT_SANDBOX_IMAGE','').strip()
        result.agent_mcp_servers=validate_servers(json.loads(os.getenv('AGENT_MCP_SERVERS_JSON','{}')))
        if result.registration_mode not in {'public','invite'}:
            raise ValueError('REGISTRATION_MODE 须为 public 或 invite')
        result.notice_input_tokens=int(os.getenv('NOTICE_INPUT_TOKENS',str(cls.notice_input_tokens)))
        result.notice_semantic_review=os.getenv('NOTICE_SEMANTIC_REVIEW','true').lower() in {'true','1','yes'}
        result.notice_review_model=os.getenv('MIMO_NOTICE_REVIEW_MODEL',cls.notice_review_model).strip()
        fast_option=os.getenv('NOTICE_FAST_ENABLED','false').strip().lower()
        if fast_option not in {'true','false','1','0','yes','no'}:raise ValueError('NOTICE_FAST_ENABLED 须为 true 或 false')
        result.notice_fast_enabled=fast_option in {'true','1','yes'}
        if not 4096 <= result.notice_input_tokens <= 900000:
            raise ValueError('NOTICE_INPUT_TOKENS 须为 4096—900000')
        parsed = urlparse(result.origin)
        for attr, key in [('asr_model','MIMO_ASR_MODEL'),('tts_model','MIMO_TTS_MODEL'),
                          ('voice_design_model','MIMO_VOICE_DESIGN_MODEL'),('voice_clone_model','MIMO_VOICE_CLONE_MODEL'),
                          ('tts_voice','MIMO_TTS_VOICE')]:
            setattr(result,attr,os.getenv(key,getattr(cls,attr)).strip())
        if result.tts_voice not in {'mimo_default','冰糖','茉莉','苏打','白桦','Mia','Chloe','Milo','Dean'}:
            raise ValueError('MIMO_TTS_VOICE 必须是小米官方预置音色')
        result.qq_bot_app_id=os.getenv('QQ_BOT_APP_ID','').strip()
        result.qq_bot_secret=os.getenv('QQ_BOT_SECRET','').strip()
        result.wechat_publisher_app_id=os.getenv('WECHAT_PUBLISHER_APP_ID','').strip()
        result.wechat_publisher_secret=os.getenv('WECHAT_PUBLISHER_SECRET','').strip()
        result.genui_enabled=os.getenv('GENUI_ENABLED','true').lower() in {'true','1','yes'}
        result.genui_debug=os.getenv('GENUI_DEBUG','false').lower() in {'true','1','yes'}
        result.genui_ai_label=os.getenv('GENUI_AI_LABEL','AI 生成内容')[:60]
        result.genui_tier=os.getenv('GENUI_TIER','auto').lower()
        result.ai_supports_json=os.getenv('AI_SUPPORTS_JSON','true').lower() in {'true','1','yes'}
        result.ai_supports_tools=os.getenv('AI_SUPPORTS_TOOLS','false').lower() in {'true','1','yes'}
        result.ai_grounding=os.getenv('AI_GROUNDING','true').lower() in {'true','1','yes'}
        result.ai_stage_summaries=os.getenv('AI_STAGE_SUMMARIES','false').lower() in {'true','1','yes'}
        result.ai_summary_model=os.getenv('MIMO_SUMMARY_MODEL',cls.ai_summary_model).strip()
        result.ai_composition_model=os.getenv('MIMO_COMPOSITION_MODEL',cls.ai_composition_model).strip()
        result.ai_context_tokens=int(os.getenv('AI_CONTEXT_TOKENS',str(cls.ai_context_tokens)))
        result.ai_output_tokens=int(os.getenv('AI_OUTPUT_TOKENS',str(cls.ai_output_tokens)))
        result.ai_workflow_timeout=int(os.getenv('AI_WORKFLOW_TIMEOUT_SECONDS','1800'))
        if not 4096<=result.ai_output_tokens<=131072 or not 60<=result.ai_workflow_timeout<=1800:
            raise ValueError('AI_OUTPUT_TOKENS 须为 4096—131072，AI_WORKFLOW_TIMEOUT_SECONDS 须为 60—1800')
        if result.genui_tier not in {'auto','1','2','3'} or not 2048<=result.ai_context_tokens<=1000000:
            raise ValueError('GENUI_TIER 或 AI_CONTEXT_TOKENS 配置无效')
        from .genui import LIMITS
        result.genui_limits=json.loads(os.getenv('GENUI_LIMITS_JSON','{}'))
        if not isinstance(result.genui_limits,dict) or any(k not in LIMITS or type(v) is not int or not 1<=v<=LIMITS[k] for k,v in result.genui_limits.items()):
            raise ValueError('GENUI_LIMITS_JSON 只能设置已知上限，范围为 1 至目录默认值')
        if not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("APP_ORIGIN 必须是完整源地址，不能包含路径")
        if result.production and parsed.scheme != "https":
            raise ValueError("生产模式要求 HTTPS APP_ORIGIN")
        if not result.production and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("对外提供服务须使用 production 模式及 HTTPS")
        from .model_catalog import validate
        validate(result)
        if not 10 <= result.ai_timeout <= 180 or not 1 <= result.ai_daily_limit <= 10000:
            raise ValueError('AI 超时须为 10—180 秒，每账号每日上限须为 1—10000 次')
        return result
