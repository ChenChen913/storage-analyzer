# 扫描执行指南（Windows / macOS）

> 本文件是 SKILL.md Step 0 / Step 1 的展开说明，只在需要确认命令、排查扫描失败或优化速度时阅读。
> 数据源横向对比见 [data-source-comparison.md](data-source-comparison.md)，Everything / WizTree 部署见 [everything-integration.md](everything-integration.md)。

## 目录

- Step 0 确认 Python 命令
- 数据源与选择规则
- 命令速查
- 覆盖保证与输出
- 大磁盘与并行技巧
- git-bash 后台执行与 execute_code
- macOS
- 扫描阶段常见故障

## Step 0 确认 Python 命令

Windows 默认没装 Python，且命令因安装方式不同而异。运行脚本前先确认：

```
python --version   # 若成功，用 python
py -3 --version    # 若成功，用 py -3
python3 --version  # 较少见，但也可能
```

记住哪个命令可用，后续所有示例中 `python3` 均替换为该命令。若三者都失败，提示用户先安装 Python 3（https://www.python.org/downloads/windows/，安装时勾选“Add Python to PATH”）。

macOS 自带 python3，无需此步。

## 数据源与选择规则

Windows 上 `scan.py` 采用数据源插件化，按 `--source` 顺序尝试。三者导出的 CSV 都会归一成同一份 `"路径",大小` 格式，后续聚合完全一致。

### Everything（首选）

自动探测 `es.exe`（`<安装目录>\Everything\es.exe`、Program Files、PATH），探测到即导出全盘文件清单（实测百万级文件秒级/盘）。单次遍历同时产出：目录聚合(2/3 层)、大文件 TopN、安装包、缓存目录、更新器目录、多版本目录。实测整盘分析约十几秒。

### WizTree（次选）

自动探测 `wiztree64.exe`（Program Files、PATH、`%LOCALAPPDATA%`），命令行读盘导出文件清单，不需要常驻服务。便携版用 `STORAGE_ANALYZER_WIZTREE=<exe 绝对路径>` 指定。默认 `/admin=0` 不弹 UAC，但普通权限会漏掉 WindowsApps、Defender 定义等受保护目录（同机实测约一成逻辑总量）；需要完整覆盖时在已提权终端加 `--wiztree-admin`。

### walk（兜底）

两个工具都没有、或 Everything 已装但未启动（`es.exe` 报 IPC window not found）时自动回退 `os.scandir` 全盘遍历，保证“全盘覆盖”而非固定目标列表。速度慢，30-90 分钟/盘。

### 怎么选

- **已装 Everything 或 WizTree：直接用已装的那个。** `--source auto` 会自动优先 Everything、其次 WizTree。
- **只装了 WizTree：** 可以直接用，但普通权限有覆盖缺口，报告里要注明；需要精确统计时在提权终端加 `--wiztree-admin` 重扫。
- **两个都没装：推荐先装 Everything。** 免费、普通权限就能全盘覆盖、重复扫描秒级（同机端到端 Everything 十几秒，WizTree 一分多钟），代价是索引常驻数百 MB 内存。
- **两个都没有又暂时不装：** 自动回退 walk，百万文件级要几十分钟，只适合应急。

`--source auto` 默认按 Everything → WizTree → walk 降级；也可 `--source everything|wiztree|walk` 强制指定（便于排查和基准测试，指定源失败则跳过该盘）。

## 命令速查

**Windows（索引工具可用时）：**

```bash
# 全部固定盘一次分析（C/D/E...），写文件避免 stdout 编码问题
python scripts/scan.py --out "%TEMP%\storage_scan.json"
# 只扫指定盘 / 调整阈值
python scripts/scan.py --drives C,D --top 50 --min-dir 20 --out "%TEMP%\storage_scan.json"
# 强制指定数据源（auto=Everything→WizTree→walk）
python scripts/scan.py --drives C --source wiztree --out "%TEMP%\storage_scan.json"
# WizTree 完整覆盖：在已提权的终端里加 --wiztree-admin（走 MFT + 受保护目录）
python scripts/scan.py --drives C --source wiztree --wiztree-admin --out "%TEMP%\storage_scan.json"
# 强制 walk 回退（排查用，等价 --source walk）
python scripts/scan.py --drives C --no-everything --out "%TEMP%\storage_scan.json"
```

**Windows（无索引工具 / 需 drilldown 时）：**

```bash
# C 盘：scan.py（两个索引工具都不可用时走全盘 walk）
python scripts/scan.py --drives C --out "C:\Users\<user>\AppData\Local\Temp\storage_scan.json" &
# D/E 盘等：drilldown.py 做顶层分析（比全量递归快 10 倍以上）
python scripts/drilldown.py "D:/" --min-mb 100 --limit 30 > "C:\Users\<user>\AppData\Local\Temp\d_scan.json" &
wait
```

两步同时跑，总等待时间 = max(scan.py, drilldown)，而非两者之和。

**macOS：**

```bash
python3 scripts/scan.py > /tmp/storage_scan.json
```

macOS 单盘（/），`du` 速度快，但多卷（外置盘等）同理并行。

## 覆盖保证与输出

