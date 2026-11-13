# facts.md

> README 的唯一事实来源。A 部分由 AI 扫描生成后人工核对；B 部分必须手写。
> 本项目没有 `package.json` / `pyproject.toml`，因此「description / version / author」三个字段无自动来源。

## A. 可自动提取的事实

1. **项目类型**：Agent Skill（宿主为支持 `SKILL.md` 的 AI Agent），附带 11 个 Python 命令行脚本。不是 npm 包、不是库、没有 `package.json`。

2. **主语言 / 运行时 / 最低版本**：
   - Python 3，**仅标准库，零第三方依赖**（无 `requirements.txt` / `pyproject.toml`）
   - 代码中没有 `sys.version_info` 或 `python_requires` 版本校验
   - 测试过的版本：Python **3.11**（CI 矩阵）、**3.13.3**（本机实测）
   - 验证命令：`Get-Content .github/workflows/tests.yml`（`python-version: ["3.11"]`）；`python --version` → `Python 3.13.3`

3. **安装命令**：未知 —— 仓库未提供安装脚本，也未说明 Skills 目录约定。

4. **运行命令**（逐字取自 `scripts/scan.py --help` 与 SKILL.md）：
   - 扫描：`python scripts/scan.py --out "%TEMP%\storage_scan.json"`
   - 报告服务：`python scripts/server.py "%TEMP%\storage_analysis.json"`

5. **测试命令**：`python -m unittest discover -s tests -v`
   - 验证输出：`Ran 43 tests in 2.109s` / `OK (skipped=2)`

6. **构建命令**：无（纯 Python 脚本，无构建步骤；CI 只跑 `python -m py_compile scripts/*.py`）。

7. **目录结构**（仓库根，三层内）：
   - `SKILL.md` — Skill 入口与流程定义（191 行）
   - `scripts/` — 11 个 Python 脚本（扫描 / 规则 / 卸载残留 / 应用登记 / 档案 / 服务 / 报告 / 工具）
   - `references/` — 16 篇按场景拆分的参考文档
   - `assets/report_template.html` — 报告模板
   - `tests/test_storage_analyzer.py` — 单测（768 行）
   - `state/` — 运行时状态（`.gitignore` 已忽略，不入库）
   - `CHANGELOG.md` / `FIXPLAN.md` / `NOTICE` / `LICENSE`

8. **主要依赖**：无第三方依赖。依赖的外部可执行程序（可选）：
   - `es.exe`（Everything）—— 首选数据源，命令：`grep -n 'es.exe' scripts/scan.py`
   - `WizTree64.exe`（WizTree）—— 次选数据源
   - 两者都没有时回退 `os.scandir` 全盘遍历（`walk`）

9. **环境变量 / 配置项**：

   | 名称 | 必填 | 默认值 | 说明 | 代码位置 |
   |---|---|---|---|---|
   | `STORAGE_ANALYZER_STATE` | 否 | `<repo>/state` | 覆盖状态目录 | `scan.py:32`、`server.py:52`、`registry.py:30`、`apps.py:35`、`history.py:17` |
   | `STORAGE_ANALYZER_WIZTREE` | 否 | 自动探测 | 指定 WizTree 可执行文件路径（便携版用） | `scan.py:266`（`WIZTREE_ENV`） |
   | `TEMP` / `TMP` | 否 | 系统临时目录 | 扫描中间 CSV 落盘位置 | `scan.py`、`rules.py:76`、`registry.py:39`、`apps.py:330` |

10. **CLI 子命令 / 参数**（逐字取自 `add_argument`）：

    | 脚本 | 主要参数 |
    |---|---|
    | `scan.py` | `--drives`、`--source {auto,everything,wiztree,walk}`、`--no-everything`、`--wiztree-admin`、`--reuse-csv`、`--min-dir`、`--big`、`--cache`、`--updater`、`--ver`、`--top`、`--out` |
    | `server.py` | `src`、`--allow-rm`（默认开）、`--no-allow-rm`、`--allow-root PATH`（可重复）、`--no-browser`、`--port` |
    | `rules.py` | `--csv`（可多值）、`--min-mb`、`--out` |
    | `orphan.py` | `--csv`（可多值）、`--min-mb`、`--out` |
    | `registry.py` | `baseline` / `diff` / `mark <path> {green,yellow,red,keep} <note>` / `stats`；`--csv`、`--min-mb` |
    | `apps.py` | `build` / `list` / `mark <key>`；`--csv`、`--unreviewed`、`--min-mb`、`--json`、`--note` |
    | `drilldown.py` | 位置参数（路径）、`--min-mb`、`--limit` |
    | `build_report.py` | `src`、`out`、`--diff`、`--registry`、`--no-history` |

