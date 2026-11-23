# P3 Notes / Artifacts 第一轮验收

日期：2026-10-09。依据技术指南“Artifacts / Notes”章节与 P3 第 13 项。本轮新增独立 Notes，未声明整个 Artifacts / Turn Into / E2E Journey 完成。

## 交付范围

1. 新增 artifact_type=notes、独立 Notes API、侧栏“学习笔记”及 `/notes` 页面。四种详细程度：summary / standard / comprehensive / exam_focus；可选择 ready 资料、文字范围和一个稳定 Topic。
2. 笔记为标题与章节集合，每节包含唯一 ID、标题、正文和非空 canonical citationIds。来源包含文件名、content block ID、页码/时间/坐标及原文快照。前端按章节展开来源、编辑标题/正文、调整引用、添加/删除章节；人工保存设置 is_user_edited。
3. 局部 AI 改写对齐已保存版本和原文选区。API 偏移为 Unicode 字符计数，前端转换浏览器 UTF-16 选区；包含 emoji 的案例已测试。只允许引用原章节的资料，返回预览，不直接写库；应用到草稿后由用户保存。模型调用完成后再检查版本，变化返回 409。
4. 版本历史列表只取摘要，点击版本单独读取完整快照；列表最多最近 100 个，按版本号可访问更早历史。恢复使用当前 expected version 和历史内容生成新版本，旧记录不变；来源已删除/未就绪或 Topic 已归档时拒绝不合法写入。
5. Notes → Flashcards / Quiz / MindMap 复用现有生成器，提供保存版本的内容与 canonical 原始证据。人工改写内容作重点提示，原始资料为依据；测验 course_only，不检索外部来源。结果记录 sourceArtifactId/sourceArtifactVersion（产物 generation_params 或测验 blueprint retrieval）。来源版本作为历史记录，即使转换期间原笔记更新，也能知道使用了哪个版本。
6. Markdown 导出包含正文、章节来源和页码/时间；JSON 保留现有内容导出约定。Notes 对暂不支持的图片/PDF/Mermaid 格式返回 400，避免原实现输出空白图像。

## 数据与权限

迁移：`backend/migrations/042_notes_versions.sql`，依赖 029 的归属复合键和 040 的资料/块复合键。

- artifact_versions：Notes 插入/更新后保存完整快照，主键 artifact_id/version；普通用户只读历史。
- note_sources：资料块/资料/笔记的 owner+subject 复合外键，防止跨用户/科目伪造来源；普通用户只读。
- save_note 私有 RPC：验证课程归属、Notes 类型、模式/结构、每节引用与 active Topic；重新从本人同课程 ready 资料读取 canonical 来源。更新行锁与版本检查、笔记/关联/历史在单事务提交，任何异常全回滚。
- 删除章节或移除引用后，保存只保留仍被章节使用的来源关联；已删除的无关资料不会永远阻止恢复正常编辑。
- Notes 和其 artifact_topics 不允许 authenticated 直接写；原非 Notes 产物写入政策继续保留。通用 `/artifacts` 更新 Notes 会转入 Notes CAS，缺少 version 返回 422，不能绕过专用接口。
- 版本/来源纳入隐私导出，笔记/课程/用户删除依赖现有级联；当前未新增单独删除笔记 UI。

## 前端恢复与限制

- 草稿存入当前浏览器标签页的 sessionStorage，按用户 ID / 笔记 ID 隔离，保存后清除。重新打开同版本恢复草稿；服务器版本改变时显示旧草稿供复制合并，避免自动覆盖新版本。
- 草稿未保存时切换笔记显示选择提示，刷新/关闭标签页触发浏览器提醒。转换/导出/新生成要求先处理草稿；保存或长操作期间禁用冲突操作。
- 保存冲突保留草稿，可重新读取服务器版本。浏览器禁止 sessionStorage 时显示提示；会话草稿不是跨设备同步，关闭标签页可能清除草稿。
- UI 沿用当前工作台与桌面设备限制，未改变全项目视觉体系或导航结构。

## 验证证据

- 新增 **44 项**后端测试，覆盖四种模式、canonical 证据、无效引用修复/拒绝、无写入的失败生成、结构/空白/重复章节、不可用来源、CAS 错误映射、Unicode 改写预览/选区/期间版本变化、三类转换的原始来源与版本、历史恢复、导出、认证与版本必填。
- 完整后端 **414 passed, 3 warnings**；警告来自既有 FastAPI/HTTPX、Supabase 参数弃用。Ruff F、现有统一离线 quality gate 通过；quality gate 的合成指标不代表真实笔记质量。
- 前端 `npm run lint` 与 `npm run build` 通过，最大 chunk **251.83 kB**；Notes 机械检测最终 `[]`。当前没有可调用浏览器工具，未进行渲染截图或真实交互验收。
- 本地 042 已安装。真实 PostgreSQL 回滚验收通过：canonical 原文/第 7 页、Topic/来源原子关联、版本 1→2→3、stale CAS 拒绝、错误引用/Topic/空引用回滚、历史保留、跨用户拒绝、owner 可读历史、普通用户不能改 Notes/关联/历史或调用私有写 RPC。所有临时用户/资料/笔记回滚。
- 真实 Supabase 私有来源 RPC 读取现有 owned ready 块通过；实际 Notes 列表 API 200、匿名 401、跨用户科目 404。使用 TestClient 认证依赖覆盖，列表联调未写入真实用户笔记；数据库事务验证和真实 HTTP 只读联调是不同证据。
- 未调用付费模型，生成/改写/转换模型输出在测试中模拟；未修改实际 .env、用户技术指南，未重启后端/Worker。

复跑（仓库根目录 PowerShell）：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/verify_notes.py --api
# 仅本地缺少 042 时，或需要刷新该迁移内的 save_note 函数：
.\.venv\Scripts\python.exe scripts/verify_notes.py --apply --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
cd ../frontend
npm run lint
npm run build
```

沙箱内本地数据库连接曾超时、esbuild 子进程曾返回 EPERM，最终通过获准的沙箱外执行完成验收。验收脚本只允许 localhost；`--apply` 不用于远端/生产部署。其他环境先安装依赖与 042，再重启后端服务。

## 仍待推进

章节有真实引用只证明结构可追溯，不证明每个观点与证据一致；AI 语义蕴含、教学质量、真实资料不同 Notes 模式的覆盖/长度和延迟仍需独立评测。用户编辑也不能被当作已验证知识或掌握证据，本轮不自动提升 Mastery。

上传后自动 Notes、Guided Study 对持久化 Notes 的执行绑定、多 Topic 的逐节标注、其他产物通用不可变版本/并发编辑、长期历史分页/存储策略、真实 JWT/浏览器 E2E 均待补。

三类转换目前使用同步既有链路与版本元数据；未完成统一对象模型、通用双向关系外键、后台任务/幂等/取消、转换故障补偿，测验仍沿用原持久化流程。下一阶段按指南 P3 第 14 项推进 Unified Turn Into，同时保留 Mind Map 的 Topic 权威绑定待办。