每轮分析必须确认输出里有 `coverage` 字段（`method` = everything / wiztree / walk，混用时形如 `everything+walk`；另含 `es_path` / `wiztree_path` / `drives` / `files_scanned`）。全盘清单 + 大文件 TopN 兜底是“不遗漏”的最低保障；只基于固定目标列表的分析一律视为不完整（教训见 [lessons-learned-windows.md](lessons-learned-windows.md) 4.1）。

`scan.py` 自动识别系统（`sys.platform`）：

- **Windows**：全盘清单（Everything → WizTree → os.scandir 全盘遍历），单遍聚合 drive_root(depth2/3)、big_files、installers、cache_dirs、updater_dirs、version_dirs、recycle_bin、dev_caches、running_apps；`system.disks` 含所有盘符（C:、D:……）；输出含 `coverage`（method/es_path/wiztree_path/drives/files_scanned）与 `temp_artifacts`（本轮临时 CSV 清单）。
- **macOS**：扫 home、library、caches、containers、group_containers、app_support、applications、downloads、dev_caches，用 `du` 算大小；输出含 `coverage.method=du`。

输出 JSON 结构：`system` + `groups` + `coverage` + `temp_artifacts` + `_hierarchy`。读不到的目录标 `denied`，需在报告里列出并提示遗漏体量。

- **Windows 扫描耗时**：Everything 后端约十几秒/盘；WizTree 读数秒级到分钟级（视缓存与权限）；无索引工具时 walk 回退数分钟到数十分钟（百万文件级）。先告知用户预计时间。

> **回收站扫描需要管理员权限。**

## 大磁盘与并行技巧

- Everything 索引常驻，扫描成本约等于 0；无 Everything 时用多进程按盘根分片（SSD 近线性）+ `os.scandir` + 先粗后细。
- 子 Agent 建议用于“多维度并行分析”而非 IO 扫描（瓶颈在磁盘）。
- **所有 drilldown 并行批处理（每批 6 个）**：不要逐条 drill——把 10-20 个目标目录一次 6 个批量发出，每轮等待最慢的那个，3-4 轮搞定。实测耗时降到逐条串行的三分之一左右。

## git-bash 后台执行与 execute_code

**⚠️ git-bash 后台模式 + 文件重定向可能静默失败**：用 `terminal(background=true)` + `>` 重定向跑 Python 脚本时，输出文件可能始终为 0 字节（进程跑了 4+ 分钟但文件为空）。这是 git-bash 后台模式 + stdout 缓冲的已知问题，`python -u` 也救不了。

**症状：**

- `process(action='poll')` 显示 `status: running`，uptime 正常增长
- 输出文件 `ls -la` 始终 0 字节
- `tasklist` / `ps aux` 在 git-bash 中找不到 Windows Python 进程（MSYS 不跟踪 Win32 进程）
- 最终进程超时退出，文件仍为空

**立即改用 `execute_code` + `subprocess.run`：**

```python
import subprocess
script = "C:/Users/.../scan.py"
result = subprocess.run(
    ["python", "-u", script],
    capture_output=True, text=True, timeout=300
)
with open("C:/Users/.../Temp/storage_scan.json", "w", encoding="utf-8") as f:
    f.write(result.stdout)
```

实测系统盘 `scan.py` 一分钟内完成，非系统盘 `drilldown.py` 一两分钟。回退策略：后台 terminal 跑 60 秒仍为 0 字节，就 kill 并切到 execute_code。

**路径与编码补充：**

- **`$TEMP` 路径差异**：git-bash 的 `$TEMP` 指向 `/tmp`，但 `server.py` 内部用 Python 的 `os.path` 解析，可能找不到。写分析 JSON 时统一用 `C:\Users\...\AppData\Local\Temp\...` 这样的 Windows 绝对路径；用 `cygpath -w "/tmp/file.json"` 可查看对应的 Windows 路径。
- **execute_code 跑系统命令**：`tasklist` 等命令输出 GBK 编码，配 `text=True` 会抛 `UnicodeDecodeError`，加 `encoding="gbk", errors="replace"`。

## 扫描阶段常见故障

- **`es.exe` 报 `Error 8: IPC window not found`**：Everything 主程序没在跑。用 `subprocess.Popen([r"<安装目录>\Everything.exe", "-startup"], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, cwd=r"<安装目录>", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)` 启动，等 5-10 秒索引加载后用 `es -get-result-count` 验证。
- **C 盘百万文件 scan.py 超前台超时**：先让 es 单独 `-export-csv`，再 `scan.py --reuse-csv` 跳过导出阶段；或后台跑完。
- **Everything 溢出值**：某些同步盘/聊天应用的数据文件可能被报成 `18446744073709551615`（2^64-1）字节。CSV 聚合时把 >4TB 的值视为无效置 0，否则总量会算出天文数字。
- **junction 幻增**：`dir_size_bytes` 跟随 NTFS junction 会循环虚增（包管理器 store 曾报数十 GB，真实只有 1 GB 余）。Windows junction 对 `Path.is_symlink()` 返回 False，必须用 `st.st_file_attributes & 0x400 (REPARSE_POINT)` 判断；Everything CSV 聚合不受影响。
- **WizTree 导出**：CLI 参数、CSV 表头与权限差异见 [everything-integration.md](everything-integration.md)。