11. **已有文档**：`SKILL.md`、`references/` 16 篇、`CHANGELOG.md`（0.2.0 → 0.3.1）、`FIXPLAN.md`、`NOTICE`、`LICENSE`(MIT)。

12. **仓库 / 版本 / 许可**：
    - 仓库：`https://github.com/ChenChen913/storage-analyzer.git`（`git config --get remote.origin.url`）
    - 版本：`0.3.1`（`CHANGELOG.md` 首行 `## 0.3.1（2026-11-12）`）
    - 许可：MIT，`Copyright (c) 2026 数字生命卡兹克`（`LICENSE` 第 3 行）
    - 上游：`https://github.com/KKKKhazix/khazix-skills`（`NOTICE` 第 5 行）

13. **CI**：`.github/workflows/tests.yml`，Ubuntu + Windows 矩阵，Python 3.11，跑 `py_compile` 与 `unittest`。徽章可用：
    `https://github.com/ChenChen913/storage-analyzer/actions/workflows/tests.yml/badge.svg`

14. **验证过的边界事实**（可用于「已知限制」）：
    - Linux 不支持：`scan.py` 返回 `unsupported_platform`（SKILL.md「平台状态」）
    - macOS 分支未复验（SKILL.md / NOTICE 均写明）
    - 非管理员权限下 WizTree 漏 WindowsApps 等受保护目录（`coverage.limited=true`）
    - 网页删除默认根仅为 `%USERPROFILE%` 与 `Program Files`，跨盘需 `--allow-root`
    - 0.3.1 起无敏感目录黑名单（`grep -n 'sensitive_paths' scripts/server.py` 无结果）

## B. 需人工补充（必填）

- **一句话描述**（< 120 字符）：给 AI Agent 用的全盘存储分析 Skill：扫描 → 三灯分级 → 网页一键删除（含永久删除）。
- **为什么做这个项目**：想要一个能被 Agent 直接调用、跨轮记住结论的清理工具，而不是又一个 GUI。
- **目标用户 / 前置知识**：中文技术社区 / X 上的同行；会自己装 Skill、会看代码，不需要解释基础概念。
- **与同类方案的差异**：跨轮记忆——`registry.py diff` 让下一轮只处理增量，不重复劳动。
- **已知限制 / 明确不做的事**：采用 A 第 14 条列出的可验证项（Linux 不支持、macOS 未复验、非管理员权限盲区、跨盘需 `--allow-root`、0.3.1 起无敏感目录黑名单、不提供一键全自动清盘）。
- **演示素材路径**（截图 / GIF）：无。仓库内没有任何图片文件，首屏改用 Mermaid 流程图 + 终端实录。
- **目标读者画像**：想给本地 Agent 加一个「能真的动手清理」能力的开发者。
- **期望读者读完能做什么**：能独立跑完 scan → 审计四件套 → server 报告这条链路，并知道三灯各能做什么。
- **备注**：`SKILL.md` 的 `description` 字段是给 Skill 路由用的触发词长文本（约 500 字符），不能当 README 的一句话描述用；本项目也没有 `package.json`，因此「描述与 package.json 逐字一致」这条无对应字段，改为与本文 B 段一致。

## 核对记录

- [x] 所有命令实际执行过（`--help` / `unittest` / `grep`）
- [x] 所有环境变量在代码中能搜到（附行号）
- [x] 目录结构与实际一致
- [x] 无臆造项（未知项已标注）
- [x] B 部分已由用户确认（2026-11-12）
