# Windows 常见应用缓存安全路径（纯缓存 vs 用户数据）

> 本文件按需阅读：对浏览器 profile / 微信 / QQLive 等应用数据目录做 🟢 分类或执行删除前必读。

## 目录

- 浏览器（Edge / Chrome）
- 微信（xwechat）
- 腾讯视频（QQLive）
- 包管理器缓存
- 应用更新器残留

分析时，对每个 🟢 候选项目必须用 `drilldown.py` 深入到子目录级别，判断哪些是纯缓存（可删）、哪些包含用户数据（不可删）。

**核心原则：用户数据 = 登录态（Cookies/Token）、历史记录（History）、偏好设置（Preferences）、扩展数据（Extensions）、应用自身数据库。缓存 = 临时文件、编译产物、下载缓存、日志。**

---

## 浏览器（Edge / Chrome）

Profile 路径：`%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\`（Edge）
或 `%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\`（Chrome）

> **⚠️ Chrome profile 名称不一定是 Default**：用户可能有多个 profile，活跃的可能叫 `Profile 1`、`Profile 2` 等。默认路径 `Default` 可能为空。**先 drilldown `User Data` 顶层找最大的 profile 目录**，不要盲信 `Default`。Chrome User Data 顶层还有独立的全局缓存目录（`component_crx_cache`、`extensions_crx_cache`、`GrShaderCache`、`optimization_guide_model_store`），不在 profile 内，也是纯缓存可安全清理。

| 子目录/文件 | 类型 | 可删？ | 说明 |
|------------|------|--------|------|
| `Service Worker\` | 纯缓存 | ✅ | PWA 离线缓存，删后自动重建 |
| `Cache\` | 纯缓存 | ✅ | 网页图片/资源缓存 |
| `Code Cache\` | 纯缓存 | ✅ | 已编译 JS 字节码缓存 |
| `GPUCache\` | 纯缓存 | ✅ | GPU 着色器缓存 |
| `DawnCache\` | 纯缓存 | ✅ | WebGPU 缓存 |
| `Shared Dictionary\` | 纯缓存 | ✅ | 压缩字典 |
| `load_statistics.db` | 纯缓存 | ✅ | 自动再生的统计文件 |
| `Extensions\` | 扩展数据 | ❌ | 已安装扩展及其数据 |
| `History` / `History-journal` | 用户数据 | ❌ | 浏览历史 |
| `Cookies` / `Cookies-journal` | 登录态 | ❌ | 删除后所有网站需重新登录 |
| `Preferences` | 设置 | ❌ | 浏览器设置 |
| `Local Storage\` | 用户数据 | ❌ | 网站本地存储 |
| `IndexedDB\` | 用户数据 | ❌ | 网站数据库 |
| `Session Storage\` | 会话数据 | ❌ | 当前会话 |
| `Bookmarks` / `Bookmarks.bak` | 用户数据 | ❌ | 书签 |
| `Login Data` / `Login Data-journal` | 登录态 | ❌ | 保存的密码 |

### 只删纯缓存目录

`Cache/`、`Code Cache/`、`GPUCache/`、`Service Worker/`、`DawnCache/`、`Shared Dictionary/`、`component_crx_cache/`、`extensions_crx_cache/`（注意不是 `Extensions/` 本身）、`GrShaderCache/`。

### 清理操作流程

1. 先 `drilldown.py` 深入 profile 目录，逐项识别缓存 vs 用户数据
2. 列出要删的精确路径给用户确认
3. 删除前检查浏览器是否在运行（`tasklist | grep -i "chrome|msedge"`），有 msedgewebview2.exe 也要杀
4. 只 `rm -rf` 缓存子目录，不动文件级别的 Cookies/History 等
5. 删完后验证 Cookies 和 Login Data 文件仍然存在

### 登录态逐文件快照核对（必做）

删除前后对 `Cookies`、`Login Data`、`Web Data`、`History`、`Preferences`、`Bookmarks`、`Extensions` 逐项比字节数（文件被锁时用 `os.stat().st_size`）。Chrome 运行时 `Cookies` 被独占锁（读会 `PermissionError`），此时只能删 `Code Cache` 与 `User Data\{component_crx_cache,extensions_crx_cache}`；`Cache` / `Service Worker` 需先关浏览器。为绝对避免用户重新登录，可主动跳过 `Service Worker`（它是唯一可能携带站点级会话数据的目录）。

### Chrome 运行时会锁住缓存文件

删除 Chrome 缓存目录（如 `Shared Dictionary`、`Code Cache`）时，如果 Chrome 正在运行，文件可能被锁定：

```
rm: cannot remove '.../Shared Dictionary/db': Device or resource busy
```

- 先关闭 Chrome，再删缓存目录
- 或告知用户：该缓存项需关掉浏览器后才能清理，下次关闭 Chrome 时自动释放
- `Code Cache` 和 `extensions_crx_cache` 通常不被锁，可以边用 Chrome 边删

### 运行中应用锁文件

Chrome、微信等运行时会将部分文件锁定（`mmap`、`db` 文件）。删除时遇到 `Device or resource busy` 不用慌——关掉应用后自动释放，或告知用户该缓存项需下次关闭应用时清理。

---

## 微信（xwechat）

路径：`%APPDATA%\Tencent\xwechat\`

| 子目录 | 类型 | 可删？ | 说明 |
|--------|------|--------|------|
| `log\` | 纯日志 | ✅ | mm_YYYYMMDD.xlog 运行日志 |
| `radium\web\profiles\*\Cache\` | 纯缓存 | ✅ | 内嵌浏览器缓存 |
| `radium\web\profiles\*\Service Worker\` | 纯缓存 | ✅ | PWA 缓存 |
| `radium\web\profiles\*\Code Cache\` | 纯缓存 | ✅ | JS 编译缓存 |
| `radium\users\*\applet\` | 用户数据 | ❌ | 小程序数据，含登录态和状态 |
| `radium\users\*\xworker\` | 用户数据 | ❌ | 小程序 worker 数据 |
| `radium\users\*\*` 下的 History/Cookies/Preferences | 用户数据 | ❌ | 浏览器 profile 用户数据 |
| `xplugin\` | 核心组件 | ❌ | 小程序框架、OCR、播放器等核心插件 |
| `radium\web\profiles\*\` 下的非 Cache 目录 | 用户数据 | ❌ | 含浏览历史等 |

---

## 腾讯视频（QQLive）

路径：`%APPDATA%\Tencent\QQLive\`

| 子目录 | 类型 | 可删？ | 说明 |
|--------|------|--------|------|
| `WxMiniGame\` | 缓存 | ✅ | 小游戏平台缓存 |
| `TCGamer\` | 缓存 | ✅ | 游戏平台缓存 |
| `Webkit3\` | 引擎缓存 | ✅ | 浏览器引擎缓存 |

---

## 包管理器缓存

| 包管理器 | 缓存路径 | 清理方式 |
|---------|---------|---------|
| npm | `%LOCALAPPDATA%\npm-cache\` | `npm cache clean --force` |
| pip | Python 内部 | `python -m pip cache purge`（不要用裸 `pip`） |
| uv | `%APPDATA%\uv\` 内部 | `uv cache clean` |
| Bun | `~\.bun\install\cache\` | 直接删 cache 目录，不动 `~\.bun\bin\` |
| Cargo | `~\.cargo\registry\` | 直接删 registry，不动 `~\.cargo\bin\` |
| WinGet | `%LOCALAPPDATA%\Microsoft\WinGet\Packages\` | 直接删 |

---

## 应用更新器残留

路径：`%LOCALAPPDATA%\*-updater\`

内部通常是 `pending\` + `installer.exe`（更新包 + 安装器），全部可删。常见命名形态：
- `@<app>-updater`（作用域式，多为 Electron 应用）
- `<app>-updater`
- `<vendor>.<app>.app-updater`（反向域名式）

判定方法：目录里只有 `pending\`、安装器或 `*.nupkg` 一类更新包时属纯缓存；若含用户配置、数据库或登录态，降级为黄灯。
