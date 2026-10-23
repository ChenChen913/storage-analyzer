# Windows 常见应用缓存安全路径（纯缓存 vs 用户数据）

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

内部通常是 `pending\` + `installer.exe`（更新包 + 安装器），全部可删。常见：
- `@phoenixdesktop-updater`
- `@genieworkbuddy-updater`
- `@zcodedesktop-updater`
- `typeless-updater`
- `AutoGLM-updater`
- `doc2x-updater`
- `apifox-updater`
- `taobao-updater`
- `quark-cloud-drive-updater`
- `xyz.chatboxapp.app-updater`

---

## 各类缓存清理的实际大小参考（实测）

基于本机 2026-06-27 清理前后的实际数据：

| 项目 | 实际释放 |
|------|---------|
| Edge Service Worker | ~2.7 GB |
| Edge Cache + Code Cache + 其他 | ~0.65 GB |
| npm-cache | ~1.3 GB |
| WinGet Packages | ~1.5 GB |
| Bun install cache | ~1.2 GB |
| Cargo registry | ~1.1 GB |
| 10 个更新器残留 | ~2.8 GB |
| 微信 log + radium 缓存 | ~0.44 GB |
| QQLive | ~0.88 GB |
| pip + uv | ~0.32 GB |
| **合计** | **~11.8 GB** |

C 盘使用率从 88.2% 降到 82.2%。
