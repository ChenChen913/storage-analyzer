# storage-analyzer 修复清单

对照外部静态审查报告与本地代码复核结果。每完成一项即在方框内打勾，全部完成后做真实测试与自查，再推送 GitHub。

本轮不处理项单独列在最后一节，写明理由。

## 第二轮：报告 02 复核后的遗留问题

- [x] R1 测试隔离：真实回收站用例改为 `SA_REAL_RECYCLE=1` 才执行，默认跳过，避免污染用户回收站
- [x] R2 回收站异常测试：用 mock 覆盖 SHFileOperation 返回失败/取消，确认失败不降级、逐项报错
- [x] R3 HTTP 负向测试：补缺 token、非法 mode、非法方法、显式 `..` 穿越、非白名单路径
- [x] R4 审计加固：追加写加锁；补批量总数、成功数、失败数与动作类型
- [x] R5 Everything 覆盖声明：coverage 增加索引覆盖无法独立验证的提示；文件数为 0 但磁盘已用时标 suspect/partial；WizTree 普通权限判 partial/limited
- [x] R6 并发扫描隔离：扫描入口使用 `state/scan.lock` 跨进程锁，避免两个扫描互相覆盖 CSV
- [x] R7 CI：新增 GitHub Actions，Ubuntu + Windows 跑编译检查与默认测试
- [x] R8 版本与变更记录：新增 CHANGELOG，推送后打 `v0.2.0` 标签
- [x] R9 文档补齐：README 增加 FAQ、测试隔离与 Everything 覆盖限制；SKILL 增加输出契约与异常处理章节
- [x] R10 前端逐项失败展示：批量与单项操作显示每条失败路径与原因，不只显示首个错误
- [x] R11 完整调用一次 skill：两盘扫描 4,132,781 文件（Everything 失败 → WizTree 降级，coverage 正确标 `partial` / `limited`）→ rules（3 绿组、247 需确认）→ orphan（47 项、高置信 11）→ apps（217 应用）→ registry（110 个新目录）→ 报告页 7 个区块正常、无 JS 报错；未启用 `--allow-rm` 时页面无“直接删除”；沙箱项真实移入回收站并写入 `action=batch` 审计
- [x] R12 自查与测试：35 项测试通过（1 项真实回收站按需跳过），`py_compile` 全部通过，Markdown 文档无本机路径 / 用户名等个人数据
- [x] R13 推送 GitHub：12 个新增/修改文件经 Git Data API 上传，远端 blob 哈希与本地逐一一致；仓库中不含 `state/`、临时 CSV 与个人数据；已打 `v0.2.0` 标签
- [x] R14 JSON `--out`：`rules.py` / `orphan.py` 增加 `--out` 直接写 UTF-8 无 BOM 文件
- [x] R15 orphan 多 CSV：`--csv` 改为 `nargs="+"` 并合并多盘树，与文档一致
- [x] R16 CI 修复：`RulesTests` 改用本机路径分隔符，Linux runner 可验证规则分组；Windows 盘符/临时清单契约测试仅在 Windows 执行

## 第三轮：报告 03 复核后的路径安全修复

