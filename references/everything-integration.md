# 索引工具集成指南（Everything / WizTree，Windows）

> 目的：让磁盘分析从"固定目标列表扫描"升级为"全盘清单 + 多维聚合"。
> 本文说明两个可用的索引数据源、命令行用法，以及 skill 如何自动选择与降级。

## 1. 为什么用索引工具

- 索引常驻或直读 MFT，查询毫秒级；全盘文件清单导出 5-6 秒/盘（350 万文件）。
- 纯 Python os.walk 全盘遍历同样数据需要 30-90 分钟，且每次重扫。
- 局限：只索引 NTFS 及已配置目录；索引大小与实际占用有偏差（见 lessons-learned 1.3）；Everything 依赖主程序常驻，WizTree 每次导出都要重新读 MFT。

## 2. Everything（首选）

### 2.1 获取与部署

1. 从 voidtools.com 官方下载 Everything 的 zip 免安装包（含 `Everything.exe` + `es.exe`）。
2. 解压到任意目录（建议 `D:\Everything` 或 `C:\Everything`）。
3. 首次运行 `Everything.exe` 建立索引（默认索引全部 NTFS 卷）。
4. 可选配置 `Everything.ini`：`app_data=1`（用户数据放 `%LOCALAPPDATA%\Everything`）、`allow_http_server=1`。

### 2.2 es.exe 关键用法（CLI 客户端，通过 IPC 连正在运行的实例）

```cmd
es -version                                  # 验证可用
es -get-result-count                         # 全盘条目数
es -get-total-size                           # 全盘文件总大小
es -n 20 c:\ /on                            # 按路径排序输出
es -path d:\ /a-d -full-path-and-name -size -no-digit-grouping -export-csv out.csv -no-header
```

- `/a-d` = 仅文件；`/ad` = 仅目录；`-export-csv` 让 es 自己写文件（规避 PowerShell UTF-16 重定向问题）。
- CSV 每行格式：`"完整路径",大小`（路径带引号、可能含逗号，解析时用 `rfind('",')` 切分）。
- **es.exe 只是客户端，Everything 主程序没运行时会报 `Error 8: IPC window not found`**，此时 scan.py 自动降级到 WizTree 或 walk。

## 3. WizTree（次选，没装 Everything 时用）

### 3.1 获取与部署

1. 从 diskanalyzer.com 下载 WizTree（安装版或便携版，均含 `WizTree64.exe`）。
2. 安装版默认在 `C:\Program Files\WizTree\`；便携版放任意目录。
3. 便携版不在 PATH 时，用环境变量指定：`set STORAGE_ANALYZER_WIZTREE=D:\Tools\WizTree64.exe`。
4. 免费版仅限个人使用，商用需授权。

### 3.2 命令行导出

```cmd
WizTree64.exe "C:\" /export="C:\tmp\wiz.csv" /exportfolders=0 /exportfiles=1 /admin=0
```

- `/exportfolders=0 /exportfiles=1`：只导文件行。目录行 Name 以 `\` 结尾且 Size 是子树总量，混入会导致重复计数。
- `/admin=0`：不请求提权、不弹 UAC；以管理员身份运行 scan.py 时可改 `/admin=1` 走 MFT 直读。
- 导出格式（带表头）：`File Name, Size, Allocated, Modified, Attributes, Files, Folders`。
  统一用 `Size`（逻辑大小）；`Allocated` 对硬链接文件带前导 0 标记，口径与 Everything 不一致。
- 导出完进程自动退出，不需要常驻服务。

## 4. 与 skill 的集成（scan.py 已内置）

- `find_es()` / `find_wiztree()`：按固定候选路径 + PATH + `%LOCALAPPDATA%` 探测。
- 数据源顺序由 `--source` 控制，默认 `auto`：
  1. `es_export_csv()`：es 通过 IPC 导出；
  2. `wiztree_export_csv()` + `normalize_wiztree_csv()`：WizTree 导出后归一成同一格式；
  3. `walk_export_csv()`：os.scandir 全盘遍历，慢但保证覆盖。
- 三者都落到同一份 `"路径",大小` CSV，`combined_pass()` 单次遍历完成：目录聚合(2/3 层)、大文件 TopN、安装包、缓存目录、更新器目录、多版本目录。
- 输出 `coverage.method` 记录实际数据源（`everything` / `wiztree` / `walk`，混用形如 `everything+walk`），并带 `es_path` / `wiztree_path` / `drives` / `files_scanned`。
- 用法：
  ```cmd
  python scripts\scan.py --drives C,D --out scan.json              # auto
  python scripts\scan.py --drives C --source wiztree --out scan.json
  python scripts\scan.py --drives C --no-everything --out scan.json # 等价 --source walk
  python scripts\scan.py --drives C --top 50 --min-dir 20           # 调整阈值
  python scripts\scan.py --drives C --reuse-csv                     # 复用 %TEMP%\scan_C.csv
  ```

## 5. 大磁盘性能建议

- 首选 Everything：扫描成本 ≈ 0（索引常驻）。
- 次选 WizTree：无需常驻，MFT 直读，但每次要重读一遍。
- 两者都没有时：
  - 多进程按盘根分片（SSD 近线性；机械盘受 IO 限制提升有限）。
  - 用 os.scandir 而非 os.walk（省 stat 调用）。
  - 先粗后细：深度 2→3→4 逐层下钻，命中才深扫。
  - 增量缓存：只重扫 mtime 变化的目录。
- 子 Agent 建议用于"多维度并行分析"（缓存/安装包/版本/系统项各一），而非 IO 扫描（瓶颈在磁盘）。
