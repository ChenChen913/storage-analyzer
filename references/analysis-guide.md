# 分析与分级指南

> 本文件是 SKILL.md Step 2 的展开说明。只在开始做 TopN 分析、三级分类或清理后复核时阅读。

## 目录

- 强制分析流程（六条）
- 数据布局与分组去重
- 神秘大目录与多盘
- 三级分类标准
- 🟢 清理命令的安全写法
- 🟢 必须 drill 到子目录
- 清理后复扫与前后对比

## 强制分析流程（六条）

来自 2026-08-21 四轮实战教训（详见 [lessons-learned-windows.md](lessons-learned-windows.md) 第 6 节）：

1. **建全量目录树**：用 Everything CSV 在内存中构建完整目录树并**无阈值逐层展开**（≥15MB 节点全部打印），禁止只依赖 scan.py 的聚合 TopN——它曾连续三轮漏掉用户目录下多个 AI 工具点目录（合计数 GB）。对每个陌生目录下钻验尸到能解释每个字节。
2. **总账核对**：Everything 总量 vs `shutil.disk_usage` 实占 vs 目录树加总，三方必须对平；差额要能解释（硬链接/NTFS 压缩/MFT），解释不了就是漏项。
3. **目录定性先看内容**：禁止凭目录名推断用途（实锤：某以产品名命名的目录其实是另一品牌的数据、`recordings` 是用户录音不是模型、某应用的缓存藏在子目录而非同名 `Cache`）。`recordings/photos/docs` 默认视为用户数据进黄灯。
4. **清理成套**：浏览器缓存六件套 = Cache + Code Cache + GPUCache + Service Worker + Shared Dictionary + DawnCache，漏一个就是下一轮的“新发现”。
5. **清理后必须重新导出 CSV 复扫**，逐项确认真的没了。
6. **登录态逐文件快照核对**：删前后对比 `Network\Cookies` / `Login Data` / `Web Data` / `Bookmarks` 的存在与大小。

## 数据布局与分组去重

先看 `system.os` 判断系统，读对应的数据布局参考：Windows 读 [windows.md](windows.md)，macOS 读 [macos.md](macos.md)。

`_hierarchy` 标注 groups 之间的父子包含关系（如 Windows 的 `user_profile` 包含 `appdata_local`、`appdata_roaming`、`dev_caches`）。统计总占用时只算顶层组（`parent=None`），子组用于深入分析具体构成，避免重复统计。

## 神秘大目录与多盘

1. **挑 Top 5** 占用大户，判定类型（系统文件/应用本体/应用数据/应用缓存/开发缓存/用户文件/媒体内容/下载内容/虚拟机镜像/回收站/其他）。
2. **识别“神秘大目录”（并行批处理）**：对于 groups 中任何一个大于 1GB 的陌生目录，用 `drilldown.py` 深入一层。不要逐条调用，每批 6 个并行发出。
   ```cmd
   python scripts\drilldown.py <路径> [--min-mb 100] [--limit 20]
   ```
   输出 JSON 包含每个子项的名称、大小、是文件还是目录，比手写 Python 更可靠高效。
   - **Windows**：`%LOCALAPPDATA%` 下不认识的大目录、UUID 命名的容器；`%APPDATA%` 下异常大的配置目录。
   - **macOS**：UUID 命名的 Container。
   - 仍只读，别动文件。
3. **多盘都要分析**：`system.disks` 列出所有盘符。非系统盘使用率 >80% 或绝对已用量 >100GB 时，在报告中单独加分析段落。详见 [non-system-drive-analysis.md](non-system-drive-analysis.md)。

## 三级分类标准

三级分类 = 清理决策清单，不是全盘点。只把“存在‘要不要动它’这个决策”的项放进三灯；日常在用的正常应用、操作系统本身、海量零碎小文件没有清理决策，不进三灯，它们落在磁盘条的蓝色“系统及其他”里。

