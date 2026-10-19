"""Verified MiMo model/endpoint capabilities, not a runtime guessing mechanism.

Last checked against Xiaomi's model and integration documentation: 2026-10-18.
Unknown models require an adapter review; credentials never enter this catalog.
"""
from urllib.parse import urlparse
from dataclasses import replace

VERIFIED_AT='2026-10-18'
PAYG='https://api.xiaomimimo.com/v1'
TOKEN_PLAN='https://token-plan-cn.xiaomimimo.com/v1'
TEXT_MODELS=frozenset({'mimo-v2.6-pro','mimo-v2.6-flash','mimo-v2.6-pro-ultraspeed'})
SPEECH_MODELS={
    'asr_model':'mimo-v2.5-asr','tts_model':'mimo-v2.5-tts',
    'voice_design_model':'mimo-v2.5-tts-voicedesign','voice_clone_model':'mimo-v2.5-tts-voiceclone'}
SOURCES={
    'models':'https://mimo.mi.com/docs/en-US/updates/model',
    'integration':'https://mimo.mi.com/docs/en-US/tokenplan/integration/mimo-desktop',
    'token_plan':'https://mimo.mi.com/docs/zh-CN/quick-start/faq/token-plan/desktop-guide'}


def channel(base_url):
    return 'token_plan' if base_url.rstrip('/')==TOKEN_PLAN else 'pay_as_you_go'


def validate(settings):
    parsed=urlparse(settings.ai_base_url)
    if (parsed.scheme!='https' or parsed.hostname not in {'api.xiaomimimo.com','token-plan-cn.xiaomimimo.com'}
        or parsed.port not in {None,443} or parsed.path!='/v1' or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('MIMO_BASE_URL 须为已核验的小米按量 API 或中国区 Token Plan 官方 /v1 端点')
    # Normalize the equivalent explicit HTTPS port for channel classification.
    settings.ai_base_url='https://'+parsed.hostname+'/v1'
    for role in ('ai_model','ai_composition_model','ai_summary_model','notice_review_model'):
        if getattr(settings,role) not in TEXT_MODELS:
            raise ValueError('MiMo 文字模型须为当前已适配的 V2.6 Pro、Flash 或 Pro UltraSpeed；旧版 ID 不能继续配置')
    if any(getattr(settings,key)!=value for key,value in SPEECH_MODELS.items()):
        raise ValueError('MiMo 语音模型须使用当前适配的 V2.5 ASR / TTS 系列 ID')
    kind=channel(settings.ai_base_url)
    key=settings.ai_api_key
    if key.startswith(('tp-','ttp-')) and kind!='token_plan':
        raise ValueError('订阅凭证需要 Token Plan 专属端点，不能混用普通按量 API')
    if key.startswith('sk-') and kind!='pay_as_you_go':
        raise ValueError('普通 API 凭证需要按量端点，不能用来扣除 Token Plan 订阅额度')
    if kind=='token_plan' and any(getattr(settings,role)=='mimo-v2.6-pro-ultraspeed' for role in ('ai_model','ai_composition_model','ai_summary_model','notice_review_model')):
        raise ValueError('当前 Token Plan 不包含 Pro UltraSpeed，请选择 V2.6 Pro 或 Flash')


def public_configuration(settings):
    kind=channel(settings.ai_base_url)
    return {'configured':bool(settings.ai_api_key),'model':settings.ai_model,'composition_model':settings.ai_composition_model,
        'notice_review_enabled':settings.notice_semantic_review,'notice_review_model':settings.notice_review_model,
        'notice_modes':notice_processing_modes(settings),
        'provider':'Xiaomi MiMo','billing_channel':kind,'billing_label':'Token Plan 订阅通道' if kind=='token_plan' else '普通 API 按量通道',
        'catalog_verified_at':VERIFIED_AT,'available_text_models':sorted(TEXT_MODELS-({'mimo-v2.6-pro-ultraspeed'} if kind=='token_plan' else set())),
        'speech_available':kind=='pay_as_you_go' and bool(settings.ai_api_key),'documentation':SOURCES}


def notice_processing_modes(settings):
    modes=[{'id':'configured','label':'使用当前配置','description':'按服务设置完成提取与核对。' if settings.notice_semantic_review else '按服务设置提取；原文复核已由维护者关闭，须本人核对。',
            'model':settings.ai_model,'review_model':settings.notice_review_model if settings.notice_semantic_review else None}]
    if settings.notice_fast_enabled and channel(settings.ai_base_url)=='pay_as_you_go':
        modes.append({'id':'fast','label':'速度优先 · 费用较高','description':'使用 UltraSpeed 加速，保留原文复核和全部校验。' if settings.notice_semantic_review else '使用 UltraSpeed 加速提取；原文复核已由维护者关闭，须本人核对。',
            'model':'mimo-v2.6-pro-ultraspeed','review_model':'mimo-v2.6-pro-ultraspeed' if settings.notice_semantic_review else None,
            'price_note':'官方参考价：未命中缓存的输入 ¥30／百万 token，输出 ¥60／百万 token；输入、输出单价均为常规 Pro 的 10 倍。实际费用按返回用量和平台账单计算。',
            'price_source':'https://mimo.mi.com/models/en-US/mimo-v2.6-pro-ultraspeed','price_checked_at':VERIFIED_AT})
    return modes


def notice_settings(settings,mode):
    if mode=='configured':return settings
    if mode!='fast' or not any(item['id']==mode for item in notice_processing_modes(settings)):
        raise ValueError('当前服务未启用速度优先，或当前订阅通道不支持；请选择当前配置。')
    return replace(settings,ai_model='mimo-v2.6-pro-ultraspeed',notice_review_model='mimo-v2.6-pro-ultraspeed')
