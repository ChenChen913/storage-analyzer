# Windows 11 实测案例 (2026-06-03)

## 环境
- OS: Windows 11 build 10.0.26200, AMD64 (初版误报为 Windows 10，已修复)
- Python: 3.11.x (command: `python`)
- Shell: git-bash (MSYS)
- 系统盘 + 一块非系统盘，均为 NTFS

## 扫描结果概要
系统盘使用率约九成，非系统盘约八成，两盘合计百万级文件。

### 占用大户（分类）
| 组 | 说明 |
|----|------|
| user_profile | 整用户目录，含 AppData |
| appdata_local | 开发工具、包管理器缓存、浏览器缓存 |
| appdata_roaming | npm 全局包、桌面应用配置 |
| dev_caches | IDE 缓存、编辑器扩展、开发工具点目录 |
| 非系统盘应用数据根目录 | 各类日常应用的数据目录 |

### 分类统计（定性）
- 🟢 可自动清理：缓存、安装包残留为主。
- 🟡 需人工判断：用户数据、项目代码、应用数据，非系统盘项目基本都归这一级。
- 🔴 谨慎清理：应用本体与重复安装项。

## 发现的 skill 问题（已全部修复）
1. server.py 后台输出被吞 → 已加 `sys.stdout.flush()`
2. scan.py 无层级标注 → 已加 `_hierarchy` 字段
3. 缺少子目录探索工具 → 已创建 `drilldown.py`
4. 多盘分析缺失 → 已更新 SKILL.md
5. build_report.py 与 server.py 分工模糊 → 已澄清
6. 回收站需要管理员权限但无提示 → 已加文档提示
7. **Windows 11 被误报为 Windows 10** → `platform.release()` 在 Win11 上仍返回 "10"，已改为通过 build ≥ 22000 判断真实版本
