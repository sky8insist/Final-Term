# 优化进度历史快照

归档日期：2026-10-27。以下完整保留进度表重整前的内容，测试数字和“下一阶段”均表示当时状态。

当前进度请读 [OPTIMIZATION_PROGRESS.md](../OPTIMIZATION_PROGRESS.md)，真实浏览器补验请读 [METRICS_BROWSER_20261027.md](../acceptance/METRICS_BROWSER_20261027.md)。

---

# 技术指南优化进度

2026-10-27 最新续作：学习记录界面/审计分页/预测覆盖率。新增全局 `/learning-metrics`，串联完成率/校准/采纳、推荐依据及分页行动历史；057 本地已安装，首次成绩发布固定覆盖分母，区分未知正确性/缺作答/缺快照。新增 **21 项后端 + 8 项 Node 回归**，完整 **886 passed, 3 warnings**，Node **33 passed**，Ruff F/quality gate/lint/build/diff 通过；最大 chunk **255.61 kB**，新页面 chunk **18.34 kB**。真实 SQL/Supabase/API 验证同时间分页/并发新记录/范围/发布口径/权限和精确清理。没有浏览器工具，真实浏览器/JWT/长期效果未验收。下一轮可进入安全隐私与数据保留专项；详见 `docs/acceptance/METRICS_WORKSPACE_20261027.md`。

2026-10-27 最新续作：离线质量版本对照与门禁。标签/两版输出分开、逐 case 输入和标签 SHA256 绑定，支持 nDCG/MRR/Recall、守卫 false-reject/false-accept、外部计划相关度/容量，输出配对差值/Bootstrap区间和显式门禁。新增 **37 项**后端回归，完整 **865 passed, 3 warnings**，Ruff F/quality gate/diff 通过。24 条合成样例实际调用当前纯函数；保留词法退步，nDCG 差值区间跨0，更严格 uplift 门禁按预期失败。结果是工具/回归验收，不是真实人工独立标注或模型效果。无迁移/前端/DB/付费调用；下一轮继续指标界面/审计分页/预测覆盖率。详见 `docs/QUALITY_EXPERIMENTS.md` 与 `docs/acceptance/PAIRED_QUALITY_20261027.md`。

2026-10-27 最新续作：完成率稳定 cohort 与前瞻 Mastery 校准。056 本地已安装，新增 Guided/Plan Task/新闪卡安排/Guided Quiz Remediation 的 7 天窗口指标，未成熟单列/零分母 null；首次作答冻结 Mastery，在成绩发布后按版本计算 Brier/分桶/ECE。新增 **10 项**后端回归，完整 **828 passed, 3 warnings**，Ruff F/quality gate/diff 通过。真实 PostgreSQL/Supabase/API 核验冻结/归属/发布门槛、2,001 条全量聚合、Brier .04/.64 和 ECE .2，临时数据精确清理。无前端改动、真实长期效果/模型/浏览器验收；下一轮继续独立质量实验，整体计划成功率等边界保留。详见 `docs/acceptance/LEARNING_OUTCOMES_20261027.md`。

2026-10-27 最新阶段：Observability / Quality Evaluation 产品审计首轮。055 本地已安装，推荐投递快照、可见曝光/点击、canonical 会话采纳/完成与步骤/Mastery/重排/停止/评分校准事件、本人审计和带分母的 SQL 指标已接通。新增 **13 项后端 + 6 项 Node 回归**，完整后端 **818 passed, 3 warnings**；前端两组 **25 passed**，Ruff F/quality gate/lint/build/diff 通过，最大 chunk **254.55 kB**。真实 PostgreSQL/Supabase/API 验证去重、归属、缺基线/空指标、+50 点、Brier .64、成绩发布门槛、RLS/私有权限与精确清理。下一轮继续本阶段剩余稳定完成率、Mastery 校准和独立质量实验；无真人效果、模型/浏览器/JWT 验收。详见 `docs/acceptance/PRODUCT_QUALITY_AUDIT_20261027.md`；缓存阶段记录保留于 `WORKSPACE_CACHE_20261027.md`。

