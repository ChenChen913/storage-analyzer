---
name: storage-analyzer
description: >
  Windows / macOS 只读存储分析助手（自动识别系统）。扫描整机磁盘占用，找出
  占空间大户，把每一项分成 🟢可自动清理 / 🟡需人工判断 / 🔴谨慎清理 三级并给出
  可执行处置方案，生成排版精美、可折叠、命令可一键复制的交互式 HTML 报告，并可
  起本地服务在网页上一键删除（移回收站/直接删）。扫描全程只读。务必在以下场景
  使用：用户说"存储分析""磁盘满了""C盘/硬盘满了""空间不够""清理空间"
  "清理磁盘""占空间""哪些东西占地方""帮我看看存储""看一下电脑存储/空间"
  "存储空间""电脑空间不够""内存满了/不够/不足""看下内存/存储"（中文口语里
  "内存"常指存储空间）"storage analysis""disk cleanup""清缓存""磁盘清理"；
  或用户抱怨电脑没空间、想知道什么东西吃硬盘、想要清理建议时。注意：若用户明确
  指运行内存/RAM（如"哪个进程吃内存""内存占用高"想看任务管理器），那是 RAM
  不是存储，不属于本 skill。
---

# Storage Analyzer

对 Windows（主）/ macOS（次）做一次只读存储分析，产出交互式 HTML 报告。流程：扫描 → 增量审计 → 分析分级 → 生成网页 → 收尾。

## 按需阅读（渐进式披露）

主文件只保留流程骨架和硬性规则。遇到下表场景再加载对应文件，不要一次性全读。

| 场景 | 文件 |
|------|------|
| 确认命令、数据源选择、扫描降级、后台执行、批量 drilldown | [scan-workflow.md](references/scan-workflow.md) |
| 跑增量审计四件套（rules / orphan / apps / registry） | [incremental-audit.md](references/incremental-audit.md) |
| TopN 分析、三级分类、清理后复扫对比 | [analysis-guide.md](references/analysis-guide.md) |
| 写 analysis JSON、启动报告服务、静态报告、渲染排障 | [reporting-guide.md](references/reporting-guide.md) |
| 浏览器 / 微信 / QQLive 缓存逐目录判定、登录态核对 | [safe-cache-paths-windows.md](references/safe-cache-paths-windows.md) |
| Windows 命令报错、删除失败、权限、跨盘搬迁 | [pitfalls-windows.md](references/pitfalls-windows.md) |
| 用户要求“再全面深扫一遍 / 感觉漏东西” | [deep-scan.md](references/deep-scan.md) |
| 数据源覆盖与速度对比、Everything / WizTree 部署 | [data-source-comparison.md](references/data-source-comparison.md)、[everything-integration.md](references/everything-integration.md) |
| 系统存储布局、非系统盘、历史案例 | [windows.md](references/windows.md)、[macos.md](references/macos.md)、[non-system-drive-analysis.md](references/non-system-drive-analysis.md)、[lessons-learned-windows.md](references/lessons-learned-windows.md) |

## 铁律

