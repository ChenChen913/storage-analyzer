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

对 Windows（主）/ macOS（次）做一次只读存储分析，产出交互式 HTML 报告。流程：扫描 → 分析分级 → 生成网页 → 打开。

## 铁律

- **全程只读。** 只能跑扫描/统计/列目录/读元信息。绝对禁止 del、rd、rmdir、清空回收站、改权限等任何写操作。
- **删除命令只展示，不执行。** 报告里给出的清理命令是供用户自己在终端确认后运行的。即使用户在对话里说"帮我删"，也要先停下确认（命中全局红线：删除文件必须先问），不要直接代跑。
- **估算标注清楚。** 涉及"可释放空间"一律说明是估算值。
- **路径、命令保留原文不翻译。**
- **JSON 必须匹配模板 schema。** 分析 JSON 的字段名和结构必须严格对照 `scripts/build_report.py` 顶部注释的 schema——`green`/`yellow`/`red` 是顶层数组（不是嵌套在 `tiers` 下），字段名用 `size_estimate`/`kill_processes`/`commands`/`content_profile`/`why_manual`/`disposal`/`why_keep`/`indirect_release` 等，不要自己发明字段名。模板文件是 `assets/report_template.html`，所有报告都走它渲染，不存在"模板不对"的问题，只有"JSON 格式不匹配"。生成 JSON 后先用 `server.py` 前台抓 URL 验证——看到"绿灯可删 N 项"即表示 JSON 被正确解析，然后才给用户看。
- **报告用网址提供，不生成桌面文件。** 始终通过 `server.py` 启动本地服务，用 `browser_navigate` 打开 `http://127.0.0.1:PORT/` 网址给用户。绝不在桌面或任何位置生成静态 HTML 文件，除非用户明确说"给我一份离线留存的文件"。
- **已清理项不再展示。** 用户授权清理后、重新生成报告时，已清理的绿灯项直接从 JSON 中移除，不再出现在网页上——既然已经清了，没理由还占着版面。🟡/🔴 不受此限（它们代表"决策"而非"可执行操作"）。唯一的例外：用户明确说"把清理过的也列出来看看"。
- **跨轮记忆（v3 新增）。** 每轮分析结束必须跑 `registry.py baseline` 更新档案；分析中每个 ≥20MB 目录的定性结论必须用 `registry.py mark` 写回。下轮分析从 `registry.py diff` 的增量清单开始，而不是从头全量重看。没有跑 diff 就开始分析，视为流程违规。
- **成套清理由规则引擎兜底（v3 新增）。** 清理候选清单必须先跑 `rules.py` 拿成组结果，agent 只做复核定性。禁止按文件名模式手工挑文件——实战教训：手工挑了 9 个 lingma zip，同目录 28 个同类 zip 漏网，下一轮成了"新发现"。

## 执行流程

### Step 0 确认 Python 命令（Windows 特有）

**Windows 默认没装 Python，且命令因安装方式不同而异。** 在 Windows 上运行脚本前，先确认：
```
python --version   # 若成功，用 python
py -3 --version    # 若成功，用 py -3
python3 --version  # 较少见，但也可能
```
记住哪个命令可用，后续所有示例中 `python3` 均替换为该命令。若三者都失败，提示用户先安装 Python 3（https://www.python.org/downloads/windows/，安装时勾选"Add Python to PATH"）。

macOS 自带 python3，无需此步。

### Step 1 扫描（只读）—— 全盘覆盖优先，Everything 加速

**速度是体验的核心。** Windows 上 scan.py v2 采用**数据源插件化**：

1. **Everything 优先（推荐）**：自动探测 `es.exe`（`D:\Everything\es.exe`、`C:\Everything\es.exe`、Program Files、PATH），探测到即导出全盘文件清单（实测 350 万文件 5-6 秒/盘），单次遍历同时产出：目录聚合(2/3 层)、大文件 TopN、安装包、缓存目录、更新器目录、多版本目录。**实测整盘分析 ~18 秒**。
2. **回退 os.scandir 全盘遍历**：无 Everything 时自动回退，保证"全盘覆盖"而非固定目标列表（慢，30-90 分钟/盘，大磁盘强烈建议装 Everything）。

**Windows（Everything 可用时）：**
```bash
# 全部固定盘一次分析（C/D/E...），写文件避免 stdout 编码问题
python scripts/scan.py --out "%TEMP%\storage_scan.json"
# 只扫指定盘 / 调整阈值
python scripts/scan.py --drives C,D --top 50 --min-dir 20 --out "%TEMP%\storage_scan.json"
# 强制 walk 回退（排查用）
python scripts/scan.py --drives C --no-everything --out "%TEMP%\storage_scan.json"
```

**Windows（无 Everything / 需 drilldown 时）：**
```bash
# C 盘：scan.py（Everything 不可用时走全盘 walk）
python scripts/scan.py --drives C --out "C:\Users\<user>\AppData\Local\Temp\storage_scan.json" &
# D/E 盘等：drilldown.py 做顶层分析（比全量递归快 10 倍以上）
python scripts/drilldown.py "D:/" --min-mb 100 --limit 30 > "C:\Users\<user>\AppData\Local\Temp\d_scan.json" &
wait
```

两步同时跑，总等待时间 = max(scan.py, drilldown)，而非两者之和。

**覆盖保证（防止"漏盘/漏项"）：** 每轮分析必须确认输出里有 `coverage` 字段（method=everything|walk、drives 列表、files_scanned 文件数）。全盘清单 + 大文件 TopN 兜底是"不遗漏"的最低保障；只基于固定目标列表的分析一律视为不完整（教训见 [references/lessons-learned-windows.md](references/lessons-learned-windows.md) 4.1）。

**大磁盘加速建议：** Everything 索引常驻，扫描成本≈0；无 Everything 时用多进程按盘根分片（SSD 近线性）+ `os.scandir` + 先粗后细。子 Agent 建议用于"多维度并行分析"而非 IO 扫描（瓶颈在磁盘）。详见 [references/everything-integration.md](references/everything-integration.md)。

**⚠️ git-bash 后台模式 + 文件重定向可能静默失败**：在 git-bash 中用 `terminal(background=true)` + `>` 重定向跑 Python 脚本时，输出文件可能始终为 0 字节（进程跑了 4+ 分钟但文件为空）。这是 git-bash 后台模式 + stdout 缓冲的已知问题。**如果后台模式输出文件为空，立即改用 `execute_code` + `subprocess.run(capture_output=True)`**（见下方 pitfall）。`execute_code` 方式同样支持并行——先发 C 盘 scan，再在同一脚本里把 D 盘 drilldown 也跑上，或用两个 `execute_code` 并行调用。

