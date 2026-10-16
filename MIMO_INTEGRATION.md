# 小米 MiMo 模型配置与对接

更新日期：2026-10-14。本文件与本轮“小米模型版”项目方案、最小可行版本配套，取代旧供应商的 AI 接入说明。真实模型联调待完成；本轮工程验证使用模拟接口，不使用真实 API Key。配置存在不等于权限和连通性已经验证。

## 模型与实际用途

| 功能 | 唯一模型 | 使用方式 |
|---|---|---|
| 通知理解、事实抽取、适用条件判断、问答、计划解释、截图理解、互动回答 | `mimo-v2.6-pro` | `app/ai.py`、`app/chat_ai.py`、`app/genui_ai.py`；方案中的协调、专业分析及复核角色共用这个模型，按任务隔离上下文 |
| 麦克风听写、口述问题转文字 | `mimo-v2.5-asr` | 聊天和通知输入框的麦克风；先显示转写文字，用户核对后再发送 |
| 普通通知、待办、回答播报 | `mimo-v2.5-tts` | “个人设置 → 语音播报 → 普通播报”，使用预置音色 |
| 小信使个性音色 | `mimo-v2.5-tts-voicedesign` | 选择音色设计并描述声音；每次请求直接合成，不假定存在持久 voice_id |
| 本人或获授权声音播报 | `mimo-v2.5-tts-voiceclone` | 选择声音复刻，提供参考 WAV 并确认声音授权；每次携带参考录音，无训练步骤 |

五个模型都已有调用入口，按场景选择；一次普通问答只需要主模型。文本提取、数据库检索、原文匹配、权限、日期校验和排程等确定性程序继续在本地运行，不引入其他 AI 服务。ASR 只做转写，不承诺说话人分离或精确时间戳；TTS 只生成音频，后台提醒送达仍取决于原有日历或通知渠道。

## 填写密钥

编辑 `系统_开发/.env` 的 `MIMO_API_KEY=`，填写小米按量 API Key 后运行 `重启工作台.cmd`。不要把密钥贴入方案、前端文件或提交到 Git。以下配置已预置：

```dotenv
MIMO_API_KEY=
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_TEXT_MODEL=mimo-v2.6-pro
MIMO_ASR_MODEL=mimo-v2.5-asr
MIMO_TTS_MODEL=mimo-v2.5-tts
MIMO_VOICE_DESIGN_MODEL=mimo-v2.5-tts-voicedesign
MIMO_VOICE_CLONE_MODEL=mimo-v2.5-tts-voiceclone
MIMO_TTS_VOICE=mimo_default
AI_TIMEOUT_SECONDS=180
AI_OUTPUT_TOKENS=32768
AI_WORKFLOW_TIMEOUT_SECONDS=1800
AI_DAILY_LIMIT=30
```

旧 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 不再读取，避免旧供应商密钥误发。Token Plan 有独立密钥、端点与适用规则，本版本固定使用按量 API，不应直接填写 Token Plan 专用密钥。一个按量密钥能否调用全部五个模型，以该账号实际权限和额度为准。QQ、微信等凭证与模型密钥独立。

## 请求契约

五个模型统一 POST `https://api.xiaomimimo.com/v1/chat/completions`，使用 `Authorization: Bearer <MIMO_API_KEY>`。兼容协议名称不表示调用了 OpenAI 模型。

