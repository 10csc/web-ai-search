# 已知陷阱与设计约束

> v6 更新：原 18 条中 13 条已彻底解决（归档在底部），保留 5 条仍然生效。

---

## 仍生效的陷阱（5 条）

### 1. Chrome execCommand 已废弃
- document.execCommand("insertText") 在 Chrome 120+ 静默失败
- 当前: generator.py 兜底模板均用 page.keyboard.insert_text()
- 注意: 新平台脚本禁止 execCommand

### 2. DeepSeek 发送键
- Control+Enter / Enter 在 contenteditable div 中可能是换行
- 当前: submit() 优先按钮选择器，Enter 仅兜底
- 注意: LLM 生成脚本必须优先点按钮

### 3. 弹窗/对话框阻塞
- window.confirm 不是 DOM 元素，querySelector 找不到
- 当前: page.on("dialog") + Escape 双保险
- 铁律: dismiss_blockers 只在前发送调用

### 4. 发送后不要按 Escape
- Gemini 将 Escape 解释为停止生成
- 当前: SKILL.md 速查明确"发送后不按 Escape"

### 5. 沙箱 writable_roots
- Codex 沙箱只允许写特定目录
- 当前: 依赖 require_escalated 提权，代码无法自动解决

---

## v6 已解决（归档）

| 原陷阱 | v6 解决方式 |
|--------|-----------|
| PowerShell 编码陷阱 | import 方式，数据全程在 Python 内存 |
| 提示词自带标记 | extractor.py prompt_marker_excluded 检测 |
| positions[-1] 跨对话污染 | 仅用相邻标记对 |
| rfind 取最后提示词 | rfind + 渐缩短查找 |
| 页面刷新后元素未加载 | time.sleep(5) + domcontentloaded |
| 发送后残留检测 | run_send 检测残留长度 |
| 清零非通用标准 | 残留 <= 2 字符即成功 |
| 提示词唯一性 | @hash + 随机种子每次重新生成 |
| PowerShell 中文传参 | import 完全绕过 shell |
| innerText 不可靠 | 多重降级路径，标记锚点兜底 |
| 反复杀 Edge 进程 | SKILL.md 核心约束 + CDP 前置 |
| 旧 prompt 复用 | 核心约束强制重新生成 + @hash 验证 |
| 本地环境硬编码 | setup.py 自动探测 + config.json 持久化 |