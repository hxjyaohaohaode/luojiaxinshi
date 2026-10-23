# 小米 MiMo 模型配置与对接

更新日期：2026-10-18，版本 1.11.0。本文件与“小米模型版”项目方案、最小可行版本配套。此前 401 是启动进程继承的旧密钥覆盖正确的本机配置，1.4.0 已修复。主模型、普通 TTS、音色设计及 ASR 已通过真实合成样本请求；1.7.0 另完成项目内真实通知的单样本整理复验。声音复刻、真实学生效果及目标设备仍需分别验收。工程模拟回归与真实模型结果在 [TESTING.md](TESTING.md) 中分开记录。

1.9.0 默认在 Pro 提取后由 Flash 开启思考独立复核行动语义。配置为 `NOTICE_SEMANTIC_REVIEW=true`、`MIMO_NOTICE_REVIEW_MODEL=mimo-v2.6-flash`；至多两个模型请求，没有自动重试。Flash 复核输出预算为 6,144；1.10.0 将 Pro／UltraSpeed 复核预算设为 16,384，包含思考与答案，输入独立检查。每阶段保留实际用量，缺失用量明确标记；每日限制仍按整理次数计。复核失败不会丢弃提取草稿，但本人需明确勾选逐份人工核对并填写说明后才可保存。1.11.0 对有意见的草稿要求逐条处理并关联实际改动或排除，不新增模型请求；详见 [ADR-008](docs/ADR-008-per-issue-human-resolution.md)。此阶段增加耗时，不承诺稳定提速，取舍见 [ADR-006](docs/ADR-006-independent-action-review.md)。

通知整理在 1.8.0 输出紧邻步骤的分类、前置与条件建议，服务器分离保存。条件状态、本人参加决定和学校受理结论不由模型填写。真实复杂通知的失败、兼容修正及复验逐次记录在 TESTING.md；不据单样本宣称整体速度或准确率。

## 模型与实际用途

| 功能 | 当前默认模型 | 使用方式 |
|---|---|---|
| 通知理解、事实抽取、适用条件判断、问答、计划解释、截图理解、互动回答 | `mimo-v2.6-pro` | `app/ai.py`、`app/chat_ai.py`、`app/genui_ai.py`；方案中的协调、专业分析及复核角色共用这个模型，按任务隔离上下文 |
| 麦克风听写、口述问题转文字 | `mimo-v2.5-asr` | 聊天和通知输入框的麦克风；先显示转写文字，用户核对后再发送 |
| 普通通知、待办、回答播报 | `mimo-v2.5-tts` | “个人设置 → 语音播报 → 普通播报”，使用预置音色 |
| 小信使个性音色 | `mimo-v2.5-tts-voicedesign` | 选择音色设计并描述声音；每次请求直接合成，不假定存在持久 voice_id |
| 本人或获授权声音播报 | `mimo-v2.5-tts-voiceclone` | 默认关闭，维护者设置 `VOICE_CLONE_ENABLED=true` 后可用；选择声音复刻，提供参考 WAV 并确认声音授权；每次携带参考录音，无训练步骤 |

五个模型都已有调用入口，按场景选择；一次普通问答只需要主模型。文本提取、数据库检索、原文匹配、权限、日期校验和排程等确定性程序继续在本地运行，不引入其他 AI 服务。ASR 只做转写，不承诺说话人分离或精确时间戳；TTS 只生成音频，后台提醒送达仍取决于原有日历或通知渠道。

## 按次使用加速模型

`NOTICE_FAST_ENABLED=true` 并重启后，普通按量通道的通知页提供“速度优先 · 费用较高”。默认仍为“使用当前配置”；每次选择加速都会显示官方价格，切换档位清除旧的外部处理勾选。后端只用本次配置副本将提取和复核切换为 `mimo-v2.6-pro-ultraspeed`，不改变全局模型或其他功能。Token Plan 不显示也不接受此档位，仓库示例默认关闭。

