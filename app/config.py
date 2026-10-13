from dataclasses import dataclass,field
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path
    origin: str = "http://127.0.0.1:8765"
    production: bool = False
    ai_base_url: str = "https://api.xiaomimimo.com/v1"
    ai_model: str = "mimo-v2.6-pro"
    ai_api_key: str = ""
    ai_timeout: int = 90
    ai_daily_limit: int = 30
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
    ai_context_tokens: int = 32768
    genui_limits: dict = field(default_factory=dict)
    asr_model: str = 'mimo-v2.5-asr'
    tts_model: str = 'mimo-v2.5-tts'
    voice_design_model: str = 'mimo-v2.5-tts-voicedesign'
    voice_clone_model: str = 'mimo-v2.5-tts-voiceclone'
    tts_voice: str = 'mimo_default'

    @classmethod
    def from_env(cls):
        data = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
        if not data.is_absolute():
            data = ROOT / data
        result = cls(data.resolve(), os.getenv("APP_ORIGIN", "http://127.0.0.1:8765").rstrip("/"),
                     os.getenv("APP_ENV", "local") == "production",
                     os.getenv("MIMO_BASE_URL", cls.ai_base_url).strip().rstrip("/"),
                     os.getenv("MIMO_TEXT_MODEL", cls.ai_model).strip(), os.getenv("MIMO_API_KEY", "").strip(),
                     int(os.getenv("AI_TIMEOUT_SECONDS", "90")), int(os.getenv("AI_DAILY_LIMIT", "30")))
        parsed = urlparse(result.origin)
        for attr, key in [('asr_model','MIMO_ASR_MODEL'),('tts_model','MIMO_TTS_MODEL'),
                          ('voice_design_model','MIMO_VOICE_DESIGN_MODEL'),('voice_clone_model','MIMO_VOICE_CLONE_MODEL'),
                          ('tts_voice','MIMO_TTS_VOICE')]:
            setattr(result,attr,os.getenv(key,getattr(cls,attr)).strip())
        expected = {'ai_model':'mimo-v2.6-pro','asr_model':'mimo-v2.5-asr','tts_model':'mimo-v2.5-tts',
                    'voice_design_model':'mimo-v2.5-tts-voicedesign','voice_clone_model':'mimo-v2.5-tts-voiceclone'}
        if any(getattr(result,k)!=v for k,v in expected.items()):
            raise ValueError('MiMo 模型配置与当前适配器不匹配，请使用 .env.example 中的五个模型 ID')
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
        result.ai_context_tokens=int(os.getenv('AI_CONTEXT_TOKENS','32768'))
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
        ai_url=urlparse(result.ai_base_url)
        if (ai_url.scheme != "https" or ai_url.hostname != 'api.xiaomimimo.com' or ai_url.port not in {None,443}
                or ai_url.path != '/v1' or ai_url.username or ai_url.password or ai_url.query or ai_url.fragment):
            raise ValueError("MIMO_BASE_URL 须为小米按量 API 端点 https://api.xiaomimimo.com/v1")
        if not 10 <= result.ai_timeout <= 180 or not 1 <= result.ai_daily_limit <= 1000:
            raise ValueError('AI 超时须为 10—180 秒，每账号每日上限须为 1—1000 次')
        return result
