# 深度扫描模式（Deep Scan）

> 触发条件：用户说“再全面深扫一遍”“感觉漏东西”，或常规分析后仍怀疑有未解释的占用。
> 常规扫描仍走 SKILL.md Step 1，本文件只在需要直读文件系统与差额对账时阅读。

## 目录

- 覆盖度审计
- 直读扫描脚本要点
- 差额对账
- 容易被漏报的实体清单
- 扫描器自己的产物

Everything CSV 路线**覆盖率高但分析深度容易不足**：本机实测 CSV 1,968,358 行 vs Everything 索引 1,968,421 个文件，只差 63 行（0.003%）——覆盖率从来不是问题，漏项都发生在“只看了 Top N 和几个大类”。深度扫描要换成直读文件系统，并做差额对账。

## 覆盖度审计（先做，30 秒）

```
cd /d/Everything
./es.exe -get-result-count                    # 索引总量
./es.exe /a-d -path "C:\\" -get-result-count  # 该盘文件数（/a-d = 排除目录，属正常用法）
```

CSV 行数与之相差应在 0.1% 以内。**校验 CSV 内容一律用 Python，不要用 bash grep**——MSYS 会把含反斜杠的模式当路径转换，导致“看起来 0 命中”的假阴性（本次被坑过：误判 Everything 漏了注册表单元，实际 CSV 里就有）。

## 直读扫描脚本要点（实测 191 万文件 / 114 秒）

- **同一份结果文件不要并发跑两次扫描**：修正参数后直接启动新进程却没 kill 前一次，两个进程写同一个 `deep_C_result.json`，事后只能靠比对 total_files 确认落盘的是哪一版。启动深扫前先 kill 上一次。
- `os.scandir` 迭代栈遍历，**不要设深度上限**（本次设 12 层导致漏 35 万文件/21GB；node_modules 树的层数轻松超过 12）。
- 跳过 reparse point（`st_file_attributes & 0x400`）：本机有 10,971 个（多是 node_modules/.bin 符号链接与 Windows 兼容链接）。跳过后 junction 内容不会重复计入。
- 记录 `denied` 目录清单（本次 106 个，全在 C:\Windows 系统区）。
- 硬链接去重：按 `(st_dev, st_ino)` 记账，`st_nlink > 1` 才算一次。**本机实测 C 盘 nlink>1 文件数 = 0**——Win11 的 WinSxS 已改用 WOF 压缩而非硬链接，别再假设“WinSxS 数字被硬链接虚增”。
- 压缩实占：`kernel32.GetCompressedFileSizeW`，但**只对 ≥1MB 的文件调用**——对全部文件调用会让 200 万文件从 2 分钟变成 90 分钟（370 文件/秒）。
- 大小要**累加到全部祖先目录**，才能得到任意深度的目录大小（本次产出 1,151 个 ≥100MB 目录）。

## 差额对账（必做，且必须在报告里解释）

`disk_used − 文件合计` 通常有 5-15GB 对不上，来源固定四类，且**这部分删文件回收不了**：

1. ACL 受限目录（注册表配置单元 `System32\config` 里 SOFTWARE 129MB/SYSTEM 22MB、Tasks、spool、WDI、WUModels、SystemTemp…）——普通权限读不到，Everything 走 MFT 能看到，直读看不到；
2. 系统还原点/卷影副本（`C:\System Volume Information`，本次 2.88GB）；
3. NTFS 元数据（$MFT / $Secure / $UsnJrnl / $LogFile，200 万文件约 2-4GB）；
4. 压缩文件逻辑大小与实占之差（本次 1.11GB）。

要把这部分定性只能用管理员身份；`fsutil`、`vssadmin`、`DISM` 在普通权限下全部“拒绝访问”。

## 容易被漏报的实体清单（下次照着逐个查）

`ProgramData\NVIDIA Corporation\Downloader`（驱动下载缓存）、`Program Files\NVIDIA Corporation\Installer2`、`Program Files (x86)\Google\GoogleUpdater`（crx_cache 可达 1GB）、`ProgramData\Package Cache`（VS/VC++ 安装缓存）、`Windows\System32\winevt\Logs`（事件日志，本次 454MB）、`Windows\WinSxS\Backup`、`Windows\WinSxS\Catalogs`、`Windows\servicing\Sessions`、`ProgramData\Microsoft\Windows Defender`（病毒库，勿删但要列）、第二套 Chrome（`Chrome Dev`）、`DoubaoIME\versions` 等多版本目录、`Saved Games`、以及**家目录下的点目录群**（本次 31 个 AI 工具点目录合计 19.4GB，只提 3 套编辑器 extensions 会严重漏报）。

## 扫描器自己的产物

`scan.py` 把全盘 CSV 写在 `%TEMP%\scan_<盘>.csv`，本机实测 **scan_C.csv 241MB + scan_D.csv 260MB = 501MB**。跑完不能直接当垃圾删——Step 1.5 与复扫依赖它；按 SKILL.md Step 5 在本轮结束、用户确认后清理。深度扫描时也可把它作为 🟢 项写进报告（本次是深扫发现的第二大绿灯项）。
