# 2026-07-15 优化案例：并行执行 + 应用卸载后重扫

## 场景

用户要求：
1. 卸载通义灵码（不用了）
2. 重跑全盘分析
3. 优化速度（"体验感有点差"）

## 操作：卸载应用

通义灵码共 4 处，全部是本地文件（无注册表安装记录）：

| 位置 | 大小 |
|------|------|
| `C:\Users\<user>\.lingma` | 2.4 GB |
| `D:\lingma` | 1.3 GB |
| `.vscode\extensions\alibaba-cloud.tongyi-lingma-2.5.20` | 220 MB |
| `.trae-cn\extensions\alibaba-cloud.tongyi-lingma-2.6.2-universal` | 237 MB |

**检查清单（卸载前必须确认）：**
1. 搜索所有 IDE 扩展目录（.vscode/.cursor/.trae-cn/.codebuddycn 等）是否安装了该扩展
2. 检查 ~/、D:/ 根目录是否有同名数据目录
3. 检查 AppData/Local 和 AppData/Roaming 是否有残留
4. 检查 Windows 注册表是否有安装记录
5. 确认用户确实不再使用

删除后 C 盘从 178.4 GB → 175.5 GB（-2.9 GB），可用 21.6 → 24.5 GB。

## 速度优化对比

### 第一轮（慢）
- C 盘 scan: 107.8s（串行）
- D 盘全量递归: >180s 超时（不得不改用 drilldown）
- 18 个 drilldown: 逐条串行 ~120s
- **总耗时 ~5 分钟**

### 第二轮（优化后）
- C 盘 scan + D 盘 drilldown: 并行 ~83s
- 12 个 drilldown: 每批 6 个并行，3 轮 ~20s
- 构建分析 JSON: 直接修改上一轮模板 ~10s
- **总耗时 ~2 分钟**

### 关键优化手段

1. **C 盘 scan.py + 非系统盘 drilldown.py 同时后台跑**（terminal background=true + notify_on_complete=true）
2. **drilldown 一律 6 个并行**（每轮 6 个 terminal 调用）
3. **分析 JSON 复用模板**（只改 disk_used/disk_free 数字和受影响的条目，不从头写）
4. **等 scan 完成前就开始 drill**（C 盘扫完立刻 drill，不用等 D 盘）

## 副作用

删除大量文件后，scan.py 扫描变快（文件少了）：
- 第一轮: 107.8s（178.4 GB，含灵码 2.4 GB 的 ~50 万文件）
- 第二轮: 42.6s（175.5 GB，文件数减少）

## 验证

重扫确认：
- .lingma 从 user_profile Top5 消失
- C 盘 used 下降 2.9 GB（本地 lingma 数据）
- D 盘 used 下降 ~1.2 GB（D 盘 lingma 数据）
- VS Code 和 Trae CN 扩展目录不再含 lingma
