# API 验收矩阵

契约来源：`openapi-after.json`（62 paths / 75 operations）。所有业务接口仅挂载在 `/api/v1`；`/health` 是唯一无版本公开路径。

“页面/API 方法”中的 `—` 表示当前没有一方前端入口，但接口仍属于后端管理、导出或扩展契约。测试列给出主要覆盖文件，不表示唯一覆盖。

| 页面操作 | 前端 API 方法 | HTTP 接口 | 后端 Service | 主要数据表/外部系统 | 自动化测试 |
| --- | --- | --- | --- | --- | --- |
| 健康检查 | — | `GET /health` | `main.health_check` | — | `test_api_baseline.py` |
| 注册账户 | Auth 页面直接 fetch | `POST /api/v1/auth/account/register` | Supabase admin client | `auth.users`、验证邮件 | `test_account_auth.py` |
| 当前用户/恢复会话 | `currentUser` | `GET /api/v1/auth/me` | JWT dependency | Supabase Auth | `test_account_auth.py`, `test_api_baseline.py` |
| 学科列表/创建 | `subjects`, `createSubject` | `GET/POST /api/v1/subjects` | `subject_service` | `subjects` | `test_subjects.py` |
| 学科详情/修改/删除 | `setSubjectExternalKnowledge`（修改）；其余暂无 UI | `GET/PATCH/DELETE /api/v1/subjects/{subject_id}` | `subject_service` | `subjects` | `test_subjects.py`, `test_subject_id_validation.py` |
| Dashboard 汇总 | `dashboard` | 组合 `GET /subjects` + `GET /study-plans/today` | `subject_service`, `study_plan_service` | `subjects`, `review_tasks` | `test_subjects.py`, `test_study_plans.py` |
| 资料列表 | `materials` | `GET /api/v1/materials` | `material_service` | `materials` | `test_upload.py`, `test_subject_id_validation.py` |
| 资料异步上传 | `addMaterial` | `POST /api/v1/materials/uploads` | `ingestion_service` → Celery | Storage、`materials`, `material_assets`, `processing_tasks` | `test_upload.py`, `test_tasks.py`, `test_mineru_integration.py` |
| 资料同步处理（迁移候选） | — | `POST /api/v1/materials/upload` | `material_service` | 同上及 chunks/index | `test_upload.py` |
| 查看内容块/来源 | — | `GET /api/v1/materials/{id}/blocks`, `/source` | `content_service`, `material_service` | `content_blocks`, `material_assets`, Storage signed URL | `test_upload.py`, `test_mineru_integration.py` |
| 查看任务/活动任务 | `task`, `tasks` | `GET /api/v1/tasks`, `GET /api/v1/tasks/{id}` | `task_service` | `processing_tasks` | `test_tasks.py` |
| 重试/取消任务 | — | `POST /api/v1/tasks/{id}/retry`, `DELETE /api/v1/tasks/{id}` | `task_service` + Celery dispatch | `processing_tasks`, Redis/Celery | `test_tasks.py`, `test_worker_recovery.py` |
| 检索 | —（由问答/生成内部使用） | `POST /api/v1/retrieval/search` | `retrieval_service` | `material_chunks`, pgvector, LightRAG | `test_retrieval_lightrag.py`, `test_embedding_vector.py` |
| 直接引用问答 | — | `POST /api/v1/chat/ask` | `rag_service` / chat service | `chat_messages`, chunks, LLM | `test_chat.py`, `test_rag.py` |
| 对话历史 | `chatHistory` | `GET /api/v1/chat/history/{subject_id}` | conversation service | `chat_messages` | `test_chat.py`, `test_subject_id_validation.py` |
| AI 学习室发消息 | `chat` | `POST /api/v1/assistant/messages` | `assistant_service`, router agent | chat、interactions、memory、RAG/LLM | `test_assistant.py`, `test_dialogue_routing.py` |
| 思维导图查询 | `mindMap` | `GET /api/v1/artifacts?artifact_type=mind_map` | `artifact_service` | `artifacts` | `test_artifacts.py`, `test_mindmap.py` |
| 生成思维导图 | `generateMindMap` | `POST /api/v1/artifacts/mind-maps` | `mindmap.service` | `artifacts`, chunks, LLM | `test_mindmap.py` |
| 生成提纲/闪卡/通用产物 | `generateFlashcards`；提纲暂无页面按钮 | `POST /api/v1/artifacts/outlines`, `/flashcards`, `/artifacts` | `artifact_service` | `artifacts` | `test_artifacts.py` |
| 产物查看/修改/导出 | — | `GET/PATCH /api/v1/artifacts/{id}`, `GET .../export` | `artifact_service` | `artifacts` | `test_artifacts.py` |
| 闪卡复习反馈 | — | `POST /api/v1/artifacts/{id}/flashcards/reviews` | `artifact_service` | `artifact_reviews`/artifact metadata | `test_artifacts.py` |
| 考试列表 | `exams` | `GET /api/v1/exams` | `exam_service` | `exams`, `exam_blueprints`, questions | `test_exams.py` |
| 异步生成考试 | `queueExamGeneration` | `POST /api/v1/exams/generations` | `exam_generation_service` → shared generation task → Celery | `processing_tasks`, exam tables | `test_exam_generation.py` |
| 查看/导出考试 | `exam`；导出暂无 UI | `GET /api/v1/exams/{id}`, `GET .../export` | `exam_service` | exam tables | `test_exams.py` |
| 开始/恢复作答 | `startExamAttempt`, `examAttempt` | `POST /api/v1/exam-attempts`, `GET /{attempt_id}` | `exam_service` | `exam_attempts`, exam tables | `test_exams.py` |
| 保存/确认答案 | `saveExamResponse`, `confirmExamResponse` | `PATCH /exam-attempts/{id}/responses`, `POST /{id}/questions/{qid}/confirm` | `exam_service`, answer evaluation | `exam_responses`, `grading_results` | `test_exams.py`, `test_exam_generation.py` |
| 提交/评分 | `submitExamAttempt` | `POST /api/v1/exam-attempts/{id}/submit` | `exam_service`, mastery/signal services | grading、mastery、learning interactions；历史 `wrong_answers` | `test_exams.py`, `test_evidence_assessment.py` |
| 评估历史 | — | `GET /api/v1/exam-attempts/history` | `exam_service` | attempts/grading | `test_exams.py` |
| 计划预览 | `previewPlan` | `POST /api/v1/study-plans/preview` | `study_plan_service` | mastery/signals（只读） | `test_study_plans.py` |
| 异步生成计划 | `generatePlan` | `POST /api/v1/study-plans/generations` | `study_plan_generation_service` → shared generation task → Celery | `processing_tasks`, `study_plans`, `review_tasks` | `test_study_plans.py`, `test_worker_recovery.py` |
| 查询计划生成 | `planGeneration` | `GET /api/v1/study-plans/generations/{id}` | `task_service` | `processing_tasks` | `test_study_plans.py`, `test_tasks.py` |
| 计划概览/今日任务 | `plan`, `dashboard` | `GET /api/v1/study-plans/overview`, `/today` | `study_plan_service` | `study_plans`, `review_tasks` | `test_study_plans.py` |
| 更新计划任务 | `updateTask` | `PATCH /api/v1/study-plans/tasks/{id}` | `study_plan_service` | `review_tasks` | `test_study_plans.py` |
| 启动冲刺阶段 | — | `POST /api/v1/study-plans/{id}/sprint` | `study_plan_service` | `study_plans`, `review_tasks` | `test_study_plans.py` |
| 掌握度/趋势/进度 | —（Dashboard/计划间接消费） | `GET /api/v1/review/today`, `GET .../{subject_id}/mastery|trends|progress`, `PATCH .../progress` | mastery/review services | mastery history、review progress | `test_study_plans.py`, `test_mastery` 相关全测 |
| 保存工作区缓存 | `saveWorkspaceState` | `PUT /api/v1/workspace/cache/{resource}` | `workspace_cache_service` | workspace cache records | `test_workspace_cache.py` |
| 读取/检查缓存 | client cache 层 | `GET /api/v1/workspace/cache/{resource}`, `/cache-health` | `workspace_cache_service` | workspace cache records | `test_workspace_cache.py` |
| 记忆 CRUD/配额 | — | `/api/v1/memories*` | `hermes_memory_service` | memories/write requests | `test_hermes_memory.py` |
| 记忆审批/冻结快照 | —（assistant 内部） | `/api/v1/memory-writes/*`, `POST /memory-snapshots` | `hermes_memory_service` | memory requests/snapshots | `test_hermes_memory.py` |
| 学习画像/会话搜索/技能 | — | `/api/v1/learner-profile`, `/sessions/search`, `/skills*` | `hermes_memory_service` | learner profiles、session history、skills | `test_hermes_memory.py` |
| 隐私导出/数据删除/账户删除 | — | `GET /api/v1/privacy/export`, `DELETE /privacy/data`, `/privacy/account` | `privacy_service` | 所有用户表、Supabase Auth/Storage | `test_operations.py`/隐私相关全测 |
| 运维指标 | — | `GET /api/v1/operations/metrics` | `observability_service` | `operation_metrics` | `test_operations.py` |

