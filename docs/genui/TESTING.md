# 验证记录

## 基线（Phase 0）

改动前：88 项 Python 测试、15 项 Node 测试通过。基线记录在 `artifacts/genui-baseline-python.xml`。工程夹具和用户数据分开，测试不需要真实模型密钥。

## Phase 2

`node --test tests/genui-core.test.mjs`：11 项通过；逐个 UTF-8 字节边界重切分，包含中文与四字节字符；半行缓冲、不完整保留、重复 id、patch、未知/错误节点、循环/深度/资源上限、原型污染、表达式、状态原子更新、信任边界均覆盖。

`.venv/Scripts/python.exe -m pytest tests/test_genui_core.py -q`：17 项通过；同一夹具由 JS 与 Python 规范化，输出逐值一致；服务器独立校验恶意输入与生成目录漂移。

这些结果只证明核心库。组件视觉、真实流式通道、历史与浏览器联动将在后续阶段分别记录；此时尚未验证。
