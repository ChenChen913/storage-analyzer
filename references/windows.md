# Windows 数据布局与分级参考

分析 Windows 扫描结果时读这份。讲"东西存在哪、怎么辨认、归哪一级"。
注意：Windows 代码路径在 macOS 上无法验证，分析时对路径存在性保持谨慎。

## 多盘符

Windows 通常多个盘（C:、D:…）。磁盘总览会列出所有盘，但**分析和清理聚焦系统盘 C:**——缓存、AppData、临时文件几乎都在 C:。其他盘（D: 等）一般是用户自存的资料/游戏，归 🟡 让用户自己判断，不要自动给删除按钮。

## 关键目录

| 目录（环境变量） | 装什么 | 典型分级 |
|---|---|---|
| `%LOCALAPPDATA%`（`C:\Users\<u>\AppData\Local`） | 浏览器缓存、应用数据、Temp，最大头 | 缓存 🟢 / 应用数据 🟡 |
| `%LOCALAPPDATA%\Temp`、`%TEMP%` | 临时文件 | 🟢 |
| `%APPDATA%`（Roaming） | 应用配置/数据 | 🟡 |
| 浏览器缓存 `%LOCALAPPDATA%\Google\Chrome\User Data\*\Cache`、Edge 同构 | 浏览器缓存 | 🟢 |
| 浏览器 `User Data\<Profile>`（非 Cache 部分） | 书签/登录态 | 🟡 |
| `%USERPROFILE%\.cache`、`.npm`、`.gradle`、`.m2`、`.nuget\packages`、`%LOCALAPPDATA%\pip\Cache`、`Yarn` | 开发缓存 | 🟢 |
| `C:\Program Files`、`Program Files (x86)` | 应用本体 | 🔴 仅重复/想卸时上灯，否则归蓝色 |
| `%USERPROFILE%\Downloads` 的安装包 | exe/msi 残留 | 🟢 |
| `C:\\$Recycle.Bin` | 回收站 | 🟡 提示用户清空 |
| `%APPDATA%\\Tencent\\xwechat` | 微信应用数据（浏览器引擎 radium + 系统插件 xplugin + 日志），**不是用户收发文件**（文件通常在 D 盘或用户指定路径） | radium 浏览器缓存 🟢 / xplugin 核心组件 ❌不能动 / log 🟢 |
| `%APPDATA%\\Tencent\\QQLive` | 腾讯视频缓存 | 🟢 纯缓存 |
| `%APPDATA%\\Tencent\\WeMeet` | 腾讯会议缓存/记录 | 🟡 含会议数据 |
| `%APPDATA%\\Tencent\\Yuanbao` | 元宝 AI 助手 | 🟡 |
| `%APPDATA%\\LarkShell` | 飞书桌面端（内嵌 Chromium 浏览器 profile），**不含 CLI**（CLI 在 npm 全局包 `@larksuite/cli`） | 🟡 profile_explorer 浏览器缓存 🟢 / profile_main 应用数据 🟡 |
| `%APPDATA%\\npm` | npm 全局安装的 node_modules | 🟡 需逐个确认哪些包不再需要 |
| `%APPDATA%\\npm-cache` | npm 下载缓存（和上面不同——这个是缓存，那个是已安装包） | 🟢 |

## 常见大型应用识别

### 微信 (xwechat)
- **radium**：内嵌 Chromium 浏览器引擎。`radium/web/profiles/` 下是标准 Chrome profile（Cache/Code Cache/History/Local Storage/IndexedDB 等）。**只删 Cache/Code Cache/GPU 缓存目录**，不动 History/Preferences/Local Storage。
- **xplugin/Plugins**：系统级插件（RadiumWMPF 小程序框架、WeChatOcr、XEditor、WeChatPlayer 等），**绝不能删**。
- **log**：可全删。
- **常见误解**：用户可能已把"文件存储"改到 D 盘，但 AppData 下的应用本体数据仍在 C 盘——这是微信设计，两者独立。

### 飞书 (LarkShell)
- **profile_explorer**：Chromium browser profile，Service Worker 通常占大头（飞书网页应用的 JS/资源缓存）。
- **profile_main**：主应用数据库和设置。
- **CLI 不在这里**：`lark-cli` / `@larksuite/cli` 是 npm 全局包，在 `%APPDATA%\npm\node_modules\`。卸载飞书桌面端不影响 CLI。

### npm 全局包
- 路径：`%APPDATA%\npm\node_modules\`
- 问题：目录树深、文件多，`du -sm` 容易超时。**用 Python `os.walk` 脚本或 drilldown.py 逐包计算大小**。

## 系统占用（不上灯，归蓝色"系统及其他"，间接释放写 long_term）

- `C:\Windows\WinSxS`：组件存储，**绝不能手删**，用 `DISM /Online /Cleanup-Image /StartComponentCleanup`
- `C:\Windows\SoftwareDistribution\Download`：Windows Update 缓存，用磁盘清理处理
- `hiberfil.sys`（休眠）、`pagefile.sys`（虚拟内存）：系统管理，别手动删
- 间接释放：设置 > 系统 > 存储 > 存储感知；`cleanmgr`（磁盘清理）；扩展磁盘清理选 Windows 更新清理

## 删除机制

`server.py` 在 Windows 用 ctypes 调 `SHFileOperationW`(FOF_ALLOWUNDO) 送进回收站；纯标准库。🟢 项的 `trash_paths` 应在用户配置文件（`%USERPROFILE%`）目录内，便于白名单与 HOME 越界校验通过。
