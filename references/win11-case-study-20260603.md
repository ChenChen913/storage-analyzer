# Windows 11 实测案例 (2026-06-03)

## 环境
- OS: Windows 11 build 10.0.26200, AMD64 (初版误报为 Windows 10，已修复)
- Python: 3.11.14 (command: `python`)
- Shell: git-bash (MSYS)
- C: 200 GB (NTFS), D: 274.7 GB

## 扫描结果概要
C 盘 179.9 GB / 200 GB (90.0%)，D 盘 218.5 GB / 274.7 GB (79.5%)。

### 占用大户
| 组 | 大小 | 说明 |
|----|------|------|
| user_profile | 104.7 GB | 整用户目录，含 AppData |
| appdata_local | 38.4 GB | JetBrains 5G、npm-cache 3.1G、Google 2.9G 等 |
| appdata_roaming | 34.3 GB | npm 4.1G、LarkShell 3.6G、TRAE 3.5G 等 |
| dev_caches | 14.8 GB | JetBrains 5G、.cache 2.3G、VSCode ext 2.2G 等 |
| D:\DailySoft | 38.2 GB | 夸克/钉钉/百度盘/微信等 51 个应用数据 |

### 分类统计
- 🟢 可自动清理: 约 16.3 GB
- 🟡 需人工判断: 约 89.8 GB（含 D 盘）
- 🔴 谨慎清理: 约 69.3 GB

## 发现的 skill 问题（已全部修复）
1. server.py 后台输出被吞 → 已加 `sys.stdout.flush()`
2. scan.py 无层级标注 → 已加 `_hierarchy` 字段
3. 缺少子目录探索工具 → 已创建 `drilldown.py`
4. 多盘分析缺失 → 已更新 SKILL.md
5. build_report.py 与 server.py 分工模糊 → 已澄清
6. 回收站需要管理员权限但无提示 → 已加文档提示
7. **Windows 11 被误报为 Windows 10** → `platform.release()` 在 Win11 上仍返回 "10"，已改为通过 build ≥ 22000 判断真实版本