2026-10-22 最新：先补齐 Dayend 界面/历史/入口收敛/自动调度，再完成 Worker 学习事件首轮。完整 **785 passed, 3 warnings**（本次新增 21 项），Ruff F/quality gate/前端 lint/build/diff 通过，最终最大 chunk **251.02 kB**。052/053 本地已安装，六类事件原子 outbox/租约/幂等回执/重算防抖/死信重试与权限回滚验收通过；**真实 Redis+独立 Celery Worker+Supabase** 验证两类任务各重复投递三次只生效一次，临时用户/队列/结果已清理。持续 Beat/分布式并发/浏览器仍待验收，原独立 Dayend 模型评审 N/A。下一阶段 Workspace Cache；详见 `LEARNING_EVENTS_WORKER_20261022.md` 与 `DAILY_REVIEW_AUTOMATION_20261022.md`。

2026-10-22 Dayend 待办补齐：学习复盘页/侧栏入口、已存历史分页/恢复、可选上海日终调度和原子报告发布已完成；052 本地已安装。新增 11 项回归，完整 **775 passed, 3 warnings**；Ruff F/quality gate/前端 lint/build（250.93 kB）通过。SQL 租约/去重/开关发布栅栏/重试/死信/跨日/RLS 回滚与实际只读 API 验收通过。持续 Worker/Beat、浏览器及原独立模型质量仍未验收；详见 `DAILY_REVIEW_AUTOMATION_20261022.md`。随后继续 Worker 学习事件闭环。

2026-10-22 最新阶段：Dayend 学习复盘首轮服务端实现。新增 **23 项**回归，完整后端 **764 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。本地 051 已安装；真实 SQL 验证有证据的 Mastery 百分点变化、共享容量/保护任务、来源快照/请求幂等、人工确认改期/审计事件/整批回滚/RLS/级联，临时行全回滚；实际 Supabase 只读预览 API 200/404/401 通过。原独立 Dayend 模型质量评审仍 N/A，原自由文本图未替换；前端/历史复盘/自动调度/真实模型/并发验收保留待办。详见 `docs/acceptance/DAILY_LEARNING_REVIEW_20261022.md`；下一阶段 Worker / Async Task。

2026-10-22 最新阶段：Memory / Learner Profile 首轮边界完成。新增 **38 项**回归，完整后端 **741 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。本地 050 已安装；SQL 回滚验证分类/范围/来源/快照/RLS，以及删除计划保留偏好、删除记忆保留 Mastery；实际 Supabase 只读 API 通过，身份为测试覆盖。未改前端/实际配置或真实用户记忆，未验收真实模型/浏览器/持续 Worker。详见 `docs/acceptance/MEMORY_BOUNDARIES_20261022.md`。下一阶段 Dayend / LangGraph 学习复盘状态与重排建议，保留独立评审 N/A。

2026-10-22 本阶段：Mind Map 稳定 Topic 绑定与学习状态首轮完成。新增 21 项回归，完整后端 **703 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build（最大 chunk 256.38 kB）及 diff 检查通过。本地已安装 049，SQL 归属/双版本 CAS/快照失效/学习投影/RLS/级联验收通过，临时行全部回滚；实际 Supabase 只读 API 联调通过，身份为测试覆盖。无真实浏览器/JWT/模型或真实用户绑定写入。详见 `docs/acceptance/MIND_MAP_TOPICS_20261022.md`；下一阶段为 Memory / Learner Profile，先修边与资料 graph diff 保留待办。

依据：PROJECT_TECHNICAL_INTERVIEW_GUIDE.md。更新：2026-10-22。

状态含义：“第一轮实现”表示代码与技术验证完成；不等于指南全部功能、质量及 E2E 验收通过。“待优化”保留现有功能，尚未执行该指南提出的增量优化。