- [x] R17 盘符根包含判断：允许根带尾分隔符时不再拼成双分隔符，`--allow-root "D:\"` 可正常放行 `D:\Cache`，同时不误放行 `D:\Cache2`
- [x] R18 白名单按报告原始路径匹配：报告列出的链接不再连带放行它指向的目标，目标路径必须自己出现在白名单
- [x] R19 链接位置校验：junction / 符号链接只校验自身是否在允许根内，目标无需在根内；根外链接直接拒绝
- [x] R20 悬空链接处理：存在性判断与删除后复核改用 `lexists`，悬空链接按已删除处理，不再误报 missing
- [x] R21 回归测试：新增盘符根、目标扩张、根外链接、链接只删自身、悬空链接、load 白名单来源共 6 项，41 项测试通过
- [x] R22 文档与版本：README 路径护栏与测试矩阵、SKILL 安全模型、CHANGELOG 0.2.1
- [x] R23 全量测试与自查：41 项测试通过（2 项按需跳过）、`py_compile` 通过、文档隐私复查并替换一处示例 bundle id
- [x] R24 完整调用一次 skill：两盘扫描 413 万文件（WizTree、coverage 标 partial/limited）→ rules（3 绿组、247 需确认）→ orphan（47 项、高置信 11）→ apps（217 应用）→ registry（113 个新目录）→ 报告页 7 个区块正常、无 JS 报错、无可见“直接删除”；浏览器点击自检沙箱后真实进入回收站，审计写入 `action=batch`；`--allow-root "D:\"` 下 `D:\Cache` 放行、`D:\Cache2` 仍拒绝
- [x] R25 CI 复核：Windows runner 的 `%TEMP%` 为 8.3 短名 `RUNNER~1`，allowlist/根目录若为长名会把合法路径误判为“不在白名单 / 路径越界”，7 项 HTTP 测试失败
- [x] R26 短名归一：`raw_norm` 用 `GetLongPathNameW` 只展开已存在前缀的 8.3 短名、不解析 junction，`_within_roots` 两侧统一走同一套归一；新增短名/长名等价回归测试，42 项通过
- [ ] R27 推送 GitHub：重跑 CI 全绿，核对远端 blob 哈希，打 `v0.2.1` 标签

## A 安全

- [x] A1 永久删除默认关闭：`server.py` 增加 `--allow-rm`，未显式开启时拒绝 `rm`，网页隐藏“直接删除”按钮
- [x] A2 危险路径 denylist：家目录根、盘符根、AppData、Documents/Desktop/Downloads、Program Files 根、Windows/System32 等即使误入白名单也拒绝
- [x] A3 junction / 符号链接只删除链接本身，不递归进目标
- [x] A4 Windows 回收站校验：检查返回码、`fAnyOperationsAborted`，并确认源路径确实消失
- [x] A5 操作审计：每次 rm/trash/open 追加写入 `state/audit.jsonl`
- [x] A6 批量删除确认框列出全部路径，不只是数量与估算大小
- [x] A7 服务端逐项返回结果，单项失败不中断整批，前端按路径标记成功/失败
- [x] A8 支持 `--allow-root` 显式放行非 HOME 盘符，解决跨盘绿灯项按钮不可用
- [x] A9 HTML 注入加固：JSON 注入转义 `</script>`，`esc()` 补单引号

## B 扫描可信度

- [x] B1 Everything 导出后用 `-get-result-count` 校验行数，严重不全时判失败并回退
- [x] B2 walk 统计权限拒绝目录数与错误，不再静默跳过
- [x] B3 `coverage` 增加逐盘来源、回退原因、denied 计数、partial 状态
- [x] B4 报告页展示扫描可信度摘要（数据源、文件数、回退、未读取目录）

## C 规则与残留

- [x] C1 `rules.py` 输出区分 `green_candidates` 与 `review_candidates`，宽泛基名与巨型日志降级为待确认
- [x] C2 修复版本排序（支持 `2.6.10-beta`），多版本组降级为“需按启动器确认”而非直接判旧版可删
- [x] C3 `orphan.py` 输出证据链（检查了哪些安装源、名称变体、闲置天数）与置信度依据
- [x] C4 `orphan.py` 收紧名称弱匹配，降低误判为“已安装”的概率

## D 状态可靠性

- [x] D1 新增 `statefile.py`：原子写、损坏文件隔离、文件锁
- [x] D2 `registry.py` 接入原子写与锁，读改写全程持锁
- [x] D3 `apps.py` 接入原子写与锁
- [x] D4 对旧 schema / 字段缺失做兼容归一

## E 文档与工程

- [x] E1 `SKILL.md` 修正“删除命令只展示不执行”与网页一键删除的矛盾
- [x] E2 `SKILL.md` 同步跨盘路径与 `--allow-rm` / `--allow-root` 说明
- [x] E3 `README.md` 增加安全模型、测试命令与验证状态
- [x] E4 `LICENSE` 恢复标准 MIT 文本，新增 `NOTICE` 记录上游与改造来源
- [x] E5 新增 `tests/` 自动化测试（路径护栏、删除开关、回收站、注入、状态、规则、扫描）
- [x] E6 真实运行测试：单元测试 + 临时沙箱扫描 + 真实回收站操作 + 服务端 HTTP 集成
- [x] E7 自查：逐条回读审查报告，确认问题是否残留（结论见下）
- [x] E8 推送 GitHub 并核对远端（36 个文件 blob 哈希与本地逐一一致）

