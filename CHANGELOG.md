# 变更记录

## 0.3.1（2026-11-12）

移除敏感目录黑名单。允许根目录内的路径不再有「拒绝删除」的特例，家目录根、`AppData` 各层、`System32`、`WindowsApps` 都能删。

### 实现

- `server.py`：删掉 `sensitive_paths()` 整个函数，以及 `validate_target()` 里的 `拒绝操作敏感目录` 分支；顺带清掉只为它存在的 `import string`。
- 不再特殊拒绝：家目录根、盘符根、`AppData`（Local/Roaming/LocalLow）、Desktop/Documents/Downloads/Pictures/Videos/Music、`ProgramData`、`Program Files`（含 `WindowsApps`）、`Windows`/`System32`/`SysWOW64`/`WinSxS`、`System Volume Information`、`TEMP`。
- **仍然保留**：token + Host 校验、按报告原始路径匹配的 allowlist、越界检查（路径仍须落在允许根目录内）、junction / 符号链接只删链接本身、逐项审计。
- **仍然生效的边界**：盘符根这类路径受「允许根目录」约束——默认根只有 `%USERPROFILE%` 与 `Program Files`，要动别的盘或根级路径仍需 `--allow-root`。

### 文档与测试

- SKILL.md（三灯限权、安全模型、排障表）、README（设计要点、路径护栏、测试覆盖表）、`references/reporting-guide.md`、NOTICE 同步新语义。
- `test_sensitive_home_rejected` 改为 `test_home_root_allowed_when_listed`：断言白名单内的家目录根现在被放行。
- FIXPLAN 中 A2 / 3.3 的 denylist 决策标注为已被本版推翻。

## 0.3.0（2026-11-12）

删除策略反转：从「只能由用户在网页上点、永久删除默认关闭」改为「Agent 可直接执行、永久删除默认开启」。这是一次**行为不兼容变更**，旧版的安全假设不再成立。

### 铁律（SKILL.md）

- 扫描阶段仍然全程只读，但删掉了「绝对禁止 del / rd / rmdir / 清空回收站」的禁令。
- 新增「清理可以由 Agent 直接执行，且默认允许永久删除」：网页按钮、`/action` 接口、Agent 直接跑命令三者等价，默认**不进回收站**。
- 新增「回收站可以清空」，允许 `Clear-RecycleBin` 立即释放空间。
- 「即使用户在对话里说"帮我删"，也引导他在网页上逐项确认」这条作废。

### 实现

- `server.py`：`ALLOW_RM` 默认改为 `True`；新增 `--no-allow-rm` 关闭；`--allow-rm` 保留为兼容参数。参数解析抽成 `build_parser()`，便于测试。
- 关闭永久删除时的 403 文案改为提示用 `--no-allow-rm`。
- 启动横幅区分「已启用（默认）」与「已关闭（--no-allow-rm）」。
- 报告模板在 `--no-allow-rm` 下的说明文案同步。
- **保持不变**：敏感目录 denylist（**0.3.1 已整体移除**，见下）、allowlist 按报告原始路径匹配、越界检查、token + Host 校验、junction 只删链接本身、逐项审计。
- 黄灯仍然「只能移回收站」，红灯仍然只能「打开目录」。

### 文档与测试

- README、SKILL.md（安全模型与排障表）、`references/analysis-guide.md`、`references/reporting-guide.md` 同步新语义。
- `test_rm_disabled_by_default` 改为 `test_rm_can_be_disabled_with_flag`（显式关闭时仍应 403）；新增 `test_cli_rm_default_on_with_opt_out` 覆盖命令行默认值与 `--no-allow-rm`；模板断言改为检查 `--no-allow-rm`。
- FIXPLAN 中 A1 / 3.2 两条决策标注为已被本版推翻，保留为历史快照。

## 0.2.1（2026-10-24）

路径安全复核修复，重点是两处 allowlist / 根目录判断与链接语义。

### 路径护栏

- 修复允许根带尾分隔符时的前缀判断：`--allow-root "D:\"` 不再把 `D:\Cache` 误判为越界，同时仍拒绝 `D:\Cache2`。
- allowlist 改为按报告里的原始路径匹配，不再按 realpath 后的目标匹配；报告列出的链接只授权链接本身，不会连带授权它指向的目录。
- 链接自身位置必须在允许根内，目标不受根目录限制；仍只删除链接，不递归目标。
- 悬空链接改用 `lexists` 判断存在性，删除后复核同样使用 `lexists`，不再误报 missing。
- 路径比较统一展开 8.3 短名（`GetLongPathNameW`，只换目录项名称、不解析链接），短名临时目录与长名用户目录可以互认，不会再误判“不在白名单 / 路径越界”。

### 测试

- 新增 7 项回归测试，覆盖盘符根、链接目标扩张、根外链接、链接只删自身、悬空链接、load 白名单来源、8.3 短名与长名等价；共 42 项。

## 0.2.0（2026-10-24）

第二轮可靠性加固，重点是把“宣称完整覆盖”“失败悄悄吞掉”“测试污染用户环境”这三类问题堵住。

### 扫描可信度

- `coverage` 新增 `caveats`、`limited`、`suspect`：Everything 索引覆盖无法独立验证时给出提示；WizTree 普通权限导出直接判 `partial=true`、`limited=true`，不再宣称完整覆盖。
- 扫描文件数为 0 但磁盘已用时判 `suspect=true`，报告页显示「结果可疑」，避免基于空结果出清理建议。
- `scan.py` 入口增加 `state/scan.lock` 跨进程锁，两个扫描不再同时写同一份 `scan_<盘符>.csv`；拿不到锁 1 秒后退出码 2。

### 删除与审计

- `audit.jsonl` 追加写加跨进程锁，多标签并发提交不会写坏行。
- 批量动作结束后追加一条 `action=batch` 汇总，含 `count` / `ok_count` / `failed` / `risk`，便于事后复盘。
- 回收站失败与取消新增 mock 测试，确认失败逐项返回、不降级为永久删除。

### 前端

- 批量与单项操作失败时，逐条列出失败路径与原因，不再只显示第一条错误。
- 扫描可信度区块展示 `caveats`，并标注「覆盖受限」「结果可疑」。

### 脚本接口

- `rules.py`、`orphan.py` 新增 `--out`，直接写 UTF-8 无 BOM 文件，规避 PowerShell `>` 的 BOM 问题。
- `orphan.py --csv` 支持多个 CSV，多盘环境可一次全传；`orphan.py` 在非 Windows 平台可导入，注册表证据标记为不可用。

### 测试与工程

- 真实回收站用例改为 `SA_REAL_RECYCLE=1` 才执行，默认跳过，避免污染用户回收站。
- 新增 HTTP 负向测试：缺 token、非法 mode、GET `/action`、`..` 穿越、非白名单路径。
- 新增 GitHub Actions：Ubuntu + Windows 矩阵跑语法检查与默认测试。
- 测试总数 35 项（默认执行 34 项，1 项真实回收站用例按需开启）。

### 文档

- README 增加 FAQ、测试隔离说明、Everything 索引覆盖限制、WizTree 普通权限覆盖说明。
- SKILL.md 增加「输出契约与异常处理」章节，明确各脚本失败时的表现与处理方式。
- 增量审计参考文档的命令示例统一改为 `--out`，并强调多盘 CSV 必须全传。