| 优先级 / 模块 | 当前状态 | 本轮结果 / 剩余范围 |
|---|---|---|
| P0 Topic Domain | 第一轮实现 | Unit/Topic、稳定 ID/别名、归档、题目/新闪卡/新任务绑定；P3 已补标题来源提案与人工确认，正文语义提案、历史同义合并、其他产物绑定待补 |
| P0 Learner State / Mastery | 第一轮实现 | 五状态投影、明确 assessment 证据、信心语义、误解风险、绩效状态历史；覆盖自动采集、历史回填和校准评测待补 |
| P0 Exam Event / Syllabus | 第一轮实现 | 人工大纲快照/Topic 映射/范围权重、P3 已补资料考试候选及证据复核确认；通用大纲语义解析与自动章节映射待补 |
| P0 Response Confidence | 第一轮实现 | 答题采集、持久化、评分、Mastery、Study Signal；真实 UI 和校准评测待验收 |
| P1 Next Best Action / Dashboard | 第一轮实现 | Top 3 与原因、考试范围加权、到期/薄弱/待办、Guided 入口与 24 条离线推荐回归；真实推荐质量与学习效果待验收 |
| P1 Guided Study Session / Assistant | 第一轮实现 | 持久化步骤、时间编辑/确认、完成凭据核验、恢复、补习/重测与总结；真实浏览器/AI 质量和跨服务故障恢复待验收 |
| P1 Adaptive Quiz / Exam | 第一轮实现 | 模式分离、Formal 隐藏即时评分、三类 Stop Policy、复习记录/恢复及 Guided 补习/重测；独立诊断和真实模型评测待补 |
| P1 Study Plan v3 / Review | 第一轮实现 | 考试目标/范围、三种 Mode、逐日预算/任务保护/CAS 重排/Beat；P3 已补共享日容量与原子复核，持续事件 E2E 与推荐质量待验收 |
| P2 Card-level Spaced Repetition | 第一轮实现 | 独立卡片状态、四档评价、事务/幂等复习、due/逾期队列和历史、Guided 恢复、遗忘后重新评估；FSRS 校准、真实浏览器与长期效果待验收 |
| P2 Retrieval / LightRAG / Reranker | 第一轮实现 | 可配置 reranker/无 rerank 对照、候选 20、意图/动态 K/改写、多样性、三路统一筛选与 DB 来源核验、对照评测脚本；真实语义模型与质量/P95 对照待执行 |
| P2 Chunk / Parent-child | 第一轮实现 | 标题/句子/表格行、事务父子替换/child 检索/有界展开、8 条对照；解析续作已补 structure-v2 caption 邻接保留与跨页公式边界，真实双索引 Recall@5/质量/P95 待验收 |
| P2 Recommendation Evaluation | 第一轮实现 | 24 条标注快照、Top-1 hit/暂不推荐准确率、独立 reason faithfulness、范围/导航/关键理由/确定性门禁与反例；真实用户数据标注、采纳率和学习增益待验收 |
| P3 Notes / Artifacts | 第一轮实现 | 四种 Notes 模式、版本/CAS/来源、编辑/恢复/局部改写/转换/Markdown；已补上传可选自动 Notes（最多前 30 块），全资料分批/Guided Notes、其他产物通用版本和真实 UI/模型质量待补 |
| P3 Mind Map | 首轮关联实现 | 人工稳定 Topic 绑定/解绑、快照失效/双版本 CAS、学习状态/复习/误解/考试权重、Guided 与考试计划入口、节点转换精准继承；权威 prerequisite、新资料 graph diff、独立节点计划及真实 UI 验收待补 |
| P3 Unified Turn Into | 第一轮实现 | 四类来源/五类目标共 14 个组合、来源快照/引用、异步任务/请求幂等/原子发布/取消重试/双向外键、错题 Tutor 与共享组件；QuizResult→StudyPlan 等、全资料分批、旧同步接口移除、持续 Worker/模型/浏览器 E2E 待补 |
| P3 Calendar | 第一轮实现 | 月历/当天任务、全部科目考试/到期闪卡、版本化个人日预算/跨计划容量、漏做自动任务改期并锁定、大纲考试候选人工确认→计划；时段冲突/定时预约/通用解析/跨时区与真实 UI/Beat E2E 待补 |
| P3 Materials / Ingestion | 首轮增量接通 | 三类用途/失败恢复、章节与 Topic 接受/拒绝、四模式可选上传 Notes/稳定请求/事务入队确认/定时补扫；全资料分批、语义提取/边界编辑、阶段断点/材料 outbox/claim 与真实 E2E 待补 |
| P3 MinerU / Parse / Multimodal / Lecture | 首轮结构增量 | 标题层级/父标题、内嵌和唯一邻接 caption、同页公式上下文候选、未知置信度/计数、Word 回退样式/阅读顺序；复杂版面/语义关联/校准、通用大纲/自动转录分题与真实质量待补 |
| P3 Live Lecture（指南第 16 项） | 第一轮代码（录制后处理） | 录音/本地草稿/上传、分段转录与回听、人工 Topic CAS、选中片段转换；本机缺 FFmpeg/ffprobe，真实 ASR/浏览器/持续任务链路及实时字幕待验收或实现 |
| Evidence / RAG QA | 首轮规则实现 | evidence-v2 分项覆盖/来源数、可选 borderline 模型判断、逐句编号/引用覆盖/词法/数值/否定检查、失败不发布、外部章节隔离、18 条质量门禁；完整语义蕴含/来源主张、校准和真实拒答/模型质量待验收 |
| Memory / Hermes | 首轮边界实现 | 稳定记忆分类/状态拦截、强制自动提案确认、来源/范围去重、白名单偏好冻结/legacy 隔离、禁用/删除失效、30 天行为只读 API；语义评测、整体事务/CAS、完整来源历史与管理界面待补 |
| Dayend / LangGraph | 首轮界面与自动生成 | 确定性复盘/审计/原子改期、工作台新入口、历史分页/恢复、可选自动日终/原子发布；真实隔离 Worker 重复投递已验收，历史状态重建/更多重排/持续 Beat 与浏览器待补，独立模型评审仍 N/A |
| Worker / Async Task | 学习事件首轮实现 | 六类 v1 事件/事务 outbox、租约/幂等回执/版本失效、30 秒防抖/dirty 最长等待、5 次自动与 3 轮手动死信重试；真实隔离 Redis/Worker 重复消费验收通过，通用 ingestion 恢复/事件保留/持续 Beat/分布式并发待补 |
| Workspace Cache | 首轮版本实现 | 同步资源 revision/v2 键、读取前后核验/旧写入拒绝、主请求重取/账户栅栏、分钟边界、分资源缓存提示/可见轮询更新提示、隐私代次撤销；容量/P95、多端浏览器/离线恢复与全页刷新待补，权威状态/推荐继续绕过快照 |
| Observability / Quality Evaluation | 首轮界面与审计闭环 | 产品审计/7天 cohort/前瞻校准与覆盖率、离线对照/区间/门禁、学习记录页/本人推荐及行动分页；真实独立标签/模型采集/分组对照、整体计划成功率/独立测验补救、长期采集/保留与规模/浏览器待补 |
| Security / Privacy | 部分接入 | 本轮新表 RLS、复合外键、用户导出/科目删除级联；其余隐私与新模块验收待补 |
| Frontend Information Architecture | 局部扩展 | 课程结构/首页下一步/答题信心/学习记录全局入口；尚未全面重组导航，新增页面真实浏览器验收待补 |

