# 报告生成指南

> 本文件是 SKILL.md Step 3 的展开说明。只在写 analysis JSON、启动报告服务或排查网页渲染问题时阅读。

## 目录

- 分析 JSON 与历史标记
- 一键删除模式与安全模型
- Windows 服务启动流程
- 静态报告（仅用户明确要求时）
- 报告结构与排版字段
- 排障
- 长期优化建议素材

## 分析 JSON 与历史标记

把分析结果写成 analysis JSON（schema 见 `scripts/build_report.py` 顶部注释）。字段名和结构必须严格对照 schema——`green`/`yellow`/`red` 是顶层数组（不是嵌套在 `tiers` 下），字段名用 `size_estimate`/`kill_processes`/`commands`/`content_profile`/`why_manual`/`disposal`/`why_keep`/`indirect_release` 等，不要自己发明。模板是 `assets/report_template.html`，所有报告都走它渲染；不存在“模板不对”，只有“JSON 格式不匹配”。

报告会自动读取 `state/last_diff.json` 和 `state/registry.json`，给每项补「新发现 / 删后复发」标记和「最后活动」时间（没有标记的就是上轮已存在）。所以**必须先跑 `registry.py diff` 再生成报告**；静态模式可用 `--no-history` 关闭。

**🟢 项必须带 `trash_paths`**（具体可删的绝对路径数组，区别于人类可读的 `path` 展示字段）——这是网页删除按钮的前提，漏了按钮就不出现。Windows 路径用反斜杠，确保在 `%USERPROFILE%` 内（白名单校验前提）。

## 一键删除模式与安全模型

默认用 `server.py` 打开报告，因为这个 skill 的核心价值就是网页上能直接清理。

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

**安全模型——三套白名单，权限从严到宽**：`rm` 只允许绿灯 `trash_paths`；`trash` 允许绿灯+橙灯 `trash_paths`（橙灯永远不能 rm）；`open`（在文件管理器打开，非破坏性）允许上述全部 + 橙灯真实 `path`。所有请求 realpath 校验 + 必须在 `$HOME` 内 + token + Host 校验，每次点击浏览器先 confirm。

## Windows 服务启动流程

即使加了 `-u` 去缓冲，agent 的 `terminal(background=true)` 模式下 `server.py` 的 stdout 可能完全不显示（实测 git-bash + Python 3.11）。

- **常规做法**：先在前台运行一次抓 URL（`timeout=15` 即可，server 启动后 1-2 秒就打印 URL），然后用 `background=true` 重新运行 `server.py`（会分配新端口），拿到新 URL 后 `browser_navigate` 打开。`server.py` 不支持 `--port` 参数，每次重启端口都是新的。
- **更省事的做法**：`execute_code` 里 `subprocess.Popen([py,"-u",server.py,json], stdout=log, creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP)`，sleep 5 读日志拿 URL；日志出现「绿灯可删 N 项」即证明 JSON 被正确解析。换报告先 `taskkill /F /PID <旧pid>`。
- **验证渲染**：`curl http://127.0.0.1:<port>/` 返回 200 + 完整 HTML 即通过（GET / 无需 token）。`browser_navigate` 缺 playwright 内核时，用系统 Chrome 无头截图兜底：
  `"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1500,3000 --screenshot=out.png http://127.0.0.1:PORT/`

## 静态报告（仅用户明确要求时）

仅当用户明确只想要一份可分享/留存的只读文件时，才用静态模式：

**Windows：**

```cmd
python scripts\build_report.py %TEMP%\storage_analysis.json %USERPROFILE%\Desktop\storage-report.html
start %USERPROFILE%\Desktop\storage-report.html
```

**macOS：**

```bash
python3 scripts/build_report.py /tmp/storage_analysis.json ~/Desktop/storage-report.html && open ~/Desktop/storage-report.html
```

## 报告结构与排版字段

报告阅读流（固定顺序）：磁盘总览卡片（容量 + 进度条 + 三色容量 pills + 系统信息，纯数据）→ 占用排行 Top5 → 执行建议 → 🟢🟡🔴 三级可折叠卡片（命令一键复制）→ 长期优化建议。即“现状 → 诊断 → 处方 → 操作 → 预防”。

- `summary.overview` 写成一句话洞察（直接说最大占用是什么、能释放多少），不要重复总/已用/可用数字——那些已在卡片大数字里显示。
- 磁盘进度条把“已用”拆成分段：绿(可自动清)+橙(需手动)+红(已识别的不建议动项)+蓝(系统及其他，自动取 已用−绿−橙−红 的余量)，余下为可用(灰底)。
- `summary.tier_stats` 的 green / yellow / red 三个值都要以可解析的 GB 数字开头（如 "约 27.8 GB"），脚本从中取数算分段。
- **多盘统计**：`tier_stats` 只填系统盘的量（否则进度条分段会超过 C 盘已用，视觉错乱）；非系统盘的 🟡/🔴 分析写进 `summary.priority` 文本，绿灯可保留跨盘卡片并标注「（D 盘）」。

## 排障

**网页上没有删除/移回收站按钮** = 要么开的是静态报告（改用 `server.py`），要么 🟢 项漏了 `trash_paths`（补上重启服务）。

## 长期优化建议素材

写进报告 `summary.long_term`。

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
