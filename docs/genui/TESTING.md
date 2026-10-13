# 验证记录

## 基线（Phase 0）

改动前：88 项 Python 测试、15 项 Node 测试通过。基线记录在 `artifacts/genui-baseline-python.xml`。工程夹具和用户数据分开，测试不需要真实模型密钥。

## Phase 2

`node --test tests/genui-core.test.mjs`：11 项通过；逐个 UTF-8 字节边界重切分，包含中文与四字节字符；半行缓冲、不完整保留、重复 id、patch、未知/错误节点、循环/深度/资源上限、原型污染、表达式、状态原子更新、信任边界均覆盖。

`.venv/Scripts/python.exe -m pytest tests/test_genui_core.py -q`：17 项通过；同一夹具由 JS 与 Python 规范化，输出逐值一致；服务器独立校验恶意输入与生成目录漂移。

## Phase 3

画廊：`/static/genui/gallery.html`。38 个组件，每个都可切换默认、加载、空、错误、长文本和渐进状态；亮暗主题与窄屏控制独立。画廊使用工程示例，不读取账户或调用模型。

浏览器实测各 199 项通过（1440×900 亮色、320×740 暗色）：190 个组件/状态组合，另加本地联动无 fetch、焦点保持、快照恢复、表格数值排序、方向键标签切换、清单、动作点击门槛、恶意文本/图片、节点错误隔离、流式/历史一致性、300 节点性能。测试入口为“运行组件验证”，实现为 `static/genui/gallery-tests.js`。

| 场景 | 1440 亮色 | 320 暗色 |
| --- | ---: | ---: |
| 本地交互到结果帧 | 14.3 ms | 14.7 ms |
| 300 节点首次渲染 | 11.2 ms | 8.8 ms |
| 300 节点更新到结果帧 | 34.9 ms | 38.2 ms |
| 其中实际更新渲染 | 8.6 ms | 6.4 ms |

这是本机浏览器的一次实测，不代表所有手机性能。原始结果及截图位于 `artifacts/genui-components-*.json`、`genui-slider-dark-320.png`。图表模块动态加载，体积明细在 `artifacts/genui-size-phase3.json`（gzip 为离线估算，不冒充服务端传输量）。

真实 SSE 通道、数据库历史、现有对话集成、完整产品视觉回归仍在后续阶段验证。
