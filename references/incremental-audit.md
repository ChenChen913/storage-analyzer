# 增量审计指南（v3，每轮必跑）

> 本文件是 SKILL.md Step 1.5 的展开说明。仅 Windows 适用：四个工具依赖全盘清单 CSV（Everything / WizTree / walk 三种数据源格式一致）与 Windows 注册表/目录布局，macOS 没有 CSV 通路，直接跳过进入 Step 2。

扫描完成后、人工分析开始前，依次跑四个增量工具。它们解决的是六轮实战暴露的结构性问题：跨轮失忆、成套清理失败、卸载残留无人认领、没审过的应用被 TopN 挤掉。

## 目录

- 四个工具与命令
- 首轮与后续轮次的顺序
- 分析过程中的写回
- 多盘与常见误用

## 四个工具与命令

```bash
# 1) 规则引擎：成组命中清理候选（plugins zip 组 / 多版本 bin / 崩溃转储 / 巨型日志）
python scripts/rules.py --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv" --out "%TEMP%\rules_hits.json"
# 输出的 green_candidates / multi_version_groups 直接进分析流程，agent 只复核不定性枚举

# 2) 卸载残留检测：数据目录存在但应用本体已不在（Programs/Program Files/WindowsApps/开始菜单/卸载注册表五重比对）
python scripts/orphan.py --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv" --min-mb 50 --out "%TEMP%\orphans.json"
# 多盘必须全传；只传 C 盘会让 D 盘目录按 0 字节处理，导致漏报
# 输出自动附最后活动时间与置信度（high/medium/low），days_idle 大的是高置信度弃用候选

# 3) 应用登记表：枚举安装侧应用（Programs / Program Files / 注册表 InstallLocation）+ 用户侧数据目录，
#    维护「未审查应用清单」。只扫系统盘会漏掉装在其他盘的应用，注册表是跨盘安装的兜底来源
python scripts/apps.py build --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
python scripts/apps.py list --unreviewed --min-mb 20
# 看完一个应用后：python scripts/apps.py mark <key> --note "结论"

# 4) 档案 diff（第二轮起）：与历史基线对比，只看增量和未定性项
python scripts/registry.py diff --csv "%TEMP%\scan_C.csv" "%TEMP%\scan_D.csv"
# 输出：新目录 / 增大≥50MB / 删后复活(活水缓存) / 未定性 / 超30天无活动的未定性目录
# 同时写 state/last_diff.json，报告用它标注「新发现 / 删后复发」
```

## 首轮与后续轮次的顺序

- **首轮**：先跑 `registry.py baseline` 建档（采集全量目录大小 + 两层 mtime 活跃度），再跑 rules、orphan、apps build。
- **后续轮次**：直接跑 `registry.py diff`，从增量清单开始。
- **分析顺序**：未审查应用清单 > diff 增量清单 > orphans（弃用嫌疑最大）> rules 命中组 > 全量 TopN 兜底。优先看“谁没被审过”，而不是“谁大看谁”。

## 分析过程中的写回

- 每个定性的目录立刻 `python scripts/registry.py mark <路径> <green|yellow|red|keep> "<一句话理由>"` 写回档案。
- 每个看完的应用立刻 `python scripts/apps.py mark <key> --note "<一句话结论>"`。
- **分析结束后**：再跑一次 `registry.py baseline` 固化本轮状态（含复活检测）。

## 多盘与常见误用

- `--csv` 支持传多个文件，缺省会自动发现 `%TEMP%\scan_*.csv`。**不要只传 C 盘 CSV 就跑 baseline**，否则 D 盘目录会被误标成“已删除”。`rules.py` 与 `orphan.py` 的 `--csv` 都接受多个值，多盘必须全传。
- PowerShell 的 `>` 写出的 JSON 带 UTF-8 BOM，`json.load` 会直接报错。用 `--out` 让脚本自己写无 BOM 文件。
- 没有跑 `diff` 就开始分析，视为流程违规。
- 手工按文件名模式挑清理项属于流程违规——必须先用 `rules.py` 拿成组结果，agent 只做复核定性。实战教训：手工按文件名模式挑了少数压缩包，同目录同类文件整批漏网，下一轮成了“新发现”。
- 脚本完整用法与设计说明见 `scripts/registry.py` / `rules.py` / `orphan.py` / `apps.py` 文件头注释。规则表可持续追加到 `scripts/rules.py` 的 RULES。