2026-10-22 Evidence / RAG QA 最新证据：新增 **46 项**回归，完整后端 **682 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。8 条证据和 10 条回答标签回归均通过，报告 `GROUNDING_EVAL_20261022.json`；真实本地 PostgreSQL 验证拒答、空引用和审计 metadata/RLS，测试数据全回滚。事实句须带现有 `[n]`，伪造编号/协议引用与未批准 URL 拦截后不保存原回答；外部 fallback 由服务器分节并隔离课程上下文。可选语义 judge 默认关闭；groundingScore 是规则支持率，不能解释为语义蕴含或线上准确率。本轮无新迁移/前端改动，真实模型/检索/浏览器链路未验收。下一阶段补 P3 Mind Map 的 Topic 权威及状态/工具联动。详见 `docs/acceptance/EVIDENCE_GROUNDING_20261022.md`。

2026-10-22 解析结构最新证据：新增 **38 项**回归，完整后端 **636 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。真实本地 PostgreSQL 回滚验收覆盖 documentStructure 标注/structure-v2 存储、caption 父块、null 置信度、canonical 来源与用户隔离，无新增迁移/历史重建；真实 DOCX 字节回归验证样式与交错顺序、旧 source_hash 兼容。8 条词法 Chunk 对照未回退；没有进行真实 MinerU/模型、复杂课件 30 页抽样、置信度校准或浏览器验收。下一阶段继续 Evidence / RAG QA。详见 `docs/acceptance/DOCUMENT_STRUCTURE_20261022.md`。

2026-10-22 上传后自动 Notes 最新证据：新增 **31 项**回归，完整后端 **598 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build（最大 chunk 255.79 kB）、UI 静态检测和 diff 检查通过。本地 048 已安装，真实 SQL 验证默认关闭、申请/模式/归属、领取/限次/重置、转换入队与申请确认同事务、稳定请求去重、Notes/版本原子发布、删除不再生成、无覆盖写入及私有 RPC/RLS，fixture 全回滚。实际 Supabase 汇总只读接口及隔离/匿名检查通过，认证为测试覆盖。范围明确为前 30 个内容块；固定草稿发布验证不替代真实模型/浏览器/持续 Worker 与 Beat 验收。下一阶段按指南继续 MinerU / Parse 的层级、caption/context 和置信度，保留 Materials 全资料分批及可靠摄取待办。详见 `docs/acceptance/UPLOAD_NOTES_20261022.md`。