```python
# execute_code 可靠写法（替代后台 terminal）
import subprocess
script = "C:/Users/.../scan.py"
result = subprocess.run(["python", "-u", script], capture_output=True, text=True, timeout=300)
with open("C:/Users/.../Temp/storage_scan.json", "w", encoding="utf-8") as f:
    f.write(result.stdout)
```

**第二步：所有 drilldown 并行批处理（每批 6 个）**
不要逐条 drill——把 10-20 个目标目录一次 6 个批量发出，每轮等待最慢的那个，3-4 轮搞定。实测从逐条 ~120s 降到 ~40s。

**macOS：**
```bash
python3 scripts/scan.py > /tmp/storage_scan.json
```

macOS 单盘（/），`du` 速度快，但多卷（外置盘等）同理并行。

`scan.py` 自动识别系统（`sys.platform`）：
- **Windows**：全盘清单（Everything 优先，回退 os.scandir 全盘遍历），单遍聚合 drive_root(depth2/3)、big_files、installers、cache_dirs、updater_dirs、version_dirs、recycle_bin、dev_caches、running_apps；`system.disks` 含所有盘符（C:、D:……）；输出含 `coverage`（method/drives/files_scanned）。
- **macOS**：扫 home、library、caches、containers、group_containers、app_support、applications、downloads、dev_caches，用 `du` 算大小。

输出 JSON：`system`（系统/磁盘信息，含 `disk_name` 主盘名 + `disks` 全部盘）+ `groups`（各组子目录大小，已降序、过滤阈值以上）+ `coverage`（扫描方法/覆盖盘/文件数）+ `_hierarchy`（groups 间的父子包含关系，标注哪些组是其他组的子集，防止分析时重复统计）。读不到的目录标 `denied`，需在报告里列出并提示遗漏体量。

- **Windows 扫描耗时**：Everything 后端 ~18 秒/盘；walk 回退数分钟到数十分钟（百万文件级）。先告知用户预计时间。

> **Windows git-bash 环境特殊注意事项（重要）：**
> 1. **`rd /s /q` 不可用**：`rd` 是 cmd.exe 内置命令，git-bash 不识别。替代方案：`cmd //c "rd /s /q <path>"` 或直接用 `rm -rf "/c/Users/..."`（MSYS 路径格式）。优先用 `rm -rf`，更简洁。
> 2. **`$TEMP` 路径差异**：git-bash 的 `$TEMP` 指向 `/tmp`，但 `server.py` 内部用 Python 的 `os.path` 解析，可能找不到。写分析 JSON 时统一用 `C:\tmp\...` 或 `C:\Users\...\AppData\Local\Temp\...` 这样的 Windows 绝对路径。用 `cygpath -w "/tmp/file.json"` 可查看对应的 Windows 路径。
> 3. **`du -sh` 超时**：对大目录（如 node_modules）运行 `du -sh` 会超时。改用 `du -sm` 加深度限制，或直接用 `drilldown.py`。
> 4. **`server.py` 前台抓 URL**：后台模式 stdout 不显示，必须先 `timeout=15` 前台运行拿到 URL，再用 `background=true` 重启到同一端口。`Ctrl+C` 停前台时会自动释放端口。

> **回收站扫描需要管理员权限**

### Step 1.5 增量审计（v3 新增，每轮必跑）

扫描完成后、人工分析开始前，依次跑三个增量工具。它们解决的是六轮实战暴露的结构性问题：跨轮失忆、成套清理失败、卸载残留无人认领。

```bash
# 1) 规则引擎：成组命中清理候选（plugins zip 组 / 多版本 bin / 崩溃转储 / 巨型日志）
python scripts/rules.py --csv "%TEMP%\scan_C.csv" > rules_hits.json
# 输出的 green_candidates / multi_version_groups 直接进分析流程，agent 只复核不定性枚举

# 2) 卸载残留检测：数据目录存在但应用本体已不在（Programs/Program Files/开始菜单/卸载注册表四重比对）
python scripts/orphan.py --min-mb 50 > orphans.json
# 输出自动附最后活动时间，days_idle 大的是高置信度弃用候选（Kiro 案例：90 天 + 本体不存在）

# 3) 档案 diff（第二轮起）：与历史基线对比，只看增量和未定性项
python scripts/registry.py diff --csv "%TEMP%\scan_C.csv"
# 输出：新目录 / 增大≥50MB / 删后复活(活水缓存) / 未定性 / 超30天无活动的未定性目录
```

**首轮**：先跑 `registry.py baseline` 建档（采集全量目录大小 + 两层 mtime 活跃度），再跑 rules 和 orphan。
**分析顺序**：diff 增量清单 > orphans（弃用嫌疑最大）> rules 命中组 > 全量 TopN 兜底。优先看「谁没被审过」，而不是「谁大看谁」。
**分析过程中**：每个定性的目录立刻 `python scripts/registry.py mark <路径> <green|yellow|red|keep> "<一句话理由>"` 写回档案。
**分析结束后**：再跑一次 `registry.py baseline` 固化本轮状态（含复活检测）。

三个脚本的完整用法与设计说明：`scripts/registry.py` / `scripts/rules.py` / `scripts/orphan.py` 文件头注释。规则表可持续追加到 `scripts/rules.py` 的 RULES 区（每轮实战新学到的模式，如某 IDE 的特殊缓存名）。

### Step 2 分析与分级

**⚠️ 强制流程（2026-08-21 四轮实战教训，详见 references/lessons-learned-windows.md 第 6 节）：**

1. **建全量目录树**：用 Everything CSV 在内存中构建完整目录树并**无阈值逐层展开**（≥15MB 节点全部打印），禁止只依赖 scan.py 的聚合 TopN——它连续三轮漏掉了用户目录下约 8GB 的 AI 工具点目录。对每个陌生目录下钻验尸到能解释每个字节。
2. **总账核对**：Everything 总量 vs `shutil.disk_usage` 实占 vs 目录树加总，三方必须对平；差额要能解释（硬链接/NTFS 压缩/MFT），解释不了就是漏项。
3. **目录定性先看内容**：禁止凭目录名推断用途（实锤：TRAE SOLO 实为 Trae CN 数据、recordings 是用户录音不是模型、XiuXiu 缓存在 QtWebEngine 子目录）。`recordings/photos/docs` 默认视为用户数据进黄灯。
4. **清理成套**：浏览器缓存六件套 = Cache + Code Cache + GPUCache + Service Worker + Shared Dictionary + DawnCache，漏一个就是下一轮的"新发现"。
5. **清理后必须重新导出 CSV 复扫**，逐项确认真的没了。
6. **登录态逐文件快照核对**：删前后对比 `Network\Cookies`/`Login Data`/`Web Data`/`Bookmarks` 的存在与大小。

