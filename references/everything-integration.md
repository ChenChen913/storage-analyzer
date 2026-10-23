# Everything 集成指南（Windows）

> 目的：让磁盘分析从"固定目标列表扫描"升级为"全盘清单 + 多维聚合"。
> 本文说明如何获取/部署 Everything 命令行工具，以及 skill 如何与之结合。

## 1. 为什么用 Everything

- 索引常驻（读 NTFS MFT），查询毫秒级；全盘文件清单导出 5-6 秒/盘（350 万文件）。
- 纯 Python os.walk 全盘遍历同样数据需要 30-90 分钟，且每次重扫。
- 增量成本为零：文件增删实时跟踪，每轮分析直接复用索引。
- 局限：只索引 NTFS 及已配置目录；索引大小与实际占用有偏差（见 lessons-learned 1.3）；依赖软件常驻。

## 2. 获取与部署

1. 从 voidtools.com 官方下载 Everything 的 zip 免安装包（含 `Everything.exe` + `es.exe`）。
2. 解压到任意目录（建议 `D:\Everything` 或 `C:\Everything`）。
3. 首次运行 `Everything.exe` 建立索引（默认索引全部 NTFS 卷）。
4. 可选配置 `Everything.ini`：`app_data=1`（用户数据放 `%LOCALAPPDATA%\Everything`）、`allow_http_server=1`。

## 3. es.exe 关键用法（CLI 客户端，通过 IPC 连正在运行的实例）

```cmd
es -version                                  # 验证可用
es -get-result-count                         # 全盘条目数
es -get-total-size                           # 全盘文件总大小
es -n 20 c:\ /on                            # 按路径排序输出
es -path d:\ /a-d -full-path-and-name -size -no-digit-grouping -export-csv out.csv -no-header
```

- `/a-d` = 仅文件；`/ad` = 仅目录；`-export-csv` 让 es 自己写文件（规避 PowerShell UTF-16 重定向问题）。
- CSV 每行格式：`"完整路径",大小`（路径带引号、可能含逗号，解析时用 `rfind('",')` 切分）。

## 4. 与 skill 的集成（scan.py 已内置）

- `find_es()`：按固定候选路径 + PATH 探测 es.exe（`D:\Everything\es.exe`、`C:\Everything\es.exe`、Program Files 等）。
- 探测成功 → `es_export_csv()` 导出全盘清单 → `combined_pass()` 单次遍历完成：
  目录聚合(2/3 层)、大文件 TopN、安装包、缓存目录、更新器目录、多版本目录。
- 探测失败 → 自动回退 `walk_export_csv()`（os.scandir 全盘遍历，慢但保证覆盖）。
- 用法：
  ```cmd
  python scripts\scan.py --drives C,D --out scan.json        # Everything 优先
  python scripts\scan.py --drives C,D --no-everything       # 强制 walk
  python scripts\scan.py --drives C --top 50 --min-dir 20   # 调整阈值
  ```

## 5. 大磁盘性能建议

- 首选 Everything：扫描成本 ≈ 0（索引常驻）。
- 无 Everything 时：
  - 多进程按盘根分片（SSD 近线性；机械盘受 IO 限制提升有限）。
  - 用 os.scandir 而非 os.walk（省 stat 调用）。
  - 先粗后细：深度 2→3→4 逐层下钻，命中才深扫。
  - 增量缓存：只重扫 mtime 变化的目录。
- 子 Agent 建议用于"多维度并行分析"（缓存/安装包/版本/系统项各一），而非 IO 扫描（瓶颈在磁盘）。
