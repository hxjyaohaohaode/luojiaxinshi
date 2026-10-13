from dataclasses import dataclass
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
    ai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen3.8-flash"
    ai_api_key: str = ""
    ai_timeout: int = 90
    ai_daily_limit: int = 30
    qq_bot_app_id: str = ''
    qq_bot_secret: str = ''
    wechat_publisher_app_id: str = ''
    wechat_publisher_secret: str = ''

    @classmethod
    def from_env(cls):
        data = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
        if not data.is_absolute():
            data = ROOT / data
        result = cls(data.resolve(), os.getenv("APP_ORIGIN", "http://127.0.0.1:8765").rstrip("/"),
                     os.getenv("APP_ENV", "local") == "production",
                     os.getenv("AI_BASE_URL", cls.ai_base_url).rstrip("/"),
                     os.getenv("AI_MODEL", cls.ai_model), os.getenv("AI_API_KEY", ""),
                     int(os.getenv("AI_TIMEOUT_SECONDS", "90")), int(os.getenv("AI_DAILY_LIMIT", "30")))
        parsed = urlparse(result.origin)
        result.qq_bot_app_id=os.getenv('QQ_BOT_APP_ID','').strip()
        result.qq_bot_secret=os.getenv('QQ_BOT_SECRET','').strip()
        result.wechat_publisher_app_id=os.getenv('WECHAT_PUBLISHER_APP_ID','').strip()
        result.wechat_publisher_secret=os.getenv('WECHAT_PUBLISHER_SECRET','').strip()
        if not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("APP_ORIGIN 必须是完整源地址，不能包含路径")
        if result.production and parsed.scheme != "https":
            raise ValueError("生产模式要求 HTTPS APP_ORIGIN")
        if not result.production and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("对外提供服务须使用 production 模式及 HTTPS")
        ai_url=urlparse(result.ai_base_url)
        if ai_url.scheme != "https" or not ai_url.hostname or ai_url.username or ai_url.password or ai_url.query or ai_url.fragment:
            raise ValueError("AI_BASE_URL 必须使用 HTTPS")
        if not 10 <= result.ai_timeout <= 180 or not 1 <= result.ai_daily_limit <= 1000:
            raise ValueError('AI 超时须为 10—180 秒，每账号每日上限须为 1—1000 次')
        return result