先看 `system.os` 判断系统，读对应的数据布局参考：Windows 读 [references/windows.md](references/windows.md)，macOS 读 [references/macos.md](references/macos.md)（讲该系统东西存哪、怎么辨认、归哪一级）。**对浏览器 profile / 应用数据目录做 🟢 分类时，必须读 [references/safe-cache-paths-windows.md](references/safe-cache-paths-windows.md)**，它给出了 Edge/Chrome、微信、QQLive 等常见应用的逐子目录安全判定表。然后读扫描 JSON 做这几件事：

1. **挑 Top 5** 占用大户，判定类型（系统文件/应用本体/应用数据/应用缓存/开发缓存/用户文件/媒体内容/下载内容/虚拟机镜像/回收站/其他）。

2. **识别"神秘大目录"（并行批处理）**：对于 groups 中任何一个大于 1GB 的陌生目录，用 `drilldown.py` 深入一层。**不要逐条调用——每批 6 个并行发出**，每轮等最慢的那个返回。通常 3 轮搞定 15-20 个目录，比串行快 3-4 倍。
   ```cmd
   python scripts\drilldown.py <路径> [--min-mb 100] [--limit 20]
   ```
   输出 JSON 包含每个子项的名称、大小、是文件还是目录——比 agent 手写 Python 更可靠高效。

   - **Windows**：`%LOCALAPPDATA%` 下不认识的大目录、UUID 命名的容器；`%APPDATA%` 下异常大的配置目录。
   - **macOS**：UUID 命名的 Container。
   - 仍只读，别动文件。

3. **注意 `_hierarchy` 去重**：`scan.py` 输出的 groups 之间存在父子包含（如 Windows 的 `user_profile` 包含 `appdata_local`、`appdata_roaming`、`dev_caches` 等）。分析时先读 `_hierarchy` 了解层级关系，统计总占用时只算顶层组（`parent=None`），子组用于深入分析具体构成。

4. **多盘都要分析**：`system.disks` 列出所有盘符。如果非系统盘（D:、E: 等）使用率 >80% 或绝对已用量 >100GB，在报告中为它单独加一个分析段落——列出该盘的大目录、给清理建议。不要只盯着 C 盘。详见 [references/non-system-drive-analysis.md](references/non-system-drive-analysis.md)。

5. **三级分类 = 清理决策清单，不是全盘点。** 只把"存在'要不要动它'这个决策"的项放进三灯；日常在用的正常应用、操作系统本身、海量零碎小文件没有清理决策，不进三灯，它们落在磁盘条的蓝色"系统及其他"里。判定标准：
   - 🟢 **可自动清理**：纯缓存、临时文件、安装包残留、明确可再生且不影响功能、不丢用户数据（`%TEMP%`、浏览器缓存、pip/npm/.gradle 等开发缓存、下载文件夹里的 .exe/.msi 安装包）。
   - 🟡 **需人工判断**：含用户数据或有判断成本（下载的视频/文档、`%APPDATA%` 里的大型应用数据、聊天记录、项目代码 node_modules）。给内容画像 + 至少 3 句处置路径（应用内清理 / 系统工具 / 文件管理器手动审查，三选最合适）+ 风险提示。**所有橙灯项在服务模式下自动有「在资源管理器打开」按钮**（跳过去自己审查删）；如果该项有一个核实过、删了不破坏 App 的安全子路径，给它 `trash_paths` → 网页出现「移到回收站」按钮（橙灯只准移回收站、可逆，绝不给"直接删除"）。按钮下方会自动写明注意事项。
   - 🔴 **谨慎清理（有决策但不建议手删）**：你可能想动、但建议别手删的具体项——重复安装的应用、想卸载的大应用、运行中应用的核心数据等。给"为什么不建议手删" + `indirect_release` 写**具体卸载步骤**（控制面板卸载 / 设置 > 应用 / 软件自带卸载器 / Store 应用直接卸载等，要可照做不是空话）。应用项给 `app_paths`（真实可执行文件或安装目录绝对路径数组）→ 网页出现「在资源管理器打开（去卸载）」按钮。**红灯不给删除/卸载按钮**。**系统文件（WinSxS、pagefile.sys、hiberfil.sys）绝不单独列红卡**，归蓝色，间接释放技巧写进 `summary.long_term`。

每个 🟢 项要给：预估释放空间、清理前需关闭的进程、可一键复制的清理命令。

**Windows 🟢 清理命令优先选安全方式：**
- 临时文件：`del /q /f /s "%TEMP%\*"` 或直接在资源管理器删
- 浏览器缓存：浏览器内 Ctrl+Shift+Del 清理，或给出具体缓存路径供删除
- 开发缓存：`npm cache clean --force`、`pip cache purge`、`gradle cleanBuildCache` 等工具命令
- 安装包残留：给出具体文件路径，让用户自行到资源管理器删
- 谨慎用 `rd /s /q`，只用在明确的缓存子目录
- **git-bash 用户注意**：上述 `del` / `rd` 是 cmd.exe 内置命令，在 git-bash 中不可用。给用户展示命令时标注"在 cmd 或 PowerShell 中执行"，或在 git-bash 中用 `rm -rf "/c/Users/..."` 替代。

**大小字段写干净**：`size` / `size_estimate` 用"约 14 GB""合计约 8.6 GB"即可——"约"已表示估算，不要再加"（估算）"。

### Step 3 生成交互报告

把分析结果写成 analysis JSON（schema 见 `scripts/build_report.py` 顶部注释）。

**🟢 项必须带 `trash_paths`**（具体可删的绝对路径数组，区别于人类可读的 `path` 展示字段）——这是网页删除按钮的前提，漏了按钮就不出现。Windows 路径用反斜杠，确保在 `%USERPROFILE%` 内（白名单校验前提）。

**默认用一键删除模式（`server.py`）打开报告**，因为这个 skill 的核心价值就是网页上能直接清理：

**Windows：**
```cmd
python scripts\server.py %TEMP%\storage_analysis.json
```

**macOS：**
```bash
python3 scripts/server.py /tmp/storage_analysis.json
```

`server.py` 起在 127.0.0.1 + 随机端口 + 随机 token，自动用默认浏览器打开。Ctrl+C 停。

