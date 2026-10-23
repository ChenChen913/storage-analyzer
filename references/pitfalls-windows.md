# Windows 常见陷阱

> 本文件按需阅读：只在遇到命令报错、删除失败、扫描超时或跨盘搬迁时查阅。

## 目录

- git-bash 路径与命令
- 扫描与统计
- 删除与权限
- 应用与文件操作
- 清理执行阶段的坑

## git-bash 路径与命令

### `D:\` 等盘符路径的引号问题

git-bash 遇到 `"D:\"` 时，末尾的 `\"` 被解释为转义引号，导致语法错误：

```bash
python drilldown.py "D:\" --min-mb 100    # ❌ unexpected EOF while looking for matching `"'
```

**正确写法：使用正斜杠：**

```bash
python drilldown.py "D:/" --min-mb 100     # ✅
```

同理，`rm -rf "/d/..."`（MSYS 路径）和 `rm -rf "D:/..."` 都能用。这条对所有 git-bash 下的 Windows 盘符命令都适用。

### `rd` / `del` 不可用

`rd /s /q` 和 `del /q /f /s` 是 cmd.exe 内置命令，在 git-bash 下直接运行会报 `rd: command not found`。

**错误做法：**

```bash
rd /s /q "C:\Users\11853\.cache"          # ❌ rd: command not found
cmd //c "rd /s /q \"C:\path\with\space\"" # ❌ 引号转义容易出错（乱码报错）
```

**正确做法（MSYS 路径 + rm -rf）：**

```bash
rm -rf "/c/Users/11853/.cache"
rm -rf "/c/Users/11853/AppData/Local/Google/Chrome for Testing"  # 含空格也能用
```

- 路径用 MSYS 风格：`/c/` 代替 `C:\`，正斜杠
- `rm -rf` 对含空格的路径也能正确处理（加引号即可）
- 如需递归删除大量文件，`rm -rf` 速度和 `rd /s /q` 相当

## 扫描与统计

### 非系统盘全量递归扫描容易超时（>180s）

大容量非系统盘（如 D 盘 200 GB+，百万级文件）用 `os.walk` 对每个子目录递归计大小极易超时。正确做法：

1. 用 `drilldown.py "D:/" --min-mb 100 --limit 30` 做顶层分析（只遍历一层，速度快）
2. 对关心的子目录再用 `drilldown.py` 深入一层
3. drilldown 顶层数据 + `system.disks` 信息足够分析非系统盘

不要写全量递归脚本去补扫。

### `du` 在深目录树上超时

Windows git-bash 的 `du -sm` 遍历百万文件级目录（如 `node_modules`、`xwechat` 整树）时经常超时（30s+ 无输出）。不要对整棵大树跑 du。

- 用 `drilldown.py` 按一级子目录拆分（限制 `--limit` 和 `--min-mb`）
- 或写一个轻量 Python `os.walk` 脚本，逐个顶级子目录计算
- `npm node_modules` 通常约 30 个顶级包，Python 脚本 7 秒完成 vs du 超时

### 包管理器缓存的可靠清理命令

`pip cache purge` 可能因 Python 环境冲突失败（如 uv 管理的 Python 与系统 pip 不兼容）。更可靠的写法：

```bash
python -m pip cache purge    # ✅ 使用明确绑定的 Python
pip cache purge              # ⚠️ 可能指向错误环境
```

同理，`npm cache clean --force` 在 Windows 上正常，但会输出 `npm warn using --force Recommended protections disabled` — 只是提示，不影响结果。

## 删除与权限

### npm 缓存 `_npx` 子目录权限问题

`rm -rf` 删除 `npm-cache` 时，`_npx/` 下的某些包（如 playwright、playwright-core）可能包含只读文件，导致部分删除失败：

```
rm: cannot remove '.../npm-cache/_npx/.../playwright-core/...': Permission denied
```

**修复：先 `chmod -R +w` 再 `rm -rf`：**

```bash
chmod -R +w "/c/Users/<user>/AppData/Local/npm-cache" 2>/dev/null
rm -rf "/c/Users/<user>/AppData/Local/npm-cache"
```

这是已知的 npm / playwright 打包问题——npx 缓存中部分 node_modules 文件的权限位被设为只读。**优先用 `npm cache clean --force`**，只在 npm 不在 PATH 或工具命令失败时才 fallback 到 `rm -rf`。

### pnpm store 目录删除权限问题

pnpm 全局 store（如 `D:\.pnpm-store` 或 `%LOCALAPPDATA%\pnpm`）内的索引 JSON 文件可能被设为只读，`rm -rf` 会报大量 `Permission denied`：

```bash
rm -rf "/d/.pnpm-store"
# rm: cannot remove '.../xxx.json': Permission denied  （可能出现数百条）
```

**修复：先 `chmod -R +w` 再 `rm -rf`：**

```bash
chmod -R +w "/d/.pnpm-store" 2>/dev/null
rm -rf "/d/.pnpm-store"
```

如果目录特别大（数百 MB+），`rm -rf` 可能超时——用后台任务运行即可。首选清理方式仍是 `pnpm store prune`，只在 pnpm 不在 PATH 时才用直接删除。

### DENY ACL 的日志目录

`icacls` 里能看到 `<user>:(I)(DENY)(DE,DC)` 继承项时，`rm -rf` 必失败、`chmod` 无效。正解：

```
icacls <dir> /remove:d <user> /t /c /q
icacls <dir> /grant <user>:(F) /t /c /q
takeown /f <dir> /r /d y
cmd /c rmdir /s /q <dir>
```

### NVIDIA 相关目录的处理与验证

用户对显卡文件普遍很敏感，务必按此流程：

- **可安全删（用户权限即可）**：`C:\ProgramData\NVIDIA Corporation\Downloader` —— ACL 是 `Everyone:(I)(OI)(CI)(F)`，普通权限可写；内容是 GFE 下载的更新安装包 + 下载清单（`gfeupdate.json` / `status.json`），属可再生缓存。**只清内容、保留目录**，并明确告知用户 GFE 需要时会重新下载。
- **需管理员**：`C:\Program Files\NVIDIA Corporation\Installer2` —— ACL 为 `TrustedInstaller/Administrators` 独占，普通权限实测 `PermissionError`，只能给管理员 `rmdir /s /q` 命令。
- **绝对不要碰**：`ProgramData\NVIDIA\NGX`（DLSS 模型）、`ProgramData\NVIDIA Corporation\{Drs,NvBackend,ShadowPlay,NvStreamSrv,NvTelemetry,nvtopps,CrashDumps,RX}`、`Program Files\NVIDIA Corporation\*` 下驱动/服务本体、`Windows\System32\DriverStore`。
- **删前后必做健康验证**：`"C:\Windows\System32\nvidia-smi.exe" --query-gpu=name,driver_version,temperature.gpu,utilization.gpu --format=csv` 前后对比驱动版本必须一致；再 `tasklist | grep -icE "nvcontainer|NVDisplay"` 确认服务进程仍在（本机常态 4 个）。
- 判断权限别用 bash 里的 `icacls`：MSYS 会把路径参数转换坏。用 `execute_code` + `subprocess.run(["icacls", r"C:\..."])`，或直接做“创建+删除探测文件”的可写性实测。

## 应用与文件操作

### 删除 ms-playwright 会破坏 browser 工具

Hermes 的 browser 工具（browser_navigate 等）底层依赖 Playwright，其浏览器二进制存放在 `%LOCALAPPDATA%\ms-playwright\`。如果删了这个目录，browser 工具会报错：

```
browserType.launch: Executable doesn't exist at ...\ms-playwright\...
```

恢复只需：`npx playwright install`（约 2 分钟重装）。这不影响分析报告本身——server.py 启动后用户可以在自己 Chrome 里打开 `http://127.0.0.1:<port>/`。