2026-10-22 Materials 章节与 Topic 提案最新证据：新增 **25 项**回归，完整后端 **567 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build（最大 chunk 255.64 kB）和 UI 静态检查通过。本地 047 已安装，真实数据库验收涵盖 canonical 来源/完整章节分区、拒绝保留、确认重放/CAS、别名和 Unit 复用、正文变化/恢复、归档拒绝、无覆盖写入、只读 RLS/私有 RPC 及删除级联，临时数据全回滚。真实 Supabase 只读 outline API、匿名/跨科目校验通过；认证为测试覆盖。当前是已有标题驱动的逻辑章节视图，不改原文和检索索引；真实浏览器/持续 Worker、正文语义提取仍待验收或实现。下一阶段为上传后自动 Notes；详见 `docs/acceptance/MATERIAL_OUTLINE_20261022.md`。

2026-10-19 Materials 用途与失败恢复最新证据：新增 **21 项**回归，完整后端 **542 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build（最大 chunk 255.23 kB）通过。本地 046 已安装，真实数据库验证用途约束、最新任务汇总/隔离、源文件有效期、手动重试新周期/重复冲突、投递失败、运行任务保护、唯一哈希冲突回滚与 RLS/私有 RPC；临时记录全部回滚。实际 Supabase 只读资料/汇总 API、匿名和跨用户检查通过，使用测试身份覆盖。此次只完成 Materials 第一阶段，下一步为章节拆分和 Topic 提案确认，再接自动 Notes；未宣称断点恢复、material outbox/claim 或真实浏览器/持续 Worker 链路完成。详见 `docs/acceptance/MATERIAL_RECOVERY_20261019.md`。

首轮基础证据：后端 243 passed；前端 lint/build 通过；本地 PostgreSQL 029–032 与新增只读 API 联调通过。

2026-10-07 P1 续作最新证据：后端 **287 passed, 3 warnings**；Ruff F 检查、前端 lint/build 通过，最大 chunk 250.07 kB。本地 033–037 已安装，并补齐缺失的 026。回滚式数据库验收覆盖会话/计划版本与事务、任务保护、三类暂停、正式评分释放及 RLS；真实 Supabase 只读 API 联调通过，认证为测试依赖覆盖。每个模块完成后均即时更新 HANDOFF.md，并有 Guided / Adaptive / Study Plan v3 独立验收文档。真实浏览器、真实生成绑定率、持续 Beat/Worker 事件链路及 AI/学习质量指标尚未验收。

后续按依赖推进：补齐 P1 独立诊断与 E2E → P2 卡片级排期 → 检索与 Chunk → 推荐评测 → 产品转换/日历与事件闭环。每完成一个模块立即追加 HANDOFF.md，并补充独立验收范围、证据与限制。

2026-10-08 卡片模块证据：完整后端 **303 passed, 3 warnings**；Ruff F、前端 lint/build 通过（最大 chunk 250.65 kB）。本地 038 已安装，真实数据库回滚验收覆盖独立排期、幂等、版本冲突、内容重置/历史保留、归档排除及 RLS；真实 Supabase 队列/汇总 API 200、跨用户 404。验收详见 `docs/acceptance/FLASHCARD_SCHEDULER_20261008.md`。下一优先级为检索 / reranker，再接 parent-child chunk 与推荐评测。

2026-10-08 检索模块最新证据：完整后端 **318 passed, 3 warnings**；Ruff F 和 diff 检查通过；本地 039 安装及回滚隔离验收通过；真实 Supabase 关键词 baseline/adaptive API 验证通过（禁用模型/向量/图谱路径）。HTTP reranker 协议验证使用模拟响应，真实语义模型质量/延迟对照尚未执行；下一模块为 Chunk / Parent-child。详见 `docs/acceptance/RETRIEVAL_V2_20261008.md`。

2026-10-08 Chunk 阶段最新证据：完整后端 **327 passed, 3 warnings**；Ruff F、diff 检查通过。本地 040/041 已安装，真实父子事务/回滚/成员归属/RLS、基线切换和 child 关键词验证通过；实际 Supabase 父上下文 RPC / 关键词 API 联调通过。8 条共享词法离线回归的完整证据 Hit@5 0.875→1.0、MRR 0.71875→0.84375，不替代真实向量/RRF Recall@5 对照。默认仅新摄取使用 structure，未全量重建旧索引。下一阶段为 Recommendation Evaluation；详见 `docs/acceptance/PARENT_CHILD_CHUNKS_20261008.md`。

