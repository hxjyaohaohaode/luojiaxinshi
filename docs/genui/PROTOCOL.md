# genui v1 协议

此页描述兼容保留的原生组件图。当前复杂任务默认按需使用 `openui` 自由生成文档，支持 CSS 优先、HTML 渐进预览和最终交互；模型参数、`ui_preview` 事件、隔离与历史保存见 [OpenIntelligentUI 适配](OPEN_INTELLIGENT_UI.md)。两种产物共享原会话、版本与 `ui-state` 端点。

消息是 Markdown 文字与 `genui` 围栏块交错的 parts。普通代码围栏保持代码，不能嵌套解释成界面。genui 中每行是一个完整 JSON 操作；在收到行结束前不应用半行。UTF-8 字节拆分用流式解码；CRLF 与 LF 等价。EOF 时未关闭围栏标为 incomplete，保留已通过检查的部分和可读降级。

```genui
{"op":"begin","v":1}
{"op":"state","set":{"hours":2}}
{"op":"node","id":"root","type":"Stack","children":["input","result"]}
{"op":"node","id":"input","type":"Slider","props":{"label":"每天学习小时","min":0,"max":8,"step":0.5,"bind":"hours"}}
{"op":"node","id":"result","type":"Stat","props":{"label":"一周可安排","value":{"$expr":"round(hours*7,1)"},"unit":"小时"}}
{"op":"end"}
```

## 操作

| op | 字段 | 语义 |
| --- | --- | --- |
| begin | v=1 | 开始区块，未知版本降级 |
| state | set 对象 | 初始化可绑定状态；控件修改之后，迟到默认值不覆盖用户输入 |
| data | id、value | 协议支持的可信数据操作；只由独立宿主通道注入，原始模型文本不享有注入权限 |
| node | id、type、props、children、on | 扁平节点定义；children 为 id 列表，同 id 后定义覆盖旧定义 |
| patch | id、props/children/on | 仅修正已经定义的节点，属性浅合并；不能引入目录之外的属性 |
| end | 无 | 完整校验与增量结果对账；后续操作不生效 |

允许属性值为字面量、单键 `{"$bind":"状态路径"}`、`{"$expr":"表达式"}`、`{"$ref":"数据路径"}`。路径只读取自身属性，禁止原型相关键、隐式全局对象和可执行字符串。输入 bind 只能写已经声明的安全状态路径。

`on` 只允许 click/change/submit，每个事件对应一个 state、open_url、host 或 ask_model 动作。组件目录的 actions 定义所有合法字段。没有批量动作、函数名调用、load 事件或自动执行动作。ask_model 由用户显式点击，结构化事件作为一条用户消息加入当前会话，并沿用外部处理同意检查。

## 上限与恢复

目录中的 limits 是默认配置：300 节点、深度 8、字符串 UTF-8 8192 字节、区块 262144 字节、表达式 500 字符及独立计算步数、单条消息和区块数量上限。超限区块停止接纳操作，但消息正文继续以有限可读文字保留。错误不执行内容，不输出到控制台正文。

规范化 spec 保存版本、节点表、根节点、初始状态、可信数据引用、区块状态和不含原文的错误码。非法节点替换为可读占位。不存在的子节点在流中显示等待占位，结束后显示缺失提示；循环、超深和重复父引用不继续递归。

旧消息无 parts 时作为一个文字 part。开关关闭使用正文降级；开启时可逐步增强 Markdown 表格、任务列表、代码和有序列表。raw 原始流、规范化 parts 和用户保存的快照分别存储；渲染时再次校验，不能信任数据库中的规范化结果来自新版本。

## 传输与存储

`POST /api/conversations/{cid}/messages/stream` 沿用原发送接口的 JSON 请求体、同意项、登录会话、来源校验、CSRF、会话版本和 request_id。返回 SSE，每帧带单调递增 id：`start` 给出消息 id、当前会话、可信 data 与运行上限；`delta` 只带已解码的 answer 文本；`done` 给出服务器最终检查后的会话。重复 request_id 仅重放历史，不重复调用模型。

兼容模型 JSON 外壳中的 answer 字符串逐步解码，包括转义、多字节字符和代理对；引用在流结束后按原文检查。最终检查前内容属于临时输出，不能把生成中的内容视为已经通过引用核对。失败时保留文字并显示未完成状态，不伪造引用。

每份已发出的增量先写入 `genui_messages.raw`。服务器完成后保存规范化 parts、引用和状态；取消会终止本机的流式读取并保留最后已交付的检查点。中断不自动重试，避免重复计费。未知断线可能仍已在模型侧计费。

新增表 `genui_messages`、`genui_preferences`，基础 schema_version 仍为 4。老消息和原 POST 接口仍可用；旧版本程序可忽略新增表。基础消息 content 保存可读文字，包含表达式的统计项会在回退文字中保留计算式，精确的当前交互结果由前端“复制为文字”导出。

`PUT /api/conversations/{cid}/messages/{mid}/ui-state` 显式保存各 UI part 的 `{state,view}`。独立 snapshot_version 执行比较并交换；状态类型、节点范围、原型键、深度和总大小均校验。滑动、勾选、排序不会调用此接口。

`PUT /api/genui/preferences` 保存个人开关和亮/暗/随系统主题；部署开关 GENUI_ENABLED 拥有最终禁用权。能力由 JSON 输出、工具调用、上下文长度和显式 tier 配置描述，模型名称不参与能力推断。

## 扩展组件与展示边界

新增 `Video` 使用受信任 `src`、说明和浏览器原生 controls，不支持任意 embed、iframe 或 autoplay。`Plot` 使用受限表达式、限定变量和最多 120 个采样点，由本地代码生成 SVG；解析和求值预算生效。确切属性、枚举、上限以唯一目录 `schema/genui/catalog.json` 为准，前后端与提示说明由此派生。

素材索引、来源时间和正文引用仍来自宿主，模型不可以通过 data 操作把任意 URL 升级成可信视频/图片。普通 Markdown、模型流、历史加载与复制均保留等价文字表达。
