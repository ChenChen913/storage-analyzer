# Storage Analyzer

> **来源**：本仓库改造自 [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) 中的 `storage-analyzer`。上游是一个包含 6 个 skill 的合集，本仓库只改造并发布了其中一个，其余 skill 的版权归原作者所有。
>
> **完整 fork**：[ChenChen913/khazix-skills](https://github.com/ChenChen913/khazix-skills)，保留上游全部内容，用于记录血缘关系。
>
> 原项目采用 MIT 许可，原版权归 数字生命卡兹克；本仓库的改造部分归 ChenChen913。

一个由 AI Agent 驱动、扫描阶段只读的存储分析 skill。它做四件事：把整块盘的文件清单摊开，按 🟢 可自动清理 / 🟡 需人工判断 / 🔴 谨慎清理分三级，生成可折叠、命令可复制、支持逐项确认删除的本地网页报告，并把这一轮的定性结论存下来供下一轮复用。

它不是双击即用的软件，需要挂在支持 skill 的 Agent 里使用，由 Agent 负责逐目录看内容、判断用途、写分级理由。

## 和清理软件相比，差别在哪

先说结论：**传统清理软件清得不彻底，这个判断在本机范围内验证成立，但原因不是它们能力差，而是它们的工作方式决定了它们默认只清「自己认识的位置」。**

### 清理软件是规则驱动

Windows 自带的磁盘清理，类别来自注册表 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VolumeCaches`。本机 Windows 11 实测共 31 项，全部是固定的系统级类别：

```text
Active Setup Temp Folders   Content Indexer Cleaner     D3D Shader Cache
Delivery Optimization Files Device Driver Packages      Downloaded Program Files
Internet Cache Files        Language Pack               Offline Pages Files
Old ChkDsk Files            Previous Installations      Recycle Bin
Setup Log Files             System error memory dumps   Temporary Files
Thumbnail Cache             Update Cleanup              Upgrade Discarded Files
User file versions          Windows Defender            Windows Error Reporting
Windows ESD installation    Windows Upgrade Log Files   ...
```

存储感知（Storage Sense）会自动清临时文件和回收站，默认不碰下载文件夹。CCleaner 一类第三方工具围绕临时文件、浏览器缓存与 Cookie、注册表等公认位置展开。它们都是「已知清单 + 定期更新」，清单外的目录默认不会碰。第三方工具通常允许手动添加自定义路径，但那要求用户自己先知道路径在哪，等于已经解决了「发现」这一步。

### 这个 skill 是清单驱动

`scan.py` 先用 Everything 或 WizTree 拿到全盘每一个文件的路径与大小，再用 `rules.py`、`orphan.py`、`apps.py`、`registry.py` 做成组命中、卸载残留检测、应用登记与跨轮差分，最后交给 Agent 逐个目录看内容定性。

换句话说：清理软件问的是「这个位置在我的清单里吗」，这个 skill 问的是「这块盘上到底有什么」。

### 验证：本机有多少东西在清理软件的清单外

对用户目录、`AppData\Local`、`AppData\Roaming` 三个根做一次枚举，名字以 `.` 开头、以 `updater` 结尾或以 `@` 开头的目录共 **196 个**。用 Everything 按逻辑大小汇总，合计 **18.8 GB**。口径是只统计这三个根的直接子目录，不做硬链接去重（本机 C 盘 `nlink > 1` 的文件数为 0，不影响结果）。

磁盘清理的 31 个类别里，没有任何一项对应它们。这些目录包括 `.claude`、`.cargo`、`.bun`、`.android`、`.conda` 这类开发工具数据，也包括 `@xxx-updater` 这类应用更新器残留。

需要说清楚的是：这 18.8 GB **不是都能删**。大量目录是正在使用的开发环境。这个 skill 的价值不是「发现即删除」，而是让这 18.8 GB 从「不可见」变成「可判断」，再由 Agent 给出保留、迁移或清理的具体方案。

### 实战中真正被挖出来的隐藏项

以下是本仓库 Windows 实机跑出来的结果，都可以在 `references/` 里找到对应案例：

| 项目 | 体量 | 传统清理器为什么看不见 |
|------|------|------------------------|
| 通义灵码 4 处残留（`~\.lingma`、`D:\lingma`、VS Code 与 Trae 扩展目录） | 约 4.16 GB | 没有注册表安装记录，「应用和功能」里不显示，磁盘清理无对应类别 |
| 浏览器缓存六件套 + npm/pip/uv/Bun/Cargo/WinGet 缓存 + 10 个更新器残留 | 约 11.8 GB | 分散在各应用私有目录，不在系统类别表里 |
| 31 个 AI 工具点目录（`.lingma`、`.claude`、`.cursor` 等） | 早期深扫时 19.4 GB | 家目录点目录，系统清理器完全不扫描 |
| `Program Files (x86)\Google\GoogleUpdater` 的 crx_cache | 约 1.0 GB | 不属于任何内置类别 |
| `ProgramData\NVIDIA Corporation\Downloader` 驱动下载缓存 | 约 0.7 GB | 同上 |
| `C:\Program Files\WindowsApps`（WizTree 普通权限漏报） | 9.62 GB | 受保护目录，普通权限的数据源读不到；磁盘清理也不会清它 |

同时，全盘清单本身是可信的：一次实测中，CSV 行数 1,968,358 与对应范围内的 Everything 索引 1,968,421 只差 63 行（0.003%）。扫描覆盖率不是瓶颈，瓶颈一直是「看不看得到清单之外的东西」。

### 需要说清楚的边界

- 清理软件不是没用。回收站、缩略图、系统更新残留这类系统级项目，它比手工判断更稳妥，而且不依赖模型。
- 这个 skill 不会无人值守地删任何东西。扫描阶段只读，清理动作只有两个入口：报告网页里由用户逐项点确认，或用户在对话中明确授权后由 Agent 按已定性的清单执行。两种方式都要求逐项确认，不存在「一键全自动清盘」。
- 「看见」不等于「该删」。应用本体、聊天记录、代码仓库这类东西，正确做法是卸载或迁移，不是删目录。
- 分析质量取决于 Agent 的判断力。同一个盘换一个模型，分级结论可能有出入，所以每一项都要求写出理由，方便人复核。
- 对受保护目录（`System Volume Information`、`WinSxS`、Defender 定义库）能看见不等于能删，这部分只做展示和解释。

## 运行环境与改造说明

| 平台 | 状态 |
|------|------|
| Windows 10 / 11 | 本仓库维护者实测使用，所有改造都在这里完成并验证 |
| macOS | 上游作者在 macOS 上开发和使用，本仓库**从未复验** |
| Linux | 不支持，`scan.py` 直接返回 `unsupported_platform` |

具体说明：

- **上游原版按 macOS 设计**，本仓库在 Windows 上做了一整套适配：Everything / WizTree 数据源、非系统盘分析、Windows 缓存安全边界、回收站与删除流程的 Windows 实现、git-bash 与 PowerShell 的路径差异、NTFS 权限与 junction。
- **macOS 分支从未在本仓库复验**。它的实现保留着：用 `du` 统计固定目标目录，生成报告，支持一键移入废纸篓。但 macOS 不生成全盘 CSV，因此 `rules.py`、`orphan.py`、`apps.py`、`registry.py` 这套增量审计在 macOS 上不可用，功能完整度明显低于 Windows。
- **Linux 没有任何实现**，脚本里的平台判断只覆盖 Windows 与 macOS，其他平台会显式报错退出。
- Windows 需要先装 Python 3（`python` 或 `py -3`），全部脚本只用标准库，不需要 `pip install`。macOS 自带 `python3`。

## 工作原理

```text
Step 1   全盘清单      Everything / WizTree / walk 三选一，导出「路径,大小」CSV
Step 1.5 增量审计      rules 成组命中 · orphan 卸载残留 · apps 应用登记 · registry 跨轮差分
Step 2   语义分级      Agent 建目录树、对平总账、逐目录看内容，分 🟢 🟡 🔴
Step 3   交互报告      server.py 起本地服务，token + 路径白名单 + 逐项确认
Step 4   对话摘要       结论先行：总可释放估算、最该先清的项、风险最高的一项
Step 5   收尾           处理扫描中间产物，询问用户删除时机
```

几条关键设计：

- **总账必须对平。** 文件合计、`disk_usage` 实占、目录树加总三方对不上，就说明有漏项，必须解释差额来源。
- **定性先看内容，禁止凭目录名猜。** `recordings`、`photos`、`docs` 默认视为用户数据，进黄灯。
- **成套清理由规则引擎兜底。** 浏览器缓存六件套（Cache、Code Cache、GPUCache、Service Worker、Shared Dictionary、DawnCache）漏一个，下一轮就会变成「新发现」。
- **跨轮记忆。** 每个 ≥20MB 目录的定性写回 `state/registry.json`，下一轮从差分清单开始，而不是每次从零重看。
- **绿灯才允许直接删，黄灯只能移回收站，红灯只允许打开目录。** 所有请求都要过 token、Host、`$HOME` 与 realpath 校验。

## 早期版本的真实问题：为什么每轮都有新发现

这是这个 skill 最早被反复指出的问题，也是 v3 改造的主因。当时连续六轮分析同一台机器，每一轮都还能再挖出一批新东西：

| 轮次 | 新发现 |
|------|--------|
| 第二轮 | 安装缓存 2.38 GB、豆包镜像、淘宝残留、VPN 旧版 |
| 第三轮 | 缓存普查 22 组 7.9 GB |
| 第四轮 | JetBrains 插件 zip 2.38 GB、更新器残留、hermes `.git` 1.08 GB |
| 第五轮 | 同一插件目录里又翻出 28 个同类 zip、灵码多版本 313 MB |
| 第六轮 | 绿灯 1.14 GB、Kiro 725 MB、Codex 1.69 GB |

### 根因

扫描覆盖从来不是问题（每轮约 174 万文件完整进 CSV），问题出在分析端：

1. **Top-N 驱动，不是全量驱动。** 分析看的是按大小排序的清单和 ≥10MB 阈值，GB 级项目永远先被看到，MB 级缓存群系统性排在后面。下一轮调低阈值，又是一批「新发现」。
2. **没有跨轮记忆。** 每一轮都从头看，上一轮的定性结论随对话压缩消失。`.dsh`、`.real`、`.box-agent` 这类点目录每轮都在 CSV 里，直到第五轮才有人去查。
3. **成套清理靠临场枚举。** 第四轮只删了文件名里带 lingma、qoder 的 9 个 zip，同目录 28 个同模式文件漏网。教训里写了「清理成套」，但执行时没有规则兜底。
4. **没有卸载残留检测。** Kiro 数据还在、应用本体早已卸载、90 天没动过，本该第一轮就发现，实际拖到第六轮。

### v3 的解法

| 问题 | 现在的机制 |
|------|-----------|
| 跨轮失忆 | `registry.py` 维护目录档案（大小、两层 mtime、定性结论、处置状态），本机现有 7,748 个目录；每轮只 `diff` 新增、变大、删后复活三类 |
| Top-N 盲区 | 分析顺序改为「未审查应用 > diff 增量 > 卸载残留 > 规则命中 > 全量 TopN 兜底」 |
| 成套漏删 | 清理候选先跑 `rules.py` 拿成组结果，agent 只做复核；浏览器缓存六件套等由规则固定 |
| 卸载残留 | `orphan.py` 用「数据目录存在 + 本体不在 + 活跃度低」给出置信度 |
| 应用没审过 | `apps.py` 从注册表 `InstallLocation` 枚举应用，输出未审查清单，实测可识别应用从 55 个提升到 215 个 |
| 真残留与活水缓存难分 | 报告读 `state/last_diff.json`，自动标「新发现 / 删后复发 / 最后活动时间」 |

### 现在的状态与边界

- 结构性问题已经消掉：同类文件下一轮不会再被当成新发现，因为规则和档案会先接住。
- 活水缓存仍会再生，但会被标成「删后复发」，不会伪装成新发现。
- 受保护目录与系统还原点造成的账目差额，普通权限下仍解释不全，见 [deep-scan.md](references/deep-scan.md) 的差额对账。
- 档案越全，增量审查越准；第一次使用仍是全量分析，不会一上来就很快。

## 数据源：Everything 与 WizTree

两个工具都能在几十秒内给出百万级文件的完整清单，但底层原理不同，覆盖范围和代价也不同。

### Everything

**原理**：Everything 直接读取 NTFS 的 **MFT（Master File Table，主文件表）** 来建立文件名索引。MFT 是 NTFS 记录每个文件元信息（文件名、大小、时间戳、父目录指针）的系统表，读它比逐个目录调用 Windows 文件系统 API 快几个数量级。后续的文件增删改用 **USN Journal（更新序列号日志）** 增量跟踪，不需要重复全盘遍历。

`es.exe` 本身不扫描磁盘，它只是一个 IPC 客户端，向常驻的 Everything 主程序要结果。所以主程序没启动时会报 `Error 8: IPC window not found`。

**好处**：

- 普通权限就能覆盖 `WindowsApps`、Defender 定义库等受保护目录。Everything 的索引服务以系统权限读取 MFT，不依赖用户对目录的 ACL 权限。
- 索引常驻内存，建好之后重复分析近乎零成本，本机实测导出 5.9 秒。
- 安装包只有 3.3 MB，命令行输出格式稳定，免费且商用无授权顾虑。

**代价**：

- 需要主程序常驻，索引 495 万条时约 400 MB 内存，内存紧张的机器要权衡。
- 主程序没运行时不可用。
- 首次安装需要花时间建索引。

### WizTree

**原理**：WizTree 同样**绕过 Windows 文件系统 API，直接解析 NTFS 的 MFT**，因此扫描速度远超普通遍历工具。区别在于它不维护常驻索引，每次扫描都重新读盘。

**好处**：

- 没有后台进程，空闲时零内存占用。
- 自带图形界面，手动查看大目录很直观。
- 安装即用，不依赖后台索引是否在运行。
- 安装包 20.2 MB，仍算轻量。

**代价**：

- 普通权限下拿不到受保护目录的读取权限。本机实测 C 盘漏掉 50,617 个文件、18.70 GB，其中 `WindowsApps` 9.62 GB、Defender 定义 3.37 GB、两个容器 GUID 目录 3.38 GB、`Windows\OEM` 0.28 GB。
- 每次都要重扫，本机热缓存 36.2 秒、冷缓存 141.3 秒。
- 完整覆盖需要在已提权的终端里加 `--wiztree-admin`（`/admin=1`）。注意：该模式本仓库尚未实测。
- 个人免费，商用需授权。

### 同机实测对比

C 盘约 170 万文件，普通权限，同一台机器顺序执行：

| 指标 | Everything | WizTree（普通权限） |
|------|-----------|--------------------|
| 导出耗时 | 5.9 s | 141.3 s 冷 / 36.2 s 热 |
| 端到端 `scan.py` | 15.5 s | 81.0 s |
| 文件行数 | 1,721,056 | 1,670,439（少 2.9%） |
| 逻辑总字节 | 187.92 GB | 167.85 GB（少 18.70 GB） |
| 安装体积 | 3.3 MB | 20.2 MB |
| 常驻内存 | 约 400 MB | 0 |
| 权限要求 | 普通权限全覆盖 | 需管理员才完整 |

完整测试方法与明细见 [data-source-comparison.md](references/data-source-comparison.md)。

### 选择规则

1. **已经装了哪个，就用哪个。** `--source auto` 自动按 Everything → WizTree → walk 选择，不需要用户做决定。
2. **两个都没装，推荐先装 Everything。** 普通权限就能全盘覆盖、重复扫描秒级、安装仅 3.3 MB，最适合需要反复分析全盘的场景。
3. **内存紧张、只想偶尔看一次，选 WizTree。** 但请在提权终端里加 `--wiztree-admin`，否则会漏掉受保护目录。
4. **两个都不装，回退 `walk`。** 能出结果，但百万文件级要几十分钟，只适合应急。

## 安装

把整个目录放到 Agent 的 skills 目录：

- Trae CN：`%USERPROFILE%\.trae-cn\skills\storage-analyzer`
- Claude Code：`~/.claude/skills/storage-analyzer`

Windows 另需安装 Python 3，并勾选「Add Python to PATH」。

## 使用

在对话里说「帮我看看 C 盘为什么满了」之类的话，Agent 会自动命中这个 skill。也可以手动跑脚本：

```powershell
# Windows
python scripts\scan.py --out "%TEMP%\storage_scan.json"
python scripts\rules.py --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
python scripts\orphan.py --csv "%TEMP%\scan_C.csv" --min-mb 50
python scripts\apps.py build --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
python scripts\registry.py diff --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
python scripts\server.py "%TEMP%\storage_analysis.json"
```

```bash
# macOS（功能子集，无 CSV 与增量审计）
python3 scripts/scan.py > /tmp/storage_scan.json
python3 scripts/server.py /tmp/storage_analysis.json
```

`server.py` 会在 `127.0.0.1` 随机端口起动，带随机 token，并自动打开浏览器。报告里的删除按钮只对绿灯可见，黄灯只能移到回收站，红灯只能打开目录，每次点击都要二次确认。

## 目录结构

```text
SKILL.md                          主入口，只放流程骨架与硬性规则
scripts/
  scan.py                         全盘扫描，Everything / WizTree / walk 三数据源
  rules.py                        成套规则命中（缓存六件套、视频缓存等）
  orphan.py                       卸载残留检测
  apps.py                         应用登记表与未审查清单
  registry.py                     跨轮目录档案与差分
  drilldown.py                    单目录多层下钻
  build_report.py                 静态报告生成
  server.py                       本地报告服务，带确认删除 API
references/
  scan-workflow.md                数据源选择、扫描降级、批量下钻
  incremental-audit.md            增量审计四件套用法
  analysis-guide.md               分级标准与清理后复扫
  reporting-guide.md              报告 JSON schema 与排障
  safe-cache-paths-windows.md     浏览器 / 微信 / QQLive 缓存边界
  pitfalls-windows.md             Windows 权限、锁文件、跨盘搬迁
  deep-scan.md                    直读深扫与差额对账
  data-source-comparison.md       Everything vs WizTree 实测
  everything-integration.md       两个工具的部署与 CLI 用法
  windows.md / macos.md           系统存储布局
  lessons-learned-windows.md      踩坑记录
  win11-*.md                      三轮实战案例
assets/report_template.html       报告模板
state/                            本地运行档案，已 gitignore
```

## 已知限制与未验证项

| 项目 | 状态 |
|------|------|
| macOS 全流程 | 上游实现保留，本仓库未复验 |
| macOS 增量审计 | 无 CSV 通路，四件套不可用 |
| Linux | 不支持 |
| WizTree 管理员模式 | 预期补齐受保护目录，本仓库未实测 |
| Windows 回收站删除 | 代码已实现，尚未完整实测 |
| 扫描与实占差额 | 系统还原点、NTFS 元数据、ACL 受限目录读不到，这部分差额删文件也回收不了 |
| 分析一致性 | 依赖 Agent 判断，同一盘不同轮次结论可能不同 |
| 大目录耗时 | `walk` 模式百万文件级需数十分钟 |

## 扫描临时文件

`scan.py` 会在 `%TEMP%` 留下 `scan_<盘符>.csv`。本机实测 `scan_C.csv` 241 MB + `scan_D.csv` 260 MB，合计约 501 MB。

这些 CSV 是增量审计与清理后复扫的必需输入，**扫描完不能立即当垃圾删**。按 SKILL.md Step 5 的规则处理：

1. 报告交付、用户确认不再复扫后，Agent 主动询问是否删除。
2. 用户还要做前后对比，就保留到复扫结束再提醒。
3. 用户事先授权「不用问直接删」，才直接在默认节点删除。

删除时只动 `%TEMP%\scan_<盘符>.csv` 与 `.wiz` 残留，`%TEMP%` 下其他文件一律不碰。

## 隐私

`state/` 是本机运行档案，包含个人目录路径与定性结论，已加入 `.gitignore`，不会上传。报告服务只绑定 `127.0.0.1`，带随机 token 与 `$HOME` 路径校验。

## 许可

MIT，见 [LICENSE](LICENSE)。原项目版权归 数字生命卡兹克，本仓库的改造部分归 ChenChen913。
