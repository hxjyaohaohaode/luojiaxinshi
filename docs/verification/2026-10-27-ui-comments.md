# 生成式界面批注工程核对清单

范围：本轮关于 OpenIntelligentUI 参考、流式生成、聊天布局、按钮、提醒、拖拽、轨迹、刷新恢复和新对话手势的全部批注。表中记录对应实现与验证入口；通过数以本次提交的测试输出和 GitHub Actions 为准。

| 批注要求 | 实现与核对位置 | 验证入口 |
| --- | --- | --- |
| 深度参考 OpenIntelligentUI，适配本项目风格与真实数据 | `docs/genui/OPEN_INTELLIGENT_UI.md` 记录上游提交和实际采用机制；`openui_prompt.py`、`design-system.css`、宿主桥沿用本项目数据与动作边界；保留 MIT 许可 | `verify_openui.mjs`、`test_openui.py` |
| 文字与组件真实流式显示，不等整段完成 | `UIStreamDecoder` 增量 CSS/HTML；原 SSE 逐段交付，稳定画布保留输入和阅读状态 | `verify_openui.mjs`、`test_openui.py` |
| 不假定模型一定遵守 JSON 指令 | `answer_format.py` 兼容普通 Markdown、围栏、BOM、外层二次编码；仍执行 Schema、引用和事实核验，截断与错误不转成成功 | `test_answer_format.py`、`test_agent_authoring.py` |
| 读取图片缓慢、协议失败后反复重写 | 明确的窄范围图片阅读使用精简工具入口；格式兼容和无进展限制防止重复空转；不再依赖模型服务不支持的强制工具选择 | `test_answer_format.py`、`test_agent_chat.py`、`test_composer_media.py` |
| 空白和单行输入只占一行，显式换行再长高 | `fitComposer` 根据实际容器和换行调整；保留中文输入法、附件与语音行为 | `verify_chat_layout.mjs`、`composer-browser.mjs` |
| 顶栏按阅读状态收起，恢复时不能推开正文 | `chat-layout.css` 使用绝对定位浮层及透明度/位移；区域尺寸不随显隐变化，程序跟随滚动不触发阅读状态 | `verify_chat_layout.mjs` |
| 底部提示更矮、位置更靠下 | 提示行收紧至 14px 行高及 2px 上留白；底部输入和安全区域独立适配 | `verify_chat_layout.mjs` |
| 后续已有新消息时，旧回复不显示重生成 | `chat-policy.js` 同时约束渲染和点击；服务端拒绝重生成旧轮次 | `chat-policy.test.mjs`、`test_conversation_tools.py`、`verify_chat_interactions.mjs` |
| 所有消息按钮的适用情形 | 完成、失败、生成中、只读分支、朗读能力、保存、反馈和版本切换分别判断；后端重复检查权限与完成状态 | `chat-policy.test.mjs`、`verify_chat_interactions.mjs` |
| 取消逐消息时间及普通已回复状态，采用居中分组时间 | 根据用户发送时间按首条、约五分钟间隔或跨日分组；慢回复和历史版本创建时间不额外分组；精确时间保留为辅助信息 | `chat-policy.test.mjs`、`execution-trace.test.mjs`、`verify_chat_interactions.mjs` |
| 提醒规则、已读及归档需要优化 | 按真实事项类型分组；已读、归档、恢复与任务完成分开；按实际结束时间保留进行中和跨日安排，过期定时器不补发旧提醒 | `test_reminder_occurrences.py`、`reminders.test.mjs`、`verify_chat_interactions.mjs` |
| 新字逐个水墨晕染、相邻字交错出现 | 只为新到字符附加短暂高斯模糊、透明度与交错动画；稳定文字节点，保留 Unicode 字素，限制活动字数并支持减少动态效果 | `verify_chat_interactions.mjs` |
| 行内图标下移八分之一个字高 | 引用标记按正文 em 下移 `.125em`，内部数字独立保持小字号；正文内图标同样校正 | `chat-refinements.css`、实际页面样式核对 |
| 计时器和数字必须等宽 | 等宽字体加 `tabular-nums`，计时保留稳定宽度 | `verify_chat_interactions.mjs` |
| 思考/执行摘要可展开收起，不用 JS 计算高度 | `work-view.js` 管理 aria/inert，CSS 网格 `0fr/1fr` 动画；内容按需创建，无高度测量代码 | `verify_chat_interactions.mjs`、`agent-adaptive-browser.mjs` |
| 正文使用网格展开，内容变换有短延时 | 正文按块建立网格展开容器；显式零最小轨道避免 WebKit 换行后沿用旧高度并裁切文字；初次到达/切换版本采用短延时渐显，历史正文不重播；材料变化使用阅读过渡 | `renderer.js`、`verify_chat_interactions.mjs`、`verify_frontend_stability.mjs` |
| 避免段落最后一个汉字单独换行 | `text-wrap:pretty`，标题 balance，末尾汉字和闭合标点用展示 span 保护；不插入改变复制内容的字符 | `typography.js`、`verify_chat_interactions.mjs` |
| 拖拽立即跟手、吸附和落位 | 去除弹簧、触摸等待和延迟落位；指针捕获转移正确处理，拖动期间冻结阅读顶栏，真实保存回执不重放卡片入场动画 | `verify_task_board.mjs` 三浏览器及原生触摸检查 |
| 点击成功后显示勾选及约五秒倒计时环，结束恢复图标 | `action-feedback.js` 保留原图标 DOM；重复成功重置计时；播放和切换按钮继续表达自身状态 | `verify_chat_interactions.mjs` |
| 材料面板从右侧带短延时出现，文字同步过渡 | 网格宽度过渡与侧滑，正文淡入；焦点恢复防滚动，关闭后回到原宽度 | `verify_chat_interactions.mjs`、`verify_frontend_stability.mjs` |
| 切换回复版本不能跳到底部 | 使用稳定轮次/文字/操作栏锚点保持视口，锚点跳过浮动顶栏遮住的文字；用户真实滚动或显式回到最新会解除旧锚定 | `verify_chat_interactions.mjs`、`verify_workspace_interactions.mjs` |
| 借鉴 Harness 轨迹，但不能把摘要撑得很长 | 摘要只留简短内容与查看入口；完整真实执行步骤、耗时、搜索、详情置于独立窗口，默认不选择详情，不显示私有推理 | `execution-trace.test.mjs`、`verify_chat_interactions.mjs`、`agent-adaptive-browser.mjs` |
| 删除末尾无意义空白 | 阅读区和最后消息下留白归零，新对话手势不占永久空间 | `verify_chat_interactions.mjs` |
| 手机与电脑上推新对话，正文要跟着上移 | 在到达末尾后的额外手势中移动整个正文，圆环和图标使用本站墨绿色；触摸与鼠标独立阈值 | `verify_chat_interactions.mjs` 原生触摸及桌面滚轮 |
| 不能一滚动就新建，必须能够反悔 | 新手势/阈值/释放或停滚后，先有 1.2 秒取消窗口；回拉、反向滚动、输入或取消按钮可中止，保留原对话草稿；生成、上传、录音、转写等状态禁止触发 | `verify_chat_interactions.mjs` |
| 桌面鼠标可能断续滚动 | 短间隔内累计进度，限制单次大滚轮增量；到末尾的惯性不作为开始手势，超时和反向滚动取消 | `verify_chat_interactions.mjs` |
| 流式显示后刷新不能丢内容或回到旧稿 | 交付前保存独立未验证检查点；新一轮改稿显式清除旧内容；最终结果原样提交，完成后清理检查点 | `test_reply_preview.py`、`verify_chat_recovery.mjs` 三浏览器 |
| 历史版本的选择也应在刷新后保留 | 完整与未完成版本的主动回看选择均由服务端保存；未完成稿不进入后续模型事实上下文 | `test_reply_preview.py`、`verify_chat_recovery.mjs` |
| 最后的审核过慢，还错误否认先前真实操作 | 作者与审核者共享真实历史回执及本轮当前状态，避免把本轮无调用当成历史未执行；有限的纯表扬走无事实/操作承诺的固定系统回应，含任务/新材料/确认请求仍走正常链路 | `test_chat_continuity.py`、原对话零模型调用重试记录 |

## 验证边界

实质性事实、计算和生成代码继续执行程序检查与独立模型审查；没有为通过速度测试而跳过核验。真实模型的耗时、准确率和具体设备触摸手感不由合成测试保证。Android/iOS 等实机系统推送及真实学生试点仍按 `TESTING.md` 记录的外部验收范围处理。

本次回归会检查原有浏览器工作台、通知、来源、材料、Agent、语音、保存和恢复行为；发布前同时核对依赖审计、源包白名单及待提交文件。源码提交不包含运行数据库、`.env`、凭证、个人材料和本机截图。
