# Windows 11 清理实战：跨盘搬迁与目录联接（2026-06-18）

## 场景

C 盘 200 GB 仅剩 16.9 GB（91.5%），经三轮清理释放 11.9 GB。第三轮涉及将 Hermes Agent 自身的 `node_modules`（1.3 GB）和 `.git`（403 MB）从 C 盘迁移到 D 盘。

## 关键技术：Windows 目录联接（Junction）

当需要将某个目录的物理存储迁到其他盘、但保持原路径可访问时，使用 `mklink /J`：

```cmd
mklink /J "C:\原路径\目录名" "D:\新位置\目录名"
```

联接是 NTFS 级别的，对应用程序完全透明——所有文件操作在 C 盘原路径照常进行，实际数据在 D 盘。

### 适用场景

- 应用不支持自定义数据路径（如微信 xwechat 的 `radium` 浏览器引擎固定在 `%APPDATA%`）
- npm `node_modules` / Git `.git` / IDE 扩展目录等大体积依赖
- 不想重装应用、不想改环境变量的情况

### 不适用场景

- Python venv（`pyvenv.cfg`、激活脚本含路径引用，虽然 junction 理论上透明但排查困难）
- SQLite 数据库（跨盘 junction 可能影响性能）
- 系统关键目录（`C:\Windows` 等）

## 跨盘移动的正确方式

### ❌ `mv`（git-bash）

```bash
mv /c/path/source /d/path/dest   # 对大目录（百万文件）经常超时，且可能部分完成
```

### ✅ `robocopy /MOVE`

```cmd
robocopy "C:\source" "D:\dest" /E /MOVE /R:2 /W:3
```

- `/E`：包含子目录（含空目录）
- `/MOVE`：复制后删除源文件
- `/R:2 /W:3`：失败重试 2 次，间隔 3 秒
- 比 `shutil.move` 更可靠，因为后者跨盘时内部 `rmtree` 可能被锁文件阻塞

### ✅ Python `shutil.move`（同盘）

同盘移动是原子操作（rename），快速安全。跨盘时等同 copy+delete，不如 robocopy。

## 实际操作流程

### Step 1：确认目标路径

```bash
ls -d "/d/hermes_data/"  # 确认 D 盘目标目录存在
```

### Step 2：robocopy 搬迁

```cmd
robocopy "C:\Users\<user>\AppData\Local\hermes\hermes-agent\node_modules" "D:\hermes_data\hermes-agent\node_modules" /E /MOVE /R:2 /W:3
```

### Step 3：创建联接

```cmd
mklink /J "C:\Users\<user>\AppData\Local\hermes\hermes-agent\node_modules" "D:\hermes_data\hermes-agent\node_modules"
```

### Step 4：验证

```bash
# 确认原路径可访问
ls "/c/Users/<user>/AppData/Local/hermes/hermes-agent/node_modules/electron/package.json"

# 确认功能正常
cd "/c/Users/<user>/AppData/Local/hermes/hermes-agent" && git status
```

## 验证清单

搬迁后逐一检查：
- [ ] Git 操作正常（`git status`、`git log`）
- [ ] npm/node 能读取模块（`ls node_modules/<key-package>`）
- [ ] 应用本身运行正常（如 Hermes 对话未中断）
- [ ] C 盘释放了对应空间（`df -h` 对比）

## 踩过的坑

1. **`mv` 部分完成**：`mv` 超时后源和目标都有文件，需要先 `rmtree` 目标再重来
2. **`rmtree` 失败（WinError 145）**：某些文件被进程锁定，用 `cmd //c "rmdir /s /q"` 更可靠
3. **`robocopy` 路径引号**：git-bash 下 `cmd //c` 传递带空格的 Windows 路径时引号转义困难，改用 `cd` 到目标目录再执行相对路径更简单
4. **`du` 超时**：搬迁后验证大小时不要对整个目录跑 `du -sh`，用 `du -sm` 分块统计