- **全程只读（唯一例外见下一条）。** 只能跑扫描/统计/列目录/读元信息。绝对禁止 del、rd、rmdir、清空回收站、改权限等任何写操作。
- **扫描中间产物必须收尾清理。** `scan.py` 会在 `%TEMP%` 生成 `scan_<盘符>.csv`（单盘 100-250MB，多盘可达 1GB+），还可能留下 `.wiz` 残留。这些文件是 Step 1.5 和 `--reuse-csv` 复扫的必需输入，**扫描后到报告交付前不得删除**；本轮分析彻底结束、用户确认不再复扫后，必须主动询问是否删除（流程见 Step 5）。只删自己命名的 `scan_*.csv` / `scan_*.csv.wiz`，`%TEMP%` 下其他文件一律不碰。
- **删除命令只展示，不执行。** 报告里的清理命令供用户自己确认后运行。即使用户在对话里说“帮我删”，也要先停下确认（命中全局红线：删除文件必须先问），不要直接代跑。
- **浏览器 / 应用缓存只删纯缓存。** 登录态文件（`Cookies`、`Login Data`、`Web Data`、`Bookmarks`、`Extensions`、`Preferences`、`History`）一条都不能丢；逐子目录判定见 [safe-cache-paths-windows.md](references/safe-cache-paths-windows.md)。
- **估算标注清楚。** 涉及“可释放空间”一律说明是估算值。
- **路径、命令保留原文不翻译。**
- **JSON 必须匹配模板 schema。** 字段名和结构严格对照 `scripts/build_report.py` 顶部注释——`green`/`yellow`/`red` 是顶层数组（不是嵌套在 `tiers` 下），字段名用 `size_estimate`/`kill_processes`/`commands`/`content_profile`/`why_manual`/`disposal`/`why_keep`/`indirect_release` 等。模板是 `assets/report_template.html`，不存在“模板不对”，只有“JSON 格式不匹配”。生成后先用 `server.py` 验证：看到“绿灯可删 N 项”即表示解析成功。
- **报告用网址提供，不生成桌面文件。** 始终通过 `server.py` 起本地服务，用 `browser_navigate` 打开 `http://127.0.0.1:PORT/`。绝不在桌面或任何位置生成静态 HTML，除非用户明确说“给我一份离线留存的文件”。
- **已清理项不再展示。** 用户授权清理后重新生成报告时，已清理的绿灯项直接从 JSON 移除。🟡/🔴 不受此限（它们代表“决策”而非“可执行操作”）。例外：用户明确说“把清理过的也列出来看看”。
- **跨轮记忆（v3）。** 每轮结束必须跑 `registry.py baseline`；分析中每个 ≥20MB 目录的定性必须用 `registry.py mark` 写回；下轮从 `registry.py diff` 的增量清单开始，没跑 diff 就开始分析视为流程违规。
- **成套清理由规则引擎兜底（v3）。** 清理候选必须先跑 `rules.py` 拿成组结果，agent 只做复核定性。禁止按文件名模式手工挑文件——实战教训：手工挑了 9 个 lingma zip，同目录 28 个同类 zip 漏网，下一轮成了“新发现”。
- **审查顺序由应用登记表驱动（v3）。** 每轮先跑 `apps.py build`，把「未审查应用清单」排在 TopN 之前；看完一个应用立刻 `apps.py mark` 写回。

## 执行流程

### Step 0 确认 Python 命令（Windows 特有）

依次尝试 `python --version`、`py -3 --version`、`python3 --version`，记住可用的那个，后续命令用它替换。三者都失败时提示用户先安装 Python 3（https://www.python.org/downloads/windows/，勾选“Add Python to PATH”）。macOS 自带 `python3`，跳过此步。

### Step 1 扫描（只读）

Windows 数据源自动降级：**Everything → WizTree → walk**，三者导出都归一成同一份 `"路径",大小` CSV，后续聚合完全一致。

- **已装哪个就用哪个。** `--source auto` 自动优先 Everything、其次 WizTree。
- **两个都没装：推荐先装 Everything**（免费、普通权限就能全盘覆盖、重复扫描秒级）。只装 WizTree 时普通权限会漏 WindowsApps 等目录，精确统计需在提权终端加 `--wiztree-admin`。
- **都没有又暂时不装：** 回退 walk，百万文件级要几十分钟，只适合应急。

```bash
# Windows：全部固定盘一次分析
python scripts/scan.py --out "%TEMP%\storage_scan.json"
# macOS
python3 scripts/scan.py > /tmp/storage_scan.json
```

必须确认输出里有 `coverage`（`method` = everything / wiztree / walk，混用形如 `everything+walk`；含 `es_path` / `wiztree_path` / `drives` / `files_scanned`）。全盘清单 + 大文件 TopN 是“不遗漏”的最低保障，只基于固定目标列表的分析视为不完整。