- 主模型：保留 `messages`、图片 `image_url` 和 JSON 输出，输出上限使用 `max_completion_tokens`。通知整理、检索规划、覆盖检查、原生交互图编排与最终独立复核使用 `thinking: {"type":"enabled"}`，这些调用不传 `temperature` 或 `top_p`。已有覆盖结果的纯文字展示阶段关闭思考并使用 `temperature=0.2`；阶段摘要由 Flash 处理受约束的实际工作状态，不接收内部推理。思考开关与温度限制见[小米官方深度思考说明](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/other/deep-thinking)。`AI_CONTEXT_TOKENS=32768` 是本应用保守预算，不是官方模型最大上下文。
- ASR：`model=mimo-v2.5-asr`；`user.content` 内放 `type=input_audio`，数据为 `data:audio/wav;base64,...`；`asr_options.language=auto`；读取 `choices[0].message.content`。
- 普通 TTS：`assistant.content` 放实际播报正文，`user.content` 仅作为风格指令；`audio={"format":"wav","voice":"mimo_default"}`。
- 音色设计：`user.content` 必填音色描述；`assistant.content` 放已核对正文；`audio={"format":"wav","optimize_text_preview":false}`，不传 `voice`，避免自动润色改变日期、材料或办理要求。
- 声音复刻：`audio.voice` 放参考 WAV 的 data URL；`assistant.content` 放正文，不把复刻模型当作普通预置音色模型使用。
- 三种 TTS 都读取 `choices[0].message.audio.data` 的 Base64 音频。本应用首轮使用非流式 WAV 输出；官方普通 TTS 支持低延迟流式，而设计／复刻的兼容流式不等于边生成边播放。

## 本应用语音接口和限制

| 路由 | 输入 | 输出 |
|---|---|---|
| `GET /api/speech/config` | 已登录会话 | 四种语音模型及是否已填密钥，不返回密钥 |
| `POST /api/speech/transcribe` | multipart：`audio`、`allow_external_processing=true` | 转写文字和模型 ID |
| `POST /api/speech/synthesize` | multipart：`text`、`mode=default/design/clone`、`allow_external_processing=true`；设计追加 `description`；复刻追加 `reference`、`clone_authorized=true` | `audio/wav`，模型 ID 在 `X-Speech-Model` |

所有写请求沿用登录、同源校验和 CSRF。录音、参考音频及合成音频在应用内存中处理，不写入通知库或普通日志；小米侧处理规则以其服务条款和隐私政策为准。

官方 ASR 与复刻支持 MP3/WAV；本轮应用先接受 **16 位 PCM WAV**，单文件 5 MB 以内。浏览器麦克风录音在本地转换为 16 kHz 单声道 WAV 后上传。ASR 输入最长 60 秒；复刻参考最长 30 秒；播报最多 2,000 字、音色描述最多 500 字。这些是应用限制，不是小米官方极限。语音每账号每日次数使用 `AI_DAILY_LIMIT` 独立计数，与既有通知／聊天限额分别计数。

听写不会自动发送消息或建待办；取消页面、权限拒绝、超时、额度不足、非完整响应或无效音频均明确反馈。不会自动切换第三方模型，不自动重试可能计费的请求。生成音频不会自动播放，点击播放器后试听。

## 提供密钥后的联调

1. 检查模型服务页，确认模型为 `mimo-v2.6-pro`。用一则文字通知验证 JSON、逐字引用及待办确认，再用截图检验视觉理解和人工核对提示。
2. 分别验证普通聊天和流式互动回答，核对取消、超时、输出长度与引用校验。
3. 麦克风录制一段包含中文、人名、日期和数字的口述，确认 ASR 结果回填且未自动发送；检查目标手机和电脑的录音兼容性。
4. 依次试听普通 TTS、音色设计和已授权参考声音复刻，确认正文、日期、数字及专有名词；无参考音频或未确认授权时不应发起复刻。
5. 在小米控制台核对每个模型的实际权限、计费与限流。模型效果、声音相似度、延迟和费用不由模拟测试证明。

## 官方依据

核对日期：2026-10-14。

- [小米聊天接口](https://mimo.mi.com/docs/en-US/api/chat)
- [结构化输出](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)
- [图像理解](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)
- [MiMo ASR 接口](https://mimo.mi.com/docs/en-US/api/audio/Speech-Recognition)
- [MiMo TTS 接口](https://mimo.mi.com/docs/en-US/api/audio/tts)
- [TTS 系列使用指南](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)