2026-10-08 Recommendation Evaluation 最新证据：完整后端 **370 passed, 3 warnings**；推荐专项 50 passed，Ruff F、统一离线 quality gate、diff 检查通过。24 条合成标注快照：Top-1 Hit 22/22，暂不推荐 2/2，支持理由 43/43，范围一致性/确定性全部通过；不代表真实用户推荐质量或 DB 授权评测。真实本地 Supabase 只读 API 200（1 条推荐 / 1 条理由审计）、匿名 401、非法参数 422、跨用户科目 404；认证为测试覆盖。规则 next-action-v2 补齐映射科目核验、回忆风险理由与待办稳定排序，无新迁移。下一阶段 P3 Notes / Artifacts。详见 `docs/acceptance/RECOMMENDATION_EVALUATION_20261008.md`。

2026-10-09 Notes / Artifacts 最新证据：完整后端 **414 passed, 3 warnings**，新增 44 项 Notes 回归；Ruff F、quality gate、前端 lint/build（最大 chunk 251.83 kB）与 diff 检查通过。本地 042 已安装，真实事务/历史/CAS 回滚、恢复、Topic/来源归属与只读 RLS 验证通过，临时记录全回滚；实际 Supabase 私有来源 RPC/Notes 列表 API 联调通过。真实模型生成/事实蕴含率、浏览器/JWT E2E、异步与跨服务补偿仍未验收。下一阶段按 P3 顺序推进 Unified Turn Into，保留 Mind Map Topic 权威待办。详见 `docs/acceptance/NOTES_ARTIFACTS_20261009.md`。

2026-10-09 Unified Turn Into 最新证据：完整后端 **460 passed, 3 warnings**，新增 46 项回归；Ruff F、quality gate、前端 lint/build（最大 chunk 253.00 kB）、共享组件机械检测与 diff 检查通过。本地 043 已安装，真实数据库验收验证原子入队/发布、幂等、claim 隔离、取消/重试上限/过期重领、来源变更/删除、Notes 历史/Flashcard 排期/Quiz 关联与 RLS；临时记录全回滚。实际 Supabase 只读列表/capabilities 与匿名/跨用户验证通过，认证为测试覆盖。14 个转换组合为第一轮实现；旧 Notes 同步接口保留兼容并标记 deprecated，QuizResult/StudyPlan 转换与真实 Worker/Beat/JWT/模型/UI E2E 尚未完成。下一阶段 Calendar；详见 `docs/acceptance/UNIFIED_TURN_INTO_20261009.md`。

2026-10-19 Calendar 最新证据：完整后端 **492 passed, 3 warnings**，新增 32 项 Calendar 回归；Ruff F、quality gate、前端 lint/build（最大 chunk 253.83 kB）和 diff 检查通过。本地 044 已安装，真实数据库回滚验收覆盖预算 CAS、跨科目容量/失败回滚、日期与筛选汇总、闪卡归档/历史卡、同日多考、受保护任务/改期锁定、考试候选证据/确认幂等/归属及 RLS；实际 Supabase 只读 API/匿名/跨用户校验通过，认证为测试覆盖。资料大纲采用有限规则和人工 Topic 确认，不等于通用语义解析；时段冲突、定时学习预约、持续 Worker/Beat、真实 JWT/浏览器仍待验收。静态检测两条互斥配色分支提示已代码核对，未声明浏览器通过。下一阶段按指南为 Live Lecture；详见 `docs/acceptance/CALENDAR_20261019.md`。

2026-10-19 Live Lecture 最新证据：完整后端 **521 passed, 3 warnings**，新增 29 项回归；Ruff F、quality gate、前端 lint/build（最大 chunk 254.95 kB）和 diff 检查通过。045 已安装，本地真实数据库验证音频挂接/归属、Topic 对齐 CAS/失效/解除、不提升 Mastery、121 段分页定位和 RLS；实际 Supabase 只读接口、匿名与跨用户检查通过，全部临时记录回滚。交付范围为录制结束后批处理：时间窗口/未知置信度有明确标记，片段复用现有四类材料转换。当前缺 FFmpeg/ffprobe，不能声明真实解码/ASR或浏览器麦克风/草稿流程通过；实时字幕和自动分题/Topic 映射保留待办。下一建议 Materials / Ingestion 与音频运行链路补齐；详见 `docs/acceptance/LIVE_LECTURE_20261019.md`。