🟢 项给「移到回收站/废纸篓」(可逆) + 「直接删除」(立即释放、不可逆)；🟡 项给「在资源管理器/访达打开」+（有安全子路径时）「移到回收站/废纸篓」。

**安全模型——三套白名单，权限从严到宽**：`rm` 只允许绿灯 `trash_paths`；`trash` 允许绿灯+橙灯 `trash_paths`（橙灯永远不能 rm）；`open`（在文件管理器打开，非破坏性）允许上述全部 + 橙灯真实 `path`。所有请求 realpath 校验 + 必须在 $HOME 内 + token + Host 校验，每次点击浏览器先 confirm。

> **Windows 服务器启动流程（重要）**：即使加了 `-u` 去缓冲，agent 的 `terminal(background=true)` 模式下 `server.py` 的 stdout 可能完全不显示（实测 git-bash + Python 3.11）。**必须先在前台运行一次抓取 URL**（`timeout=15` 即可，server 启动后 1-2 秒就打印 URL），然后用 `background=true` 重新运行 `server.py`（会分配新端口），拿到新 URL 后 `browser_navigate` 打开。不要直接后台启动——拿不到端口号就无法打开报告。`server.py` 不支持 `--port` 参数，每次重启端口都是新的。
>
仅当用户明确只想要一份可分享/留存的只读文件时，才用静态模式（`build_report.py`）：

**Windows：**
```cmd
python scripts\build_report.py %TEMP%\storage_analysis.json %USERPROFILE%\Desktop\storage-report.html
start %USERPROFILE%\Desktop\storage-report.html
```

**macOS：**
```bash
python3 scripts/build_report.py /tmp/storage_analysis.json ~/Desktop/storage-report.html && open ~/Desktop/storage-report.html
```

**排障：网页上没有删除/移回收站按钮** = 要么开的是静态报告（改用 `server.py`），要么 🟢 项漏了 `trash_paths`（补上重启服务）。

报告阅读流（固定顺序）：磁盘总览卡片（容量 + 进度条 + 三色容量 pills + 系统信息，纯数据）→ 占用排行 Top5 → 执行建议 → 🟢🟡🔴 三级可折叠卡片（命令一键复制）→ 长期优化建议。即"现状 → 诊断 → 处方 → 操作 → 预防"。

注意 `summary.overview` 要写成一句话洞察（直接说最大占用是什么、能释放多少），不要重复总/已用/可用数字——那些已在卡片大数字里显示。

磁盘进度条把"已用"拆成分段：绿(可自动清)+橙(需手动)+红(已识别的不建议动项)+蓝(系统及其他，自动取 已用−绿−橙−红 的余量)，余下为可用(灰底)。`summary.tier_stats` 的 green / yellow / red 三个值都要以可解析的 GB 数字开头（如 "约 27.8 GB"），脚本从中取数算分段。

### Step 4 对话里给摘要

报告生成后，在对话里用一段话给结论先行的摘要：总可释放估算、最该先清的 2-3 项、风险最高的一项。细节让用户看网页。

## 依赖与运行前提

- 全部脚本是 **Python 3 标准库**，零第三方依赖（不用 pip install）。
- **Windows**：默认没装 Python，需先安装 Python 3（https://www.python.org/downloads/windows/，安装时勾选"Add Python to PATH"）。命令用 `python` 或 `py -3`（不是 `python3`）。
- **macOS**：自带 python3、`du`、`diskutil`、`osascript`，开箱即用。
- 本 skill 是 **agent 驱动**：扫描出数据后由 agent（Claude）做分级分析，不是双击即用的独立 App。

## 平台状态

- **Windows**：已验证通过（Windows 10/11 + Python 3.11 + git-bash）。`scan.py` v2 已实测：Everything 后端 18 秒完成 D 盘 197 万文件全盘分析（目录聚合/大文件/安装包/缓存/更新器/多版本六维输出），`coverage` 覆盖声明生效；walk 回退与 macOS 分支保持兼容。`server.py` 报告渲染正常；回收站操作（`SHFileOperationW`）待后续实测验证。踩坑实录见 [references/lessons-learned-windows.md](references/lessons-learned-windows.md)，Everything 集成方法见 [references/everything-integration.md](references/everything-integration.md)。历史完整案例见 [references/win11-case-study-20260603.md](references/win11-case-study-20260603.md)、[references/win11-cleanup-case-20260618.md](references/win11-cleanup-case-20260618.md)、[references/win11-optimization-case-20260715.md](references/win11-optimization-case-20260715.md)。
- **macOS**：完整实现并实测（扫描 / 报告 / 一键删除全验证过）。

## 常见陷阱 / Common Pitfalls

### `D:\` 等盘符路径在 git-bash 中的引号问题

