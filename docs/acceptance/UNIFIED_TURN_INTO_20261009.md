# Unified Turn Into 第一轮验收 — 2026-10-09

依据技术指南第二十七节及 P3 第 14 项；上一阶段为 Notes，下一阶段为 Calendar。本阶段完成共享来源/参数、持久化任务与跨工具上下文，不代表指南所有组合及学习质量已经验收。

| 来源 | 本轮支持目标 | 必需的上下文 |
|---|---|---|
| Material | Notes / Flashcards / MindMap / Quiz | 本人同科目 ready 资料，最多前 30 个真实内容块；超过时提示范围限制 |
| Notes | Flashcards / MindMap / Quiz / Tutor | 已保存笔记 ID、版本、章节正文/引用、Topic 关联 |
| MindMap node | Flashcards / Quiz / Tutor | 已保存导图 ID/版本、节点 ID、该节点的课程引用 |
| Wrong answer | Tutor / Notes / Flashcards | 原题版本、本人实际错误作答及评分、正确答案/解析、错误类型/知识点和证据 |

`ConversionRequest` 只接收来源标识、目标、count、Notes mode 与请求 UUID，禁止客户端上传伪造答案/正文/claim。count=1–20；本轮 Quiz 固定 adaptive practice、单选、每题 5 分、30 分钟、course_only。来源原文冻结在服务端，所有新产物继续继承原始课程证据；用户笔记和题目上下文只作学习重点提示，不能替代原始证据。

转换不会修改来源对象或更新 Mastery。Topic 在来源唯一绑定时继承；多 Topic 的新卡片/题目由既有 SQL Topic resolver 解析，再原子关联。导图节点目前仍继承导图整体 Topic 关联，不声称节点级权威已实现。

## 数据与任务约束

- 043 新增 learning_conversions；来源、结果和 processing_tasks 通过 user/subject 复合外键关联。认证用户可读本人转换记录，不能直写或调用私有状态 RPC。API 隐去 fingerprint、claim_token 和原始 snapshot；Tutor 上下文仅提供本人同科目且成功的 Tutor 转换。
- `enqueue_conversion` 按 user/request UUID 使用事务 advisory lock。相同参数重复提交返回原任务，不重复入队；同 UUID 换参数返回 409。来源版本改变后重复原请求仍返回原任务；新的请求需使用当前版本。
- `claim_conversion` 行锁领取任务，分配每次执行独立 token，最多 3 次执行；running 超过 20 分钟可重领。取消/重试/失败与发布均锁转换及任务，旧 worker 不能发布或覆盖新的状态。失败后的手动重试继续使用同一任务。
- Notes / Artifacts / Exam 生成器支持 draft_only，先完成结构/引用验证，只返回内存草稿。`finish_conversion` 再读取 canonical 课程来源核对冻结快照；变化、删除、跨科目或未 ready 时拒绝发布。输出与任务完成在同一数据库事务：Notes 调用 save_note 建立历史/来源关联；闪卡触发卡片级状态初始化；Quiz 创建蓝图、试卷、分节、题目、版本与题目关联。任一校验/写入失败全回滚。
- Tutor 转换不提前调用模型，只建立成功任务与上下文链接。Assistant 接收 conversionId 后后端加载原题/作答/评分和证据，使用既有角色要求与 RAG，强制课程来源；不能与 Guided/question/attempt/interaction 上下文混用。正式考试只有 graded attempt 的错题能进入此路径。
- Worker `process_conversion`、Beat 每 60 秒 `sweep_conversions` 负责投递 queued 和过期 running。Broker 不可用时保留入队记录；必须运行 Beat 才能恢复投递。没有执行中的心跳延租；超过 20 分钟或故障重领可能多次调用模型，但 token 保证同任务最多一次结果发布，不保证模型计费恰好一次。
- 来源/结果删除按外键清理转换记录；删除触发器取消 queued/running 的处理任务，避免 outbox 反复投递已经失去来源的任务。课程/账户删除保持既有级联语义；隐私导出包含转换记录。