## 已删除契约的负向矩阵

| 旧契约 | 替代契约 | 保护方式 |
| --- | --- | --- |
| 无前缀业务路由 | `/api/v1/*` | OpenAPI 断言 `/subjects` 不存在 |
| `/api/workbench/*` | 真实 `/api/v1/*` + Supabase 登录 | OpenAPI 断言无 Workbench path |
| `/outline/generate` | `/api/v1/artifacts/outlines` | OpenAPI 负向断言 |
| `/quiz/generate` | `/api/v1/exams/generations` | OpenAPI 负向断言 |
| `/exams/attempts/*` | `/api/v1/exam-attempts/*` | OpenAPI 负向断言 |
| `POST /api/v1/exams` | `POST /api/v1/exams/generations` | OpenAPI method 断言 |
| `POST /api/v1/study-plans` | `POST /api/v1/study-plans/generations` | OpenAPI path 断言 |
| 错题本页面/API | 练习表现、掌握度与学习信号 | 全仓公开入口扫描；历史表保留 |

## 契约差异结论

- OpenAPI before：147 paths / 177 operations。
- OpenAPI after：62 paths / 75 operations。
- 删除 85 paths，新增 0 paths。
- 前端 `apiV1()` 统一追加 `/api/v1`；README 和 E2E 脚本已同步。
- 前端类型检查是当前客户端契约门禁；尚未引入 OpenAPI 自动生成 TypeScript 类型，属于后续增强项。