- 🟢 **可自动清理**：纯缓存、临时文件、安装包残留、明确可再生且不影响功能、不丢用户数据（`%TEMP%`、浏览器缓存、pip/npm/.gradle 等开发缓存、下载文件夹里的 .exe/.msi 安装包）。
- 🟡 **需人工判断**：含用户数据或有判断成本（下载的视频/文档、`%APPDATA%` 里的大型应用数据、聊天记录、项目代码 node_modules）。给内容画像 + 至少 3 句处置路径（应用内清理 / 系统工具 / 文件管理器手动审查，三选最合适）+ 风险提示。所有橙灯项在服务模式下自动有「在资源管理器打开」按钮；如果该项有一个核实过、删了不破坏 App 的安全子路径，给它 `trash_paths` → 网页出现「移到回收站」按钮（橙灯只准移回收站、可逆，绝不给“直接删除”）。
- 🔴 **谨慎清理（有决策但不建议手删）**：你可能想动、但建议别手删的具体项——重复安装的应用、想卸载的大应用、运行中应用的核心数据等。给“为什么不建议手删” + `indirect_release` 写具体卸载步骤（控制面板卸载 / 设置 > 应用 / 软件自带卸载器 / Store 应用直接卸载等，要可照做不是空话）。应用项给 `app_paths`（真实可执行文件或安装目录绝对路径数组）→ 网页出现「在资源管理器打开（去卸载）」按钮。红灯不给删除/卸载按钮。系统文件（WinSxS、pagefile.sys、hiberfil.sys）绝不单独列红卡，归蓝色，间接释放技巧写进 `summary.long_term`。

每个 🟢 项要给：预估释放空间、清理前需关闭的进程、`trash_paths`（网页一键移回收站的路径）。`commands` 只在用户明确要求命令行方式、或该项需要应用内清理（如 `npm cache clean --force`）时补充。

## 🟢 清理命令的安全写法

清理动作的默认入口是报告网页：agent 不在命令行代跑删除，永久删除默认关闭。下面的命令是给用户自行执行、或用于应用内清理的参考写法。

**Windows 🟢 清理命令优先选安全方式：**

- 临时文件：`del /q /f /s "%TEMP%\*"` 或直接在资源管理器删
- 浏览器缓存：浏览器内 Ctrl+Shift+Del 清理，或给出具体缓存路径供删除
- 开发缓存：`npm cache clean --force`、`pip cache purge`、`gradle cleanBuildCache` 等工具命令
- 安装包残留：给出具体文件路径，让用户自行到资源管理器删
- 谨慎用 `rd /s /q`，只用在明确的缓存子目录
- **git-bash 用户注意**：上述 `del` / `rd` 是 cmd.exe 内置命令，在 git-bash 中不可用。给用户展示命令时标注“在 cmd 或 PowerShell 中执行”，或在 git-bash 中用 `rm -rf "/c/Users/..."` 替代。

**大小字段写干净**：`size` / `size_estimate` 用“约 14 GB”“合计约 8.6 GB”即可——“约”已表示估算，不要再加“（估算）”。

## 🟢 必须 drill 到子目录

浏览器 profile、应用数据目录不能整目录标绿——必须用 `drilldown.py` 深入至少 2-3 层，把“纯缓存”和“用户数据”分开。用户数据包含：登录态（Cookies/Token）、历史记录（History）、偏好设置（Preferences）、扩展数据（Extensions）、应用自身数据库。删了这些用户需要重新登录、丢失历史。

逐子目录安全判定表见 [safe-cache-paths-windows.md](safe-cache-paths-windows.md)（Edge/Chrome、微信、QQLive、包管理器、更新器残留）。

**典型案例（Edge Default profile）：**

- ✅ 可删：`Service Worker\`（可达数 GB）、`Cache\`、`Code Cache\`、`GPUCache\`、`Shared Dictionary\`
- ❌ 不可删：`Extensions\`、`History`、`Cookies`、`Preferences`、`Local Storage\`、`Bookmarks`、`Login Data`

**典型案例（微信 xwechat）：**

- ✅ 可删：`log\`（运行日志）、`radium\web\profiles\*\Cache\`、`radium\web\profiles\*\Service Worker\`
- ❌ 不可删：`radium\users\*\applet\`（小程序登录态）、`xplugin\`（核心插件）

## 清理后复扫与前后对比

清理完绿灯项后，重跑 `scan.py` 生成对比报告。扫描时间缩短是侧面印证信号（例如从数十秒降到三十秒左右）。对比两次 `disk_used` 差值即实际释放量，比手动估准。

**前后对比脚本**——逐个 group 找出删除/缩小的目录，生成清晰的 before/after 表格：

```python
import json

with open("scan_before.json") as f:
    old = json.load(f)
with open("scan_after.json") as f:
    new = json.load(f)

freed = float(old["system"]["disk_used"].split()[0]) - float(new["system"]["disk_used"].split()[0])
print(f"释放: {freed:.1f} GB")

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

这个脚本直接告诉用户每一项目录的释放量，比笼统说“释放了 X GB”更有说服力。