## 入口与交互

侧栏 `/convert` 选择资料、Notes、错题，导图节点在详情面板选择；材料文件链接、Notes 编辑器和导图详情复用共享组件。能力矩阵由后端返回，UI 不另建独立转换列表。

待确认请求以账户/课程/来源版本/节点隔离存于 sessionStorage；网络失败时继续原请求，允许明确改为新建转换。服务端历史保留任务状态并支持刷新、取消及限次重试。历史同时可按来源 ID 或结果 ID 查阅，有原来源与生成结果链接；结果分别以 noteId、artifactId、examId 定位，闪卡队列按卡组过滤。Notes 有未保存修改时禁用转换，保留编辑草稿。

原来源链接打开当前对象，任务快照记录转换时版本，并不将原对象恢复成历史版本。资料只取前 30 个内容块；无引用节点不能转换。本轮尚未做长文件分批覆盖。

## 已执行验证

- 新增转换回归 **46 项**：14 个能力组合、来源形状/数量/伪造字段、参数指纹、请求重放、范围/版本/节点/采样、正式考试答案保护与固定题目版本、重复 worker、claim 发布与取消、任务 RPC 分流、Tutor 证据复核与上下文传递、API 认证/202/UUID/归属、五类目标真实生成器的 draft_only 无输出写入。生成模型使用测试响应，不是线上质量评测。
- 完整后端：**460 passed, 3 warnings**（既有 Starlette/Supabase 弃用提示）。Ruff F、统一离线 quality gate 通过。
- 前端 TypeScript lint、生产 build 通过，最大 chunk **253.00 kB**。机械检测范围为共享 TurnInto、新转换页面、Notes、AIStudyRoom、导图详情，最终返回空列表。没有可调用浏览器工具，真实布局/交互 E2E 为 N/A。
- `verify_conversions.py --api` 使用真实本地 PostgreSQL 事务，验证请求幂等/参数冲突、来源版本、重复 claim/发布、取消阻止输出、失败重试与 token 更换、过期重领、三次上限、闪卡状态初始化、Notes 历史、原子 Quiz 及失败回滚、来源变更、来源删除取消、跨用户来源/结果 FK、只读 RLS/私有 RPC。验证行全部回滚。
- 实际本地 Supabase 转换列表及能力 API 返回 200，跨用户科目 404、匿名 401。只读 API 使用 TestClient 身份依赖覆盖，没有真实 JWT；没有生成实际用户产物、没有调用模型、没有启动/重启后台服务。
- `git diff --check` 通过。

## 部署与复跑

其他环境先具备历史迁移（含 029/038/040/042），再安装 `backend/migrations/043_unified_conversions.sql`。本地已经安装 043。后端/Worker 需重启加载新路由/任务，并启动 Beat；持续 broker/worker 事件链路尚待实际验收。

在 backend 目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
.\.venv\Scripts\python.exe scripts/verify_conversions.py --api
```

`--apply` 严格限定 localhost，只安装缺失 043，或刷新该迁移的函数及补齐转换索引；不替代正式数据库版本升级流程。实际 .env 和用户技术指南未修改。

## 保留待办

QuizResult→Tutor/Flashcards/StudyPlan、其他来源/目标、长文件分批/覆盖预算、导图节点 Topic 权威和学习状态联动、其他产物通用版本/并发保护、取消模型执行/心跳延租、持续 Worker/Beat 故障注入、真实模型事实蕴含/转换质量与浏览器/JWT 全链路。

旧 `/notes/{id}/convert` 同步接口标记 deprecated 并保留兼容，仍可能通过旧客户端调用，不具备统一接口的任务幂等/原子发布保证；新 UI 全部使用 `/conversions`。前期生成器入口也继续保留，不将新转换语义误报为所有 AI 接口的通用保证。