git-bash 遇到 `"D:\"` 时，末尾的 `\"` 被解释为转义引号，导致语法错误：
```bash
python drilldown.py "D:\" --min-mb 100    # ❌ unexpected EOF while looking for matching `"'
```
**正确写法：使用正斜杠：**
```bash
python drilldown.py "D:/" --min-mb 100     # ✅
```
同理，`rm -rf "/d/..."`（MSYS 路径）和 `rm -rf "D:/..."` 都能用。这条对所有 git-bash 下的 Windows 盘符命令都适用。

### 非系统盘全量递归扫描容易超时（>180s）

大容量非系统盘（如 D 盘 200 GB+，百万级文件）用 `os.walk` 对每个子目录递归计大小极易超时。`scan.py` 只扫系统盘（C:），其他盘没有现成的 groups 数据。**不要写全量递归脚本去补扫。** 正确做法：
1. 用 `drilldown.py "D:/" --min-mb 100 --limit 30` 做顶层分析（只遍历一层，速度快）
2. 对关心的子目录再用 `drilldown.py` 深入一层
3. drilldown 顶层数据 + `system.disks` 信息足够分析非系统盘

### `server.py` 不接受 `--port` 参数

`server.py` 端口总是随机分配，无法通过 `--port` 命令行指定。如需在后台重启服务：直接重新运行 `server.py`（会分配新端口），用 `browser_navigate` 打开新 URL 即可。

### git-bash 环境下 `rd` / `del` 不可用

Windows 用户常用 git-bash（MSYS）作为终端。`rd /s /q` 和 `del /q /f /s` 是 cmd.exe 内置命令，在 git-bash 下直接运行会报 `rd: command not found`。

**错误做法：**
```bash
rd /s /q "C:\Users\<user>\.cache"          # ❌ rd: command not found
cmd //c "rd /s /q \"C:\path\with\space\"" # ❌ 引号转义容易出错（乱码报错）
```

**正确做法（MSYS 路径 + rm -rf）：**
```bash
rm -rf "/c/Users/<user>/.cache"
rm -rf "/c/Users/<user>/AppData/Local/Google/Chrome for Testing"  # 含空格也能用
```

- 路径用 MSYS 风格：`/c/` 代替 `C:\`，正斜杠
- `rm -rf` 对含空格的路径也能正确处理（加引号即可）
- 如需递归删除大量文件，`rm -rf` 速度和 `rd /s /q` 相当

### 包管理器缓存清理命令的可靠写法

`pip cache purge` 可能因 Python 环境冲突失败（如 uv 管理的 Python 与系统 pip 不兼容）。更可靠的写法：

```bash
python -m pip cache purge    # ✅ 使用明确绑定的 Python
pip cache purge              # ⚠️ 可能指向错误环境
```

同理，`npm cache clean --force` 在 Windows 上正常，但会输出 `npm warn using --force Recommended protections disabled` — 只是提示，不影响结果。

### ⚠️ 浏览器缓存清理铁律：登录信息一条都不能丢

清理 Chrome / Edge 等浏览器缓存时，**只能删纯缓存目录**，必须严格避开所有用户数据文件。登录信息存在于以下文件中，**绝不能动**：

| 文件/目录 | 内容 | 删了后果 |
|-----------|------|---------|
| `Cookies` / `Cookies-journal` | 所有网站的登录 Cookie | 全部网站需重新登录 |
| `Login Data` / `Login Data-journal` | 保存的密码 | 自动填充密码丢失 |
| `History` / `History-journal` | 浏览历史 | 历史记录消失 |
| `Preferences` | 浏览器设置 | 所有偏好设置丢失 |
| `Bookmarks` / `Bookmarks.bak` | 书签 | 书签全部丢失 |
| `Extensions/` | 已安装扩展 | 扩展消失需重装 |
| `Local Storage/` | 网站本地数据 | 网站设置丢失 |
| `IndexedDB/` | 网站数据库 | 离线数据丢失 |
| `Web Data` | 自动填充/搜索词 | 表单数据丢失 |

**只能删的纯缓存目录（删了不影响登录）：**
- `Cache/` — 网页图片/资源缓存
- `Code Cache/` — 已编译 JS 字节码
- `GPUCache/` — GPU 着色器缓存
- `Service Worker/` — PWA 离线缓存（Edge 可能被 WebView2 进程锁住，需先 `taskkill /F /IM msedgewebview2.exe`）
- `DawnCache/` — WebGPU 缓存
- `Shared Dictionary/` — 压缩字典
- `component_crx_cache/` — 组件扩展缓存
- `extensions_crx_cache/` — 扩展安装包缓存（注意：不是 Extensions 目录本身）
- `GrShaderCache/` — GPU 着色器缓存

**操作流程：**
1. 先 `drilldown.py` 深入 profile 目录，逐项识别缓存 vs 用户数据
2. 列出要删的精确路径给用户确认
3. 删除前检查浏览器是否在运行（`tasklist | grep -i "chrome|msedge"`），有 msedgewebview2.exe 也要杀
4. 只 rm -rf 缓存子目录，不动文件级别的 Cookies/History 等
5. 删完后验证 Cookies 和 Login Data 文件仍然存在

### Chrome profile 名称不一定是 Default

Chrome 的活跃 profile 目录 **不一定叫 `Default`**。用户可能有多个 profile，活跃的那个可能叫 `Profile 1`、`Profile 2` 等。`Default` 目录可能存在但为空或极少使用。

**正确做法：先 drilldown `User Data` 顶层**，看哪个 profile 目录最大、内容最多——那才是实际使用的：

```bash
python drilldown.py "C:/Users/<user>/AppData/Local/Google/Chrome/User Data" --min-mb 10 --limit 15
```

输出示例：
```
Profile 2: 2.2 GB      ← 这才是主 profile
Default: 0 B           ← 空的或不用的
component_crx_cache: 140 MB
extensions_crx_cache: 136 MB
```

找到主 profile 后再深入它的子目录。同理，Chrome User Data 顶层还有独立的缓存目录（`component_crx_cache`、`extensions_crx_cache`、`GrShaderCache`、`optimization_guide_model_store`），这些不在 profile 内，但也是纯缓存可安全清理。

### Chrome 运行时会锁住缓存文件

删除 Chrome 缓存目录（如 `Shared Dictionary`、`Code Cache`）时，如果 Chrome 正在运行，文件可能被锁定：
```
rm: cannot remove '.../Shared Dictionary/db': Device or resource busy
```

**处理方式：**
- 先关闭 Chrome，再删缓存目录
- 或者告知用户：该缓存项需关掉浏览器后才能清理，下次关闭 Chrome 时自动释放
- `Code Cache` 和 `extensions_crx_cache` 通常不被锁，可以边用 Chrome 边删

### 删除 ms-playwright 会破坏 browser 工具

Hermes 的 browser 工具（browser_navigate 等）底层依赖 Playwright，其浏览器二进制存放在 `%LOCALAPPDATA%\ms-playwright\`。如果删了这个目录，browser 工具会报错：
```
browserType.launch: Executable doesn't exist at ...\ms-playwright\...
```

恢复只需：`npx playwright install`（约 2 分钟重装）。这不影响分析报告本身——server.py 启动后用户可以在自己 Chrome 里打开 `http://127.0.0.1:<port>/`。

### 🟢 绿灯项必须 drill 到子目录：纯缓存 vs 用户数据

浏览器 profile、应用数据目录不能整目录标绿——必须用 `drilldown.py` 深入至少 2-3 层，把"纯缓存"和"用户数据"分开。用户数据包含：登录态（Cookies/Token）、历史记录（History）、偏好设置（Preferences）、扩展数据（Extensions）、应用自身数据库。删了这些用户需要重新登录、丢失历史。

> 详细安全路径参考：**[references/safe-cache-paths-windows.md](references/safe-cache-paths-windows.md)** — 含 Edge/Chrome、微信、QQLive、包管理器、更新器残留的逐子目录安全判定表.