## E7 自查结论

测试证据：`python -m unittest discover -s tests -v`，35 项通过、1 项按需跳过（Windows 真实执行；真实回收站用例需 `SA_REAL_RECYCLE=1`，默认跳过以免污染回收站）。

| 审查报告条目 | 自查结果 |
|--------------|----------|
| 3.1 统一删除入口 | 已解决：唯一写盘入口是网页按钮，Agent 不代跑删除；批量确认列出全部路径；批量只处理绿灯卡片，服务端二次校验；逐项返回结果 |
| 3.2 永久删除默认关闭 | 已解决：`--allow-rm` 未开启时服务端 403 拒绝且前端不渲染按钮；服务端校验独立于前端 |
| 3.3 路径按真实对象校验 | 基本解决：realpath、根目录前缀（防 `C:\Data` 放行 `C:\Database`）、denylist、junction 只删链接；TOCTOU 残余风险已在 README 明确说明 |
| 3.4 回收站实现验证 | 已解决主要场景：返回码、`fAnyOperationsAborted`、源路径消失三项校验；实测文件/中文空格/空目录/非空目录/只读/批量；取消、占用、超长路径、网络盘未覆盖并已写入文档 |
| 3.5 危险操作审计 | 已解决：`state/audit.jsonl` 追加记录时间、动作、逐路径结果与失败原因；README 说明其含本地路径及清理方式 |
| 4.x 自动化测试 | 部分解决：已建 `tests/` 并覆盖路径、删除、回收站、注入、状态、规则、扫描、HTTP；未建 CI |
| 5.1 扫描完整性表述 | 已解决：`coverage` 输出数据源、逐盘来源、partial、回退原因、denied、errors，并在报告页展示 |
| 5.2 回退可观测性 | 已解决：Everything 导出用 `-get-result-count` 比对，低于 98% 判失败并记录回退原因 |
| 5.3 规则与残留允许“不确定” | 已解决：`review_candidates` 独立输出，宽泛基名与巨型日志降级；orphan 输出证据链并在证据不全时降置信度 |
| 6.x 状态与并发可靠性 | 已解决：原子写、损坏隔离、线程/跨进程锁、旧 schema 归一；测试覆盖 3 进程并发 |
| 7.x 代码结构 | 部分解决：只做契约测试，未拆分 `scan.py`（见“本轮不处理”） |
| 8.x HTML 与前后端一致性 | 已解决：`</script>` 转义、单引号转义、批量数量/路径与逐项结果一致；空数据、超长路径、中文路径有稳定展示 |
| 9.x 文档 | 部分解决：README/SKILL/参考文档已对齐实际实现；未把长文迁移到 `docs/`（见“本轮不处理”） |

## 本轮不处理

| 项目 | 理由 |
|------|------|
| 拆分 `scan.py` | 无自动化测试前大重构风险高于收益，先补测试与契约 |
| 全量 JSON Schema / 强类型 | 现有测试已覆盖关键契约，引入 schema 库违背“纯标准库”约束 |
| README 长文迁移到 `docs/` | 属于结构调整，不影响安全与功能，等文档整体改版时再做 |
| 改写 git 历史去除脱敏前数据 | 破坏性操作，需用户单独授权 |
| `orphan.py` 扫描其他盘便携应用 | 候选泛化会显著增加误报，先保留用户目录范围并在文档标注 |
| 彻底消除 TOCTOU 竞态 | 需要 Windows 句柄级打开后再删除，改动面大；当前已在 README 写明窗口，执行前复核对象类型 |
| 回收站全边界自动化（占用、网络盘、超长路径） | 依赖真实环境且不可稳定复现；保留现有真实批量用例，其余以 mock 覆盖并在文档标注 |
