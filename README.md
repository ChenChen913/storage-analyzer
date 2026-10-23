# Storage Analyzer

> **来源**：本仓库改造自 [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) 中的 `storage-analyzer`。上游是一个包含 6 个 skill 的合集，本仓库只改造并发布了其中一个，其余 skill 的版权归原作者所有。
>
> **完整 fork**：[ChenChen913/khazix-skills](https://github.com/ChenChen913/khazix-skills)，保留上游全部内容，用于记录血缘关系。
>
> 原项目采用 MIT 许可，原版权归 数字生命卡兹克；本仓库的改造部分归 ChenChen913。

Windows / macOS 只读存储分析 Skill。流程是：全盘扫描，三级分级，生成交互式 HTML 报告。扫描阶段只读，删除命令只展示，不自动执行。

## 相比上游的主要改动

- 用 Everything 索引做全盘扫描，C/D 多盘一次覆盖，输出 coverage 字段
- 新增 rules.py、orphan.py、registry.py：成套规则命中、卸载残留检测、跨轮目录档案
- 三灯分级：可自动清理、需人工判断、谨慎清理，并生成本地报告服务
- 本地服务带 token 与路径白名单：绿灯可删，橙灯只移回收站，红灯只允许打开
- 补充 Windows 缓存安全边界、浏览器登录态保护与多轮实战案例

## 安装

把整个目录放到 agent 的 skills 目录，例如：

- Trae CN：`%USERPROFILE%\.trae-cn\skills\storage-analyzer`
- Claude Code：`~/.claude/skills/storage-analyzer`

## 使用

在对话里调用 `storage-analyzer`，或直接运行脚本：

```powershell
python scripts\scan.py --out "%TEMP%\storage_scan.json"
python scripts\rules.py --csv "%TEMP%\scan_C.csv"
python scripts\build_report.py "%TEMP%\storage_analysis.json"
python scripts\server.py "%TEMP%\storage_analysis.json"
```

## 目录结构

```text
SKILL.md
scripts/     扫描、规则、残留检测、档案、报告、服务
references/  Windows / macOS 数据布局、缓存安全边界、实战案例
assets/      报告模板
```

## 隐私

`state/` 是本地运行档案，含个人目录信息，已加入 .gitignore，不会上传。

## 许可

MIT，见 LICENSE。原项目版权归 数字生命卡兹克，本仓库的改造部分归 ChenChen913。