指定盘 / 调整阈值 / 强制数据源 / 并行 drilldown / git-bash 后台失败时的 `execute_code` 兜底，见 [scan-workflow.md](references/scan-workflow.md)。扫描耗时：Everything 约 18 秒/盘，walk 数分钟到数十分钟。

### Step 1.5 增量审计（v3，每轮必跑，仅 Windows）

```bash
python scripts/rules.py --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv" > rules_hits.json
python scripts/orphan.py --csv "%TEMP%\scan_C.csv" --min-mb 50 > orphans.json
python scripts/apps.py build --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
python scripts/apps.py list --unreviewed --min-mb 20
python scripts/registry.py diff --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
```

- **分析顺序**：未审查应用清单 > diff 增量 > orphans > rules 命中组 > 全量 TopN 兜底。
- 每个定性目录立刻 `registry.py mark <路径> <green|yellow|red|keep> "<理由>"`；每个看完的应用立刻 `apps.py mark <key> --note "<结论>"`。
- 首轮先 `registry.py baseline`；分析结束后再跑一次固化本轮状态。
- **多盘 CSV 必须全传**，只传 C 盘会把 D 盘目录误标成“已删除”。macOS 无 CSV 通路，跳过本步。
- 完整说明与输出字段见 [incremental-audit.md](references/incremental-audit.md)。

### Step 2 分析与分级

先按 `system.os` 读 [windows.md](references/windows.md) 或 [macos.md](references/macos.md)。以下六条强制流程不可跳过：

1. **建全量目录树**：用 CSV 在内存中构建完整目录树，≥15MB 节点无阈值展开；禁止只依赖 scan.py 的 TopN。
2. **总账核对**：CSV 总量 vs `shutil.disk_usage` 实占 vs 目录树加总，三方必须对平；差额解释不了就是漏项。
3. **定性先看内容**：禁止凭目录名推断用途；`recordings/photos/docs` 默认视为用户数据进黄灯。
4. **清理成套**：浏览器缓存六件套 = Cache + Code Cache + GPUCache + Service Worker + Shared Dictionary + DawnCache，漏一个就是下一轮的“新发现”。
5. **清理后必须重新导出 CSV 复扫**，逐项确认真的没了。
6. **登录态逐文件快照核对**：删前后对比 `Network\Cookies` / `Login Data` / `Web Data` / `Bookmarks`。

三级分类是清理决策清单，不是全盘点。没有“要不要动它”决策的项（正常应用、系统本身、海量小文件）不进三灯，归磁盘条的蓝色“系统及其他”。

- 🟢 **可自动清理**：纯缓存、临时文件、安装包残留、明确可再生且不影响功能、不丢用户数据。每项给预估释放空间、需关闭的进程、可复制命令。
- 🟡 **需人工判断**：含用户数据或有判断成本（下载的视频/文档、大型应用数据、聊天记录、node_modules）。给内容画像 + 至少 3 句处置路径 + 风险提示；有核实过的安全子路径时给 `trash_paths`，网页只允许“移到回收站”，绝不给直接删除。
- 🔴 **谨慎清理**：想动但不建议手删的项（重复安装的应用、想卸载的大应用、运行中应用的核心数据）。写清“为什么不建议手删” + 具体卸载步骤；应用项给 `app_paths` 供打开安装目录。红灯不给删除/卸载按钮。系统文件（WinSxS、pagefile.sys、hiberfil.sys）绝不单独列红卡。

🟢 候选必须用 `drilldown.py` 深入 2-3 层，把纯缓存和用户数据分开，逐目录判定读 [safe-cache-paths-windows.md](references/safe-cache-paths-windows.md)。`size` / `size_estimate` 写成“约 14 GB”即可，不要再加“（估算）”。分析细节、清理命令写法、清理后前后对比脚本见 [analysis-guide.md](references/analysis-guide.md)。