**典型案例（Edge Default profile）：**
- ✅ 可删：`Service Worker\`（2.7 GB）、`Cache\`、`Code Cache\`、`GPUCache\`、`Shared Dictionary\`
- ❌ 不可删：`Extensions\`、`History`、`Cookies`、`Preferences`、`Local Storage\`、`Bookmarks`、`Login Data`

**典型案例（微信 xwechat）：**
- ✅ 可删：`log\`（运行日志）、`radium\web\profiles\*\Cache\`、`radium\web\profiles\*\Service Worker\`
- ❌ 不可删：`radium\users\*\applet\`（小程序登录态）、`xplugin\`（核心插件）

### 清理后建议重跑 scan + 前后对比

清理完绿灯项后，重跑 `scan.py` 生成对比报告。扫描时间缩短是侧面印证信号（本次：46s → 38s，减少约 8s）。对比两次 `disk_used` 差值即实际释放量，比手动估准。

**前后对比脚本（execute_code）**——逐个 group 找出删除/缩小的目录，生成清晰的 before/after 表格：

```python
import json

with open("scan_before.json") as f:
    old = json.load(f)
with open("scan_after.json") as f:
    new = json.load(f)

# 整体变化
freed = float(old["system"]["disk_used"].split()[0]) - float(new["system"]["disk_used"].split()[0])
print(f"释放: {freed:.1f} GB")

# 逐组对比
for gname in old["groups"]:
    if gname not in new["groups"]:
        continue
    old_items = {i["name"]: i["size_h"] for i in old["groups"][gname]}
    new_items = {i["name"]: i["size_h"] for i in new["groups"][gname]}
    gone = set(old_items) - set(new_items)
    changed = {k: (old_items[k], new_items[k]) for k in old_items if k in new_items and old_items[k] != new_items[k]}
    if gone:
        print(f"{gname} 已删除: {gone}")
    if changed:
        print(f"{gname} 变化: {changed}")
```

这个脚本直接告诉用户每一项目录的释放量，比笼统说"释放了 X GB"更有说服力。

### `du` 在深目录树上超时

Windows git-bash 的 `du -sm` 遍历百万文件级目录（如 `node_modules`、`xwechat` 整树）时经常超时（30s+ 无输出）。**不要对整棵大树跑 du**。

正确做法：
- 用 `drilldown.py` 按一级子目录拆分（限制 `--limit` 和 `--min-mb`）
- 或写一个轻量 Python `os.walk` 脚本，逐个顶级子目录计算
- `npm node_modules` 通常 ~30 个顶级包，Python 脚本 7 秒完成 vs du 超时

### 运行中应用锁文件

Chrome、微信等运行时会将部分文件锁定（`mmap`、`db` 文件）。删除时遇到 `Device or resource busy` 不用慌——关掉应用后自动释放，或告知用户该缓存项需下次关闭应用时清理。

### npm 缓存 `_npx` 子目录权限问题

`rm -rf` 删除 `npm-cache` 时，`_npx/` 下的某些包（如 playwright、playwright-core）可能包含只读文件，导致部分删除失败：

```
rm: cannot remove '.../npm-cache/_npx/.../playwright-core/...': Permission denied
```

**修复：先 `chmod -R +w` 再 `rm -rf`：**

```bash
chmod -R +w "/c/Users/<user>/AppData/Local/npm-cache" 2>/dev/null
rm -rf "/c/Users/<user>/AppData/Local/npm-cache"
```

这是已知的 npm / playwright 打包问题——npx 缓存中部分 node_modules 文件的权限位被设为只读。**优先用 `npm cache clean --force`**（npm 内部走自己的权限处理），只在 npm 不在 PATH 或工具命令失败时才 fallback 到 `rm -rf`。同理，`pip cache purge`、`uv cache clean` 等工具命令比裸 `rm -rf` 更可靠。

### pnpm store 目录删除权限问题

pnpm 全局 store（如 `D:\\.pnpm-store` 或 `%LOCALAPPDATA%\\\\pnpm`）内的索引 JSON 文件可能被设为只读，`rm -rf` 会报大量 `Permission denied`：

```bash
rm -rf "/d/.pnpm-store"
# rm: cannot remove '.../xxx.json': Permission denied  （可能出现数百条）
```

**修复：先 `chmod -R +w` 再 `rm -rf`：**
```bash
chmod -R +w "/d/.pnpm-store" 2>/dev/null
rm -rf "/d/.pnpm-store"
```

如果目录特别大（数百 MB+），`rm -rf` 可能超时——用 `terminal(background=true, timeout=120)` 后台运行即可。首选清理方式仍是 `pnpm store prune`，只在 pnpm 不在 PATH 时才用直接删除。

### git-bash 后台模式 + 文件重定向静默失败（scan.py / drilldown.py 输出为空）

`terminal(background=true)` + `>` 重定向在 git-bash 中跑 Python 脚本时，子进程的 stdout 可能完全不写入文件——进程能跑满 4+ 分钟但输出文件始终 0 字节。`python -u`（unbuffered）也救不了，因为问题是后台模式的重定向链路，不是 Python 自身的缓冲。

**症状：**
- `process(action='poll')` 显示 `status: running`，uptime 正常增长
- 但输出文件 `ls -la` 始终 0 字节
- `tasklist` / `ps aux` 在 git-bash 中找不到 Windows Python 进程（MSYS 不跟踪 Win32 进程），无法确认进程是否还活着
- 最终进程超时退出，文件仍为空

**正确做法——用 `execute_code` + `subprocess.run`：**
```python
import subprocess
script = "C:/Users/.../scan.py"
result = subprocess.run(
    ["python", "-u", script],
    capture_output=True, text=True, timeout=300
)
# result.stdout 有完整输出，写入文件即可
with open("C:/Users/.../Temp/storage_scan.json", "w", encoding="utf-8") as f:
    f.write(result.stdout)
```
实测 C 盘 scan.py 52 秒完成（25KB JSON），D 盘 drilldown.py 112 秒完成。比后台 terminal 模式可靠且更快定位问题。

**回退策略：** 先用后台 terminal 尝试并行扫描（这是最快的），如果 60 秒内输出文件仍为 0 字节，立即 kill 后台进程并切到 `execute_code`。

### Everything IPC 未运行 / scan 超时 / junction 幻增（2026-08-21 C 盘实战）

1. **es.exe 报 `Error 8: IPC window not found`**：Everything 主程序没在跑。git-bash 里 `cmd //c start` 启不动它，用 `execute_code` 分离进程启动：
   ```python
   subprocess.Popen([r"D:\Everything\Everything.exe", "-startup"],
       creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
       cwd=r"D:\Everything", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
   ```
   等 5-10 秒索引加载后 es 即可用（`es -get-result-count` 验证）。

2. **C 盘（192 万文件）scan.py 全程超前台 300s**：es 导出 251MB CSV 约 2-4 分钟 + 聚合 2-3 分钟 + dev_caches 逐目录递归。方案：后台 terminal 跑完；或先让 es 单独 `-export-csv`，再 `scan.py --reuse-csv` 跳过导出阶段（scan.py 已内置该参数，复用 `%TEMP%\scan_<盘>.csv`）。

