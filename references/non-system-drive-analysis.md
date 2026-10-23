# 非系统盘（D:、E: 等）分析模式

`scan.py` 只扫系统盘（C:），其他盘在 `system.disks` 里只有容量/已用/可用数字，没有 groups 数据。

## 触发条件

`system.disks` 中非系统盘满足任一条件时需分析：
- 使用率 > 80%
- 已用量 > 100 GB

## 分析步骤

### 1. 顶层概览（drilldown.py，必须）

```bash
python drilldown.py "D:/" --min-mb 100 --limit 30
```

注意：用正斜杠 `"D:/"` 而非 `"D:\"`——git-bash 中反斜杠会转义引号。

这一步给出该盘的一级目录大小排行，速度快（只遍历一层），通常足够分析。超大目录（百万文件级）注意 timeout——drilldown.py 对顶层目录也是逐子目录 `os.walk` 递归，但只算一级子目录的总大小，比全盘递归快很多。

### 2. 深入可疑目录

对 Top N 中的大目录（如 DailySoft 38 GB、claudecode 23 GB）如需进一步了解内部结构：

```bash
python drilldown.py "D:/DailySoft" --min-mb 200 --limit 15
```

### 3. 不要做的事

- ❌ **不要写全量递归脚本**——对 220 GB 的 D 盘用 `os.walk` 逐个顶级目录递归必然超时（实测 180s+）
- ❌ **不要试图算出"所有文件总和"**——drilldown 顶层数据 + disks 信息够用
- ✅ **多盘数据统一进 analysis JSON**——top5 和三级分类都包含 D 盘项，disk_name/total 写清楚

## 报告中的呈现

- `system.disks` 保留所有盘信息，报告自动渲染多盘进度条
- top5 包含跨盘的大项（如 "DailySoft（D 盘）"）
- 🟡 项中 D 盘目录给 `open_note` 提示用户在资源管理器打开 → 自己判断
- D 盘的 pagefile.sys 放 🔴 或归蓝色（系统管理），不标 🟢

## 本会话实际案例（2026-07-15）

```
D: 274.7 GB 总容量，已用 220.2 GB（80.2%）
Top 项目：
  DailySoft       38.4 GB — 日常软件和数据
  it              27.3 GB — IT 项目
  claudecode      22.8 GB — Claude Code 项目
  course          15.7 GB — 课程视频
  pagefile.sys    11.0 GB — 虚拟内存（系统管理）
  aiproject       10.0 GB — AI 项目
  电影              7.6 GB — 电影文件
```

除 pagefile.sys 外，所有 D 盘项目都归 🟡（需人工判断），不给自动删除按钮。