### Step 3 生成交互报告

把分析结果写成 analysis JSON（schema 见 `scripts/build_report.py` 顶部注释）。报告会自动读取 `state/last_diff.json` 和 `state/registry.json` 标注「新发现 / 删后复发」，所以**必须先跑 `registry.py diff`**；静态模式可用 `--no-history` 关闭。

**🟢 项必须带 `trash_paths`**（具体可删的绝对路径数组，Windows 用反斜杠，必须在 `%USERPROFILE%` 内）——漏了网页删除按钮就不出现。

```cmd
python scripts\server.py %TEMP%\storage_analysis.json     # Windows
```

```bash
python3 scripts/server.py /tmp/storage_analysis.json       # macOS
```

`server.py` 起在 127.0.0.1 + 随机端口 + 随机 token，自动打开浏览器。安全模型：`rm` 只允许绿灯 `trash_paths`；`trash` 允许绿灯+橙灯；`open` 再加橙灯 `path`；所有请求 realpath + `$HOME` + token + Host 校验，每次点击先 confirm。

启动流程、静态报告、排版字段（`summary.overview`、`tier_stats`、进度条分段）、无按钮排障见 [reporting-guide.md](references/reporting-guide.md)。

### Step 4 对话里给摘要

报告生成后，在对话里用一段话给结论先行的摘要：总可释放估算、最该先清的 2-3 项、风险最高的一项。细节让用户看网页。

### Step 5 收尾：处理扫描中间产物（每轮必做）

扫描后不能立刻删 `scan_<盘符>.csv`——Step 1.5 和复扫都依赖它。删除时机：

1. 报告已交付、用户确认不再重出报告、也没有“清理后再复扫对比”的计划 → 默认删除点，主动询问。
2. 用户还要复扫或做前后对比 → 保留到复扫结束再提醒。
3. 用户事先授权“不用问，直接删” → 到默认删除点直接删；否则每次先问。

提醒时说真实体量，例如：“本轮扫描在 `%TEMP%` 留下了 scan_C.csv、scan_D.csv，合计约 420 MB，现在已经不需要了。要我删掉吗？如果打算清理后再扫一遍做对比，可以先留着，等复扫完我再提醒你删。”

- 删除前读扫描 JSON 的 `temp_artifacts`，按实际大小汇报，不要凭印象估。
- 只删精确匹配 `%TEMP%\scan_<盘符>.csv` 和 `scan_<盘符>.csv.wiz` 的文件；`%TEMP%` 下其他文件一律不碰。
- 删除后告知实际释放量；保留则告知位置、总体量和下次删除时机。
- macOS 只有调用方保存的 scan JSON（如 `/tmp/storage_scan.json`），同理在本轮结束后询问。

## 依赖与运行前提

- 全部脚本是 **Python 3 标准库**，零第三方依赖（不用 pip install）。
- **Windows**：默认没装 Python，需先安装 Python 3；命令用 `python` 或 `py -3`（不是 `python3`）。**macOS**：自带 `python3`、`du`、`diskutil`、`osascript`，开箱即用。
- 本 skill 是 **agent 驱动**：扫描出数据后由 agent 做分级分析，不是双击即用的独立 App。

## 平台状态

- **Windows**：已验证（Windows 10/11 + Python 3.11 + git-bash）。`scan.py` v2/v3 已实测 Everything、WizTree、walk 三种数据源与增量审计；`server.py` 报告渲染正常，回收站操作待后续实测验证。
- **macOS**：完整实现并实测（扫描 / 报告 / 一键删除全验证过）。
- 详细踩坑见 [lessons-learned-windows.md](references/lessons-learned-windows.md)，历史案例见 [win11-case-study-20260603.md](references/win11-case-study-20260603.md)、[win11-cleanup-case-20260618.md](references/win11-cleanup-case-20260618.md)、[win11-optimization-case-20260715.md](references/win11-optimization-case-20260715.md)。