3. **⚠️ junction 幻增（已修）**：`dir_size_bytes` 曾跟随 NTFS junction 导致 pnpm 报 62.5GB（真实 1.4GB）——`pnpm\store\v11\projects\` 下 junction 指向项目目录，项目 node_modules 又链回 store，循环虚增。**Windows junction 对 `Path.is_symlink()` 返回 False，必须用 `st.st_file_attributes & 0x400 (REPARSE_POINT)` 判断**。Everything 聚合路径（CSV）不受影响。

4. **execute_code 里跑 tasklist 等系统命令**：GBK 输出使 `text=True` 解码崩溃（UnicodeDecodeError），加 `encoding="gbk", errors="replace"`。

5. **server.py 可用 execute_code 分离启动**：stdout 重定向到日志文件，sleep 4 秒后读日志拿 URL，比"前台抓 URL 再后台重启"少一步。`curl http://127.0.0.1:<port>/` 返回 200 + 完整 HTML 即验证通过（GET / 无需 token）。

### 跨盘移动大目录的正确方式

当用户要求将 C 盘的大目录（如 `node_modules`、`.git`）搬迁到 D 盘时：

| 方法 | 可靠性 | 说明 |
|------|--------|------|
| `mv /c/src /d/dst` | ❌ 容易超时 | git-bash 的 mv 对大目录可能部分完成 |
| `shutil.move`（跨盘） | ⚠️ 可能卡住 | 内部 `rmtree` 遇锁文件会抛 WinError 145 |
| `robocopy /MOVE` | ✅ 推荐 | Windows 原生，重试机制，稳定 |

```cmd
robocopy "C:\source" "D:\dest" /E /MOVE /R:2 /W:3
```

搬迁后如需原路径仍可访问，用 `mklink /J` 创建目录联接（详见 `references/win11-cleanup-case-20260618.md`）。

### NVIDIA 相关目录的处理与验证（用户对显卡文件普遍很敏感，务必按此流程）
- **可安全删（用户权限即可）**：`C:\ProgramData\NVIDIA Corporation\Downloader` —— ACL 是 `Everyone:(I)(OI)(CI)(F)`，普通权限可写；内容是 GFE 下载的更新安装包 + 下载清单（`gfeupdate.json` / `status.json`），属可再生缓存。**只清内容、保留目录**，并明确告知用户 GFE 需要时会重新下载。
- **需管理员**：`C:\Program Files\NVIDIA Corporation\Installer2` —— ACL 为 `TrustedInstaller/Administrators` 独占，普通权限实测 `PermissionError`，只能给管理员 `rmdir /s /q` 命令。
- **绝对不要碰**：`ProgramData\NVIDIA\NGX`（DLSS 模型）、`ProgramData\NVIDIA Corporation\{Drs,NvBackend,ShadowPlay,NvStreamSrv,NvTelemetry,nvtopps,CrashDumps,RX}`、`Program Files\NVIDIA Corporation\*` 下驱动/服务本体、`Windows\System32\DriverStore`。
- **删前后必做的健康验证（一句话就能让用户放心）**：`"C:\Windows\System32\nvidia-smi.exe" --query-gpu=name,driver_version,temperature.gpu,utilization.gpu --format=csv` 前后对比驱动版本必须一致；再 `tasklist | grep -icE "nvcontainer|NVDisplay"` 确认服务进程仍在（本机常态 4 个）。
- 判断权限别用 bash 里的 `icacls`：MSYS 会把路径参数转换坏（报"参数模式错误"）。用 `execute_code` + `subprocess.run(["icacls", r"C:\..."])`，或直接做"创建+删除探测文件"的可写性实测。

## 深度扫描模式（Deep Scan）—— 用户说"再全面深扫一遍/感觉漏东西"时走这条

Everything CSV 路线**覆盖率高但分析深度容易不足**：本机实测 CSV 1,968,358 行 vs Everything 索引 1,968,421 个文件，只差 63 行（0.003%）——**覆盖率从来不是问题，漏项都发生在"只看了 Top N 和几个大类"**。深度扫描要换成直读文件系统，并做差额对账。

### 覆盖度审计（先做，30 秒）
```
cd /d/Everything
./es.exe -get-result-count          # 索引总量
./es.exe /a-d -path "C:\\" -get-result-count   # 该盘文件数（/a-d = 排除目录，属正常用法）
```
CSV 行数与之相差应在 0.1% 以内。**校验 CSV 内容一律用 Python，不要用 bash grep**——MSYS 会把含反斜杠的模式当路径转换，导致"看起来 0 命中"的假阴性（本次被坑过：误判 Everything 漏了注册表单元，实际 CSV 里就有）。

### 直读扫描脚本要点（本次实测 191 万文件 / 114 秒）
- **同一份结果文件不要并发跑两次扫描**：本次踩过——修正参数后直接启动了新进程却没 kill 前一次，两个进程写同一个 `deep_C_result.json`，事后只能靠比对 total_files 才能确认落盘的是哪一版。启动深扫前先 `process(action='kill')` 掉上一次。
- `os.scandir` 迭代栈遍历，**不要设深度上限**（本次设 12 层导致漏 35 万文件/21GB；node_modules 树的层数轻松超过 12）。
- 跳过 reparse point（`st_file_attributes & 0x400`）：本机有 10,971 个（多是 node_modules/.bin 符号链接与 Windows 兼容链接）。跳过后 junction 内容不会重复计入。
- 记录 `denied` 目录清单（本次 106 个，全在 C:\Windows 系统区）。
- 硬链接去重：按 `(st_dev, st_ino)` 记账，`st_nlink > 1` 才算一次。**本机实测 C 盘 nlink>1 文件数 = 0** —— Win11 的 WinSxS 已改用 WOF 压缩而非硬链接，别再假设"WinSxS 数字被硬链接虚增"。
- 压缩实占：`kernel32.GetCompressedFileSizeW`，但**只对 ≥1MB 的文件调用**——对全部文件调用会让 200 万文件从 2 分钟变成 90 分钟（370 文件/秒）。
- 大小要**累加到全部祖先目录**，才能得到任意深度的目录大小（本次产出 1,151 个 ≥100MB 目录）。