2026-10-18 核对：[UltraSpeed 官方](https://mimo.mi.com/models/en-US/mimo-v2.6-pro-ultraspeed)的普通输入 ¥30／百万 token、缓存输入 ¥0.25／百万 token、输出 ¥60／百万 token；普通输入与输出单价为[常规 Pro](https://mimo.mi.com/models/en-US/mimo-v2.6-pro)的 10 倍。最终真实样本 39.438 秒、两次请求，按返回用量估算约 ¥1.379；这不是供应商账单、固定每次价格或稳定延迟。原始失败和质量问题一并保留，见 [ADR-007](docs/ADR-007-notice-processing-modes.md)。

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
AI_OUTPUT_TOKENS=131072
AI_CONTEXT_TOKENS=1000000
AGENT_CONTEXT_BYTES=2000000
AI_WORKFLOW_TIMEOUT_SECONDS=1800
AI_DAILY_LIMIT=30
AI_STAGE_SUMMARIES=false
```

旧 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 不再读取。1.5.0 的 `app/model_catalog.py` 集中校验以下官方通道，不会在请求失败后自动更换费用方案。QQ、微信凭证与模型密钥独立。

| 通道 | 凭证类型 | `MIMO_BASE_URL` | 本应用支持配置的文字模型 |
|---|---|---|---|
| 普通 API 按量 | `sk-` 前缀 | `https://api.xiaomimimo.com/v1` | V2.6 Pro、Flash、Pro UltraSpeed |
| 中国区 Token Plan | `tp-` 或 `ttp-` 前缀 | `https://token-plan-cn.xiaomimimo.com/v1` | V2.6 Pro、Flash |

对应文字 ID 为 `mimo-v2.6-pro`、`mimo-v2.6-flash`、`mimo-v2.6-pro-ultraspeed`。凭证与通道不匹配、非官方端点、未知模型或 Token Plan 配置 UltraSpeed 会在启动时拒绝。默认通知提取为 Pro、通知复核为 Flash，互动回答的写作与独立复核为 Pro；目录不代表当前账号均有权限。依据为[官方集成说明](https://mimo.mi.com/docs/en-US/tokenplan/integration/mimo-desktop)和[Token Plan 规则](https://mimo.mi.com/docs/zh-CN/quick-start/faq/token-plan/desktop-guide)。

本次凭证的成功请求来自普通 API，不能据此断言扣除订阅额度。当前语音适配器仅支持普通 API；Token Plan 下会说明暂不可用并在外发前拒绝。这是本应用的适配边界，不是对供应商全部订阅语音能力的判断。

`APP_ENV=local` 时，仅 `MIMO_API_KEY` 由明确存在于本机 `.env` 的值覆盖同名继承变量；文件中的空值表示主动停用。`APP_ENV=production` 保持注入环境优先。不会打印密钥或向浏览器下发密钥。

## 请求契约

文字请求 POST 到所选官方端点的 `/chat/completions`；四类语音使用普通 API 的同名路径。使用 `Authorization: Bearer <MIMO_API_KEY>`。兼容协议名称不表示调用了 OpenAI 模型。

- 主模型：保留 `messages`、图片 `image_url` 和 JSON 输出，输出上限使用 `max_completion_tokens`。通知整理、检索规划、覆盖检查、原生交互图编排与最终独立复核使用 `thinking: {"type":"enabled"}`，这些调用不传 `temperature` 或 `top_p`。自 1.19.4 起，Agent 工具循环、纯文字展示、修复、独立核验和记忆维护全部显式开启思考，不因任务简单而关闭。工具多轮调用完整回传服务端 `reasoning_content`，只在当前 Provider 内存保存，结束即清理，不进入聊天、持久日志或 UI。1.4.0 的限定材料短文字路径合并覆盖与写作，两次主模型调用均开启思考，第二次独立复核。阶段提示默认直接使用服务器实际状态；只有显式启用 `AI_STAGE_SUMMARIES=true` 才由 Flash 改写状态提示，不接收内部推理。思考开关与温度限制见[小米官方深度思考说明](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/other/deep-thinking)。所有 MiMo 文字阶段统一使用 `AI_CONTEXT_TOKENS=1000000` 和 `max_completion_tokens=131072`，不再保留按阶段设置的较小额度；128K 指思考与最终输出的合计上限。
- ASR：`model=mimo-v2.5-asr`；`user.content` 内放 `type=input_audio`，数据为 `data:audio/wav;base64,...`；`asr_options.language=auto`；读取 `choices[0].message.content`。
- 普通 TTS：`assistant.content` 放实际播报正文，`user.content` 仅作为风格指令；`audio={"format":"wav","voice":"mimo_default"}`。
- 音色设计：`user.content` 必填音色描述；`assistant.content` 放已核对正文；`audio={"format":"wav","optimize_text_preview":false}`，不传 `voice`，避免自动润色改变日期、材料或办理要求。
- 声音复刻：`audio.voice` 放参考 WAV 的 data URL；`assistant.content` 放正文，不把复刻模型当作普通预置音色模型使用。
- 三种 TTS 都读取 `choices[0].message.audio.data` 的 Base64 音频。本应用首轮使用非流式 WAV 输出；官方普通 TTS 支持低延迟流式，而设计／复刻的兼容流式不等于边生成边播放。

## 通知整理输入预算

1.7.0 的原文段落携带请求内唯一编号。模型的 evidence 只返回编号，服务端恢复准确原句和位置后再校验，原有前端草稿结构不变。未知编号、无效结构及不完整输出拒绝；已从供应商收到的实际用量在失败时也记录，未知用量仍为空。`24:00` 和完整日期一起归一化到次日 `00:00`，原表述保留；时刻必须与对应日期有同一原文依据，不借用其他节点。详见 [ADR-003](docs/ADR-003-notice-evidence-references.md)。

`NOTICE_INPUT_TOKENS` 默认 65,536，可设为 4,096—900,000；现有 `AI_CONTEXT_TOKENS` 保留互动回答能力分层用途，两者不混用。通知预算包含系统提示、JSON 字段结构、必要身份条件、全部原文／段落位置及图片估算。在模型调用前校验，超限返回 422，保留原件和已有草稿，不消耗每日模型调用次数；不会自动裁剪材料、压缩图片或发起重试。预算检查后到正式调用前还会再次核对通知版本。

文字按 UTF-8 字节数保守计量并预留消息封装空间，图片使用[小米官方尺寸估算规则](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)。该结果是应用预算估算，不是精确 tokenizer 或计费数据；实际用量仍取 API 返回的 `usage`。例如大量短段落会增加来源定位与 JSON 的输入，即使正文未超 10,000 字也可能触及预算。

主模型的[官方上下文规格](https://mimo.mi.com/docs/quick-start/model)为 1M；代码使用保守的 1,000,000 上界，并为统一的 131,072 最大输出留出空间。维护者可根据真实样本覆盖率调整输入预算，但仍须遵守文件／字数限制和实际账户能力。此检查只覆盖正式通知整理入口，不能推断其他多阶段对话已完成相同的总输入或费用验证。

## 本应用语音接口和限制

| 路由 | 输入 | 输出 |
|---|---|---|
| `GET /api/speech/config` | 已登录会话 | 四种语音模型及是否已填密钥，不返回密钥 |
| `POST /api/speech/transcribe` | multipart：`audio`、`allow_external_processing=true` | 转写文字和模型 ID |
| `POST /api/speech/synthesize` | multipart：`text`、`mode=default/design/clone`、`allow_external_processing=true`；设计追加 `description`；复刻追加 `reference`、`clone_authorized=true` | `audio/wav`，模型 ID 在 `X-Speech-Model`，并带 `X-AI-Generated: true` |

1.20.0 起，合成的 WAV 在文件尾追加 RIFF `LIST/INFO` 元数据（`ICMT`、`ISFT`），写明“AI生成内容”、服务名和模型，作为隐式标识，音频数据本身不变；缓存重放返回同一份已标识文件。声音复刻默认关闭（`VOICE_CLONE_ENABLED=false`），关闭时 `mode=clone` 直接返回 403，不会发到小米；开启前，部署方须先建立被复刻人的书面授权流程。

所有写请求沿用登录、同源校验和 CSRF。录音、参考音频及合成音频在应用内存中处理，不写入通知库或普通日志；小米侧处理规则以其服务条款和隐私政策为准。

官方 ASR 与复刻支持 MP3/WAV；本轮应用先接受 **16 位 PCM WAV**，单文件 5 MB 以内。浏览器麦克风录音在本地转换为 16 kHz 单声道 WAV 后上传。ASR 输入最长 60 秒；复刻参考最长 30 秒；播报最多 2,000 字、音色描述最多 500 字。这些是应用限制，不是小米官方极限。语音每账号每日次数使用 `AI_DAILY_LIMIT` 独立计数，与既有通知／聊天限额分别计数。

听写不会自动发送消息或建待办；取消页面、权限拒绝、超时、额度不足、非完整响应或无效音频均明确反馈。不会自动切换第三方模型，不自动重试可能计费的请求。生成音频不会自动播放，点击播放器后试听。

## 已执行的真实联调及后续复验

1.7.0 使用项目内真实赛事通知与榜题材料、虚构参赛者资料做一次修复前及一次修复后调用。修复前 221.218 秒后因三处 Markdown 链接引文变化返回 502；修复后 128.422 秒 HTTP 200，9 项事先登记的检查通过，实际返回 6,435 输入、6,014 输出 token。生成 9 项个人步骤和 4 项单位步骤；本人签章、申请确认与最终上传分别保留，个人截止为 2026-10-20 00:00。模型曾对单位日期补年份，程序拒绝采纳该候选。不能据这两个样本推断整体准确率或固定提速比例；正式通知仍为一次 Pro 思考调用，没有自动重试。HTTP 读取超时不是总墙钟耗时上限。

复现脚本 `scripts/verify_business_notice.py --live --label verified --keep-fixture` 会发送这两份指定项目材料与合成资料，默认不带 `--live` 时只保存检查条件；保留的隔离库用于浏览器验收。新一次请求可能计费且输出有波动，不能把复现说明当作自动重跑安排。当前真实调用仍走普通 API，不据此声称扣除订阅额度。

1.5.0 使用合成短句：普通 TTS 1.594 秒返回 24 kHz、3.52 秒 WAV；音色设计 1.375 秒返回 24 kHz、3.68 秒 WAV；ASR 1.109 秒正确转写合成音频。长历史样本 23.5 秒完成两次 Pro 思考调用和九项预设检查。脚本为 `scripts/verify_speech_models.py --live` 与 `scripts/verify_personalization.py --live --long-history`。这不是人声准确率、人工音质评分或吞吐基准；未发起真实声音复刻。实际设备和业务材料按以下步骤复验：

1. 检查模型服务页，确认模型为 `mimo-v2.6-pro`。用一则文字通知验证 JSON、逐字引用及待办确认，再用截图检验视觉理解和人工核对提示。
2. 分别验证普通聊天和流式互动回答，核对取消、超时、输出长度与引用校验。
3. 麦克风录制一段包含中文、人名、日期和数字的口述，确认 ASR 结果回填且未自动发送；检查目标手机和电脑的录音兼容性。
4. 依次试听普通 TTS、音色设计和已授权参考声音复刻（复刻须先设置 `VOICE_CLONE_ENABLED=true` 并具备书面授权），确认正文、日期、数字及专有名词；无参考音频或未确认授权时不应发起复刻。
5. 在小米控制台核对每个模型的实际权限、计费与限流。模型效果、声音相似度、延迟和费用不由模拟测试证明。

## 官方依据

原接口核对日期：2026-10-14；2026-10-18 复核模型目录、凭证通道、上下文及图片估算规则。文字为 V2.6，官方语音仍为 V2.5；不能因文字更新就改写语音 ID。

- [模型更新记录](https://mimo.mi.com/docs/en-US/updates/model)

- [小米聊天接口](https://mimo.mi.com/docs/en-US/api/chat)
- [结构化输出](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)
- [图像理解](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)
- [MiMo ASR 接口](https://mimo.mi.com/docs/en-US/api/audio/Speech-Recognition)
- [MiMo TTS 接口](https://mimo.mi.com/docs/en-US/api/audio/tts)
- [TTS 系列使用指南](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)

## 1.8.1 通知流式整理

通知请求使用 `stream=true`、`stream_options.include_usage=true` 和原有 `json_object`，保留 Pro 思考模式及统一的 131,072 最大输出；收齐响应后执行引用、日期和办理结构校验。用量尾包只提取数字，思考正文不进入数据库、日志或浏览器。处理记录区分首段答案等待、模型请求及本地校验耗时；这不是模型纯计算时间或计费凭证。

对同一复杂通知关闭思考的诊断虽降至约 40 秒，但遗漏可选咨询，未采用为默认。开启思考的另一轮也因缺少一项依据被拒绝，说明不能省略服务器校验。更多诊断与最终复验见 [TESTING.md](TESTING.md)、[ADR-005](docs/ADR-005-notice-streaming-and-measurement.md)。普通 API 与订阅额度的区分不变。
