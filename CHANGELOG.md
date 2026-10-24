# 变更记录

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