### 差额对账（必做，且必须在报告里解释）
`disk_used − 文件合计` 通常有 5-15GB 对不上，来源固定四类，且**这部分删文件回收不了**：
1. ACL 受限目录（注册表配置单元 `System32\config` 里 SOFTWARE 129MB/SYSTEM 22MB、Tasks、spool、WDI、WUModels、SystemTemp…）——普通权限读不到，Everything 走 MFT 能看到，直读看不到；
2. 系统还原点/卷影副本（`C:\System Volume Information`，本次 2.88GB）；
3. NTFS 元数据（$MFT / $Secure / $UsnJrnl / $LogFile，200 万文件约 2-4GB）；
4. 压缩文件逻辑大小与实占之差（本次 1.11GB）。
要把这部分定性只能用管理员身份；`fsutil`、`vssadmin`、`DISM` 在普通权限下全部"拒绝访问"。

### 容易被漏报的实体清单（下次照着逐个查）
`ProgramData\NVIDIA Corporation\Downloader`（驱动下载缓存）、`Program Files\NVIDIA Corporation\Installer2`、`Program Files (x86)\Google\GoogleUpdater`（crx_cache 可达 1GB）、`ProgramData\Package Cache`（VS/VC++ 安装缓存）、`Windows\System32\winevt\Logs`（事件日志，本次 454MB）、`Windows\WinSxS\Backup`、`Windows\WinSxS\Catalogs`、`Windows\servicing\Sessions`、`ProgramData\Microsoft\Windows Defender`（病毒库，勿删但要列）、第二套 Chrome（`Chrome Dev`）、`DoubaoIME\versions` 等多版本目录、`Saved Games`、以及**家目录下的点目录群**（本次 31 个 AI 工具点目录合计 19.4GB，只提 3 套编辑器 extensions 会严重漏报）。

### 别忘了扫描器自己的产物
`scan.py` 把全盘 CSV 写在 `%TEMP%\scan_<盘>.csv`，本机实测 **scan_C.csv 241MB + scan_D.csv 260MB = 501MB**。跑完要么删掉，要么把它作为 🟢 项写进报告（本次是深扫发现的第二大绿灯项）。

## 2026-09-28 实战新增坑（清理执行阶段，Windows）

1. **agent 工作区千万别放 %TEMP%**：绿灯项里常有 `rm -rf "$TEMP"/*`，会把分析 JSON、目录树缓存、query 脚本一起删掉（本次实录，白干一轮）。工作目录改用 `%LOCALAPPDATA%\hermes\scan-work\`。
2. **Everything 溢出值必须过滤**：微信 `xwechat_files\...\msg\migrate\config\*` 等文件被报成 `18446744073709551615`（2^64-1）字节。CSV 聚合时把 >4TB 的值视为无效置 0，否则总量算出天文数字（本次 D 盘一度算出 5.15e10 GB）。
3. **Ollama（Windows）安装包残留的判定与验证**：`D:\ollama\OllamaSetup.exe`、`%LOCALAPPDATA%\Ollama\updates_v2\<hash>\OllamaSetup.exe` 只是安装器；模型在 `OLLAMA_MODELS`（本例 `D:\ollama\models`，就是 embedding 模型 bge-m3 的家），程序在 `D:\ollama\Program`，`db.sqlite`/`*.log` 是应用状态——**绝不能删整个 `%LOCALAPPDATA%\Ollama`**。删前删后都用 `curl -s --noproxy 127.0.0.1 http://127.0.0.1:11434/api/embed -d '{"model":"bge-m3","input":"测试"}'` 比对向量 md5 指纹。
4. **⚠️ 跑 `ollama list` 会触发自动升级**：Windows 上 CLI 会拉起 app wrapper，发现有 pending 更新就静默安装（本次 0.34.3 → 0.34.4，安装过程会长时间占用 `D:\ollama\Program`）。要测试请用 `ollama serve` + curl，别用 `ollama list`；若升级已在跑，等 `OllamaSetup.exe` 进程退出再动手。
5. **浏览器缓存与登录态核对（必做）**：Chrome 运行时 `Cookies` 被独占锁（读会 `PermissionError`），此时只能删 `Code Cache` 与 `User Data\{component_crx_cache,extensions_crx_cache}`；`Cache`/`Service Worker` 需先关浏览器。删前后对 Cookies / Login Data / Web Data / History / Preferences / Bookmarks / Extensions **逐项比字节数**（文件被锁就退化为比 `os.stat().st_size`）。为绝对避免用户重新登录，可主动跳过 `Service Worker`（它是唯一可能携带站点级会话数据的目录）。
6. **DENY ACL 的日志目录**（WorkBuddy 等）：`icacls` 里能看到 `<user>:(I)(DENY)(DE,DC)` 继承项，`rm -rf` 必失败、`chmod` 无效。正解：`icacls <dir> /remove:d <user> /t /c /q` → `icacls <dir> /grant <user>:(F) /t /c /q` → `takeown /f <dir> /r /d y` → `cmd /c rmdir /s /q <dir>`。
7. **server.py 最省事的启动方式**（优于"前台抓 URL 再后台重启"）：`execute_code` 里 `subprocess.Popen([py,"-u",server.py,json], stdout=log, creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP)`，sleep 5 读日志拿 URL；日志出现「绿灯可删 N 项」即证明 JSON 被正确解析。换报告先 `taskkill /F /PID <旧pid>`。
8. **验证渲染的兜底**：`browser_navigate` 依赖 playwright 内核，缺内核时报 `Executable doesn't exist at ...\ms-playwright\chromium_headless_shell-XXXX\...`；此时用系统 Chrome 无头截图代替：
   `"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1500,3000 --screenshot=out.png http://127.0.0.1:PORT/`
9. **多盘统计的正确性**：`tier_stats` 只填系统盘的量（否则进度条分段会超过 C 盘已用，视觉错乱）；非系统盘的 🟡/🔴 分析写进 `summary.priority` 文本，绿灯可保留跨盘卡片并标注「（D 盘）」。

## 长期优化建议素材（写进报告 summary.long_term）

**Windows 优先：**
- 设置 > 系统 > 存储 > 存储感知（自动清 Temp 和回收站）
- `cleanmgr`（磁盘清理）→ 扩展磁盘清理 → 勾选 Windows 更新清理
- `DISM /Online /Cleanup-Image /StartComponentCleanup`（清 WinSxS 组件存储，需管理员）
- 定期整理下载文件夹；卸载不用的大型游戏/软件
- 可视化工具：SpaceSniffer、WizTree（Windows 免费磁盘分析，极快）

**macOS：**
- 定期清理：`brew cleanup`、Xcode DerivedData、浏览器缓存
- 可视化工具：DaisyDisk、GrandPerspective、OmniDiskSweeper
- 大文件归档到外置盘 / iCloud / NAS；macOS「系统设置 > 通用 > 储存空间」的优化选项