### 跨盘移动大目录

当用户要求将 C 盘的大目录（如 `node_modules`、`.git`）搬迁到 D 盘时：

| 方法 | 可靠性 | 说明 |
|------|--------|------|
| `mv /c/src /d/dst` | ❌ 容易超时 | git-bash 的 mv 对大目录可能部分完成 |
| `shutil.move`（跨盘） | ⚠️ 可能卡住 | 内部 `rmtree` 遇锁文件会抛 WinError 145 |
| `robocopy /MOVE` | ✅ 推荐 | Windows 原生，重试机制，稳定 |

```cmd
robocopy "C:\source" "D:\dest" /E /MOVE /R:2 /W:3
```

搬迁后如需原路径仍可访问，用 `mklink /J` 创建目录联接（详见 [win11-cleanup-case-20260618.md](win11-cleanup-case-20260618.md)）。

### Ollama（Windows）安装包残留的判定与验证

`D:\ollama\OllamaSetup.exe`、`%LOCALAPPDATA%\Ollama\updates_v2\<hash>\OllamaSetup.exe` 只是安装器；模型在 `OLLAMA_MODELS`（本例 `D:\ollama\models`，就是 embedding 模型 bge-m3 的家），程序在 `D:\ollama\Program`，`db.sqlite` / `*.log` 是应用状态——**绝不能删整个 `%LOCALAPPDATA%\Ollama`**。删前删后都用 `curl -s --noproxy 127.0.0.1 http://127.0.0.1:11434/api/embed -d '{"model":"bge-m3","input":"测试"}'` 比对向量 md5 指纹。

**⚠️ 跑 `ollama list` 会触发自动升级**：Windows 上 CLI 会拉起 app wrapper，发现有 pending 更新就静默安装（本次 0.34.3 → 0.34.4，安装过程会长时间占用 `D:\ollama\Program`）。要测试请用 `ollama serve` + curl，别用 `ollama list`；若升级已在跑，等 `OllamaSetup.exe` 进程退出再动手。

## 清理执行阶段的坑

1. **agent 工作区千万别放 `%TEMP%`**：绿灯项里常有 `rm -rf "$TEMP"/*`，会把分析 JSON、目录树缓存、query 脚本一起删掉。工作目录改用 `%LOCALAPPDATA%\hermes\scan-work\`。
2. **Everything 溢出值必须过滤**：极端大值（2^64-1）要置 0，详见 [scan-workflow.md](scan-workflow.md)。
3. **浏览器删除前后逐项核对登录态**：见 [safe-cache-paths-windows.md](safe-cache-paths-windows.md)。
4. **server.py 启动与渲染验证**：见 [reporting-guide.md](reporting-guide.md)。
5. **多盘 `tier_stats` 只填系统盘量**：见 [reporting-guide.md](reporting-guide.md)。
