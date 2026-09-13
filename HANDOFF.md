# 项目交接文档

## 2026-09-13 — Dayend V3 本地持久化验收与质量评估豁免（最新）

> 当前全项目验收索引：`docs/acceptance/CURRENT_PROJECT_ACCEPTANCE_20260913.md`。
> 结论为“有条件通过（本地技术交付）”，不是生产级最终验收。

### 本轮已完成

- Closure 合同新增约束：模型分类为 `uncertain` 的事项必须引用有效
  `needs_confirmation_ids`；新增 `test_closure_contract.py`，完整后端回归为
  `205 passed, 3 warnings`。
- `/api/v3/runs/stream` 在 `confirmation_required` 后不再错误发出
  `run_completed`；所有者隔离已真实验证：owner `GET` 为 200，另一账户
  `GET`/`resume` 均为 404。
- A/B/C 盲评流程已补齐私有 answer key：评审包只含 `review_id`，协调者通过
  `merge_dayend_blind_scores.py` 在评分回收后再映射 `case_id`/`variant`。
  评分工具回归 `4 passed`；评审包位于 `.run/dayend-blind-review/`，私钥位于
  `.run/dayend-blind-review-keys/`，后者绝不可发给评审者。
- PostgreSQL 持久化代码准备已完成：新增 `langgraph-checkpoint-postgres`，
  `DAYEND_PERSISTENCE_BACKEND=postgres` 时 checkpoint 使用
  `AsyncPostgresSaver`，业务投影使用 JSONB upsert；新增迁移
  `backend/migrations/028_dayend_business_persistence.sql`。SQLite 兼容路径
  回归 `5 passed`。
- 本地 Supabase PostgreSQL 已恢复后，`028` 已核验存在 `dayend_runs`、
  `dayend_night_states` 及 `dayend_runs_user_created_idx`。Windows 下发现
  `psycopg` 与 Proactor event loop 不兼容，已新增 PostgreSQL 模式专用的
  Selector 启动兼容层。两次独立进程已验证 checkpoint 中断后 resume 与 JSONB
  业务投影读取，测试记录已清理；新的无 reload 后端启动器健康检查通过。

### 未完成 / 不得误报

- VS Code Codex 当前没有可用 Browser 控制面板；Dayend Activity Drawer 的真实
  浏览器确认/resume 验收仍未执行，不得标记为通过。
- 用户确认无法取得两位独立评审的 JSONL；本交付将 A/B/C 质量指标与货币成本
  正式记为 `N/A（质量复核未完成）`。评审包和私有 answer key 继续保留，以便未来
  独立复核；不得用自动评分、协调者评分或推断结果替代。
- PostgreSQL 已在本地 Supabase 环境通过迁移对象、进程重启恢复与启动器验证；
  这仅代表本地验收，尚未构成部署到生产环境的声明。
- Windows `uvicorn --reload` 在该环境可能陷入命名管道 `WinError 5` 循环。
  验收时使用无 reload 的单进程后端，并确保它继承
  `NO_PROXY=localhost,127.0.0.1`，否则本地 Supabase 认证会错误走系统代理。

### 当前交付结论与后续顺序

- Dayend V3 后端技术验收为**有限通过**：真实运行批次、权限、SSE 语义、SQLite /
  PostgreSQL 持久化恢复及专项回归已有证据。
- A/B/C 人工质量结论为 **N/A（豁免，待未来独立复核）**，不构成质量优于基线或
  最终完整验收通过的证据。
- Activity Drawer 的真实浏览器 HITL 验收仍为未完成。
- 前端生产构建已完成 vendor 分包；最大 chunk 由 517.26 kB 降至 246.83 kB，
  不再出现 >500 kB 构建警告。
- 真实完整 E2E `acceptance-20260913T205814-live` 完成为 43/46：认证、真实 PDF
  处理、隔离、Chat、Artifacts（含思维导图）、考试/评分、计划及隐私流程通过；
  Chandler/Andrews/Johnson 检索检查仍未达标，Golden Recall@5 为 18/20。

1. 在支持 Browser 的 Codex 客户端完成真实 Activity Drawer 与 HITL UI 验收。
2. 如未来取得两位独立评分 JSONL，再用私有 answer key 合并、校验并补发 A/B/C
   质量报告；此前不得修改 `N/A` 结论。

## 2026-09-10 — Dayend V3 真实验收与工作区整理续作（最新）

### 已完成并提交

- 工作区已整理为干净状态；已删除 17 个 `test-*.sqlite` 测试产物，并在 `.gitignore` 中忽略根目录 `data/dayend/*.sqlite`。
- 已提交：
  - `cc2b171 feat(dayend): add stateful multi-agent runtime and acceptance`
  - `be97fea fix(dayend): make checkpoint persistence async-safe`
- 真实 SiliconFlow 逐 Agent 结构化验收已覆盖 Supervisor、Closure、Planning、Emotion、Safety、Critic、Morning；运行元数据记录在本地 `.run/dayend-*.log`，不提交。
- 真实 Mixed 图验收完成：Closure/Emotion 并行，分别依赖到 Planning/Safety，最终由 Critic 汇合。
- 真实 Critic revision 验收完成：Critic 指向 `planning_agent`，Planning 带反馈修订，Critic 复审通过；完整 Trace 为 3 条。
- 真实 HITL 验收完成：真实 Closure → SQLite checkpoint → 新图实例 → `resume(thread_id)`；人工响应为 `{"confirmed": false, "status": "unfinished"}`。

### 本轮修复

- Dayend async 图原先搭配同步 `SqliteSaver`，真实 HITL 报错。生产 `/api/v3` 现使用 `AsyncSqliteSaver`，子图由根图持久化。
- Dayend checkpoint serializer 显式允许 `AgentEnvelope[TypeVar]` 和 `AgentTrace`，跨实例 resume 不再出现未来版本将拒绝的未注册类型警告。
- Agent runtime 增加 120 秒硬超时、失败类型 Trace 和 provider token usage 采集；Critic 的路由目标由其 issue 的 `target_agent` 确定性投影，避免重复字段冲突。
- 持久化测试显式关闭 SQLite saver，防止 Windows 留下锁定的测试数据库。

### 当前验收状态与门禁

- Dayend/图/API/运行时专项测试通过；最近一轮异步持久化相关回归为 `14 passed`，serializer 修复后的本地回归为 `3 passed`。
- 前端 `npm run lint`、`npm run build` 通过；构建仍有 509.37 kB 主 chunk 警告。
- 后端完整 `pytest tests -q` 能推进到约 85%，随后在后段检索/计划测试无 CPU 进展；该完整回归目前为未完成，不能写成通过。单独的 assistant 用例可通过。

### 下一步（严格顺序）

1. 补齐 `/api/v3/runs/stream` 的细粒度 SSE：`agent_started`、真实 tool-call、`revision_started`、`critic_failed`、明确 `run_failed`/`run_completed`。
2. 前端在 `MainLayout` 挂载 Dayend Activity Drawer；使用受认证的 fetch streaming 消费 POST SSE，并提供 HITL 确认/resume 交互。
3. 为 SSE 与前端消费增加自动化契约测试和一次真实流式验收；不得用模拟活动替代真实 Trace。
4. 诊断并恢复完整后端 pytest 门禁，再进入 100-case evaluation、A/B/C ablation 与生产 PostgreSQL 迁移。

### 后续启动提示

```powershell
Set-Location C:\Users\xingk\Desktop\Final-Term-main
git status --short
Get-Content -Raw -Encoding UTF8 .\HANDOFF.md

Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests\graphs tests\architecture\test_v3_api_contract.py tests\runtime\test_agent_factory.py tests\scripts -q -p no:cacheprovider
```

真实 Dayend 验收前只检查非敏感开关：`MOCK_EXTERNAL_APIS=false`；不得输出 API key、提交 `.run/`、`data/` 或 `.env`。

## 2026-09-01 — Dayend V3 Multi-Agent 重构续作（最新）

### 本轮新增与已验证

- 新增 Dayend V3 独立运行时（不替换现有 `/api/v1` 考试复习 API）：
  - 7 个 Agent：Supervisor、Closure、Planning、Emotion、Safety、Critic、Morning；
  - LangGraph shared state、Critic revision loop、HITL `interrupt()/resume`、SQLite checkpoint；
  - Closure → Planning、Emotion → Safety 依赖；Mixed 图使用 fan-out/fan-in；
  - 独立 V3 business SQLite 保存 Closure、Planning、Emotion、人工确认与 run projection；
  - `/api/v3/runs`、查询、resume 和 SSE run stream 已挂载。
- 真实模型统一走项目现有 SiliconFlow OpenAI-compatible 配置：
  - `EXAMAI_OPENAI_BASE_URL=https://api.siliconflow.cn/v1`；
  - `EXAMAI_OPENAI_API_KEY`（绝不输出或提交）；
  - Dayend 显式使用 `trust_env=False`，避免环境中错误的 `127.0.0.1:9` 代理；
  - 可用 `DAYEND_ORCHESTRATOR_MODEL`、`DAYEND_SPECIALIST_MODEL`、
    `DAYEND_CRITIC_MODEL`、`DAYEND_SAFETY_MODEL` 在同一 SiliconFlow provider 内按角色选模型。
- 真实调用验收已成功（不是 mock）：
  - SiliconFlow `/models` 带鉴权请求返回 HTTP 200；
  - Dayend `supervisor_agent` 完成一次真实结构化调用，返回 `SupervisorOutput`，
    trace `success`，模型为 `deepseek-ai/DeepSeek-V4-Flash`，attempt=1；
  - 模型故障时运行时抛出 `AgentRunFailed`，没有旧规则 fallback。
- 最近本地专项验收：业务持久化、Mixed/Morning 图和 Critic revision 相关测试 6/6 通过；
  更早一轮 V3 图/API/架构专项测试 17/17 通过。pytest 仍可能报告 Windows pytest cache 目录权限 warning，
  不代表测试失败。

### 关键文件

| 用途 | 位置 |
| --- | --- |
| V3 主图 / 子图 | `backend/app/graphs/root_graph.py`、`mixed_graph.py`、`morning_graph.py` |
| Agent runtime 与 SiliconFlow 模型工厂 | `backend/app/runtime/agent_factory.py`、`model_factory.py` |
| V3 API 与 run service | `backend/app/api/runs.py`、`backend/app/services/dayend_run_service.py` |
| Checkpoint / 业务持久化 | `backend/app/persistence/checkpointer.py`、`store.py` |
| V3 合约、状态、工具 | `backend/app/schemas/`、`state/dayend_state.py`、`tools/` |
| 真实模型验收脚本 | `backend/scripts/verify_dayend_live.py` |
| 审计与验收文档 | `docs/V2_ARCHITECTURE_AUDIT.md`、`docs/MULTI_AGENT_*.md`、`docs/AGENT_*.md` |

### 仍未完成 / 不得误报

- 100-case evaluation 与 A/B/C ablation 尚未建立或运行；
- 前端尚未接入 V3 SSE Agent Activity Drawer 与人工确认 UI；
- SSE 仍未完整覆盖规范要求的所有细粒度事件（例如真实 tool-call、critic-failed、revision-start）；
- 生产 PostgreSQL checkpoint、生产业务数据库迁移和完整 server-restart E2E 尚未完成；
- 需继续以真实 SiliconFlow 调用覆盖 Closure、Planning、Emotion、Safety、Critic、Morning 及 Mixed 全链路，
  不得用 mock 代替真实架构验收。

### 后续执行顺序

1. 逐 Agent 跑真实 SiliconFlow structured-output 验收，并记录 trace/latency/token；
2. 补齐 Critic revision、Mixed、HITL resume 的真实端到端测试；
3. 补齐 SSE 细粒度事件并在前端消费真实 trace；
4. 建立 100-case 数据集、A/B/C ablation 和真实指标报告；
5. 完成生产持久化迁移及重启恢复验收后，才可宣称 V3 完整完成。

更新时间：2026-08-24（Asia/Shanghai）

项目路径：`C:\Users\xingk\Desktop\Final-Term-main`

基线提交：`2a058b8d511f3d58bf204798d95a747eda8f269a`（`main`）

## 新窗口首先执行

```powershell
Set-Location C:\Users\xingk\Desktop\Final-Term-main
git status --short
Get-Content -Raw -Encoding UTF8 .\HANDOFF.md
```

必须遵守：

- 当前工作区包含尚未提交的连续修复和验收文档，不要执行 `git reset --hard`、`git checkout --` 或覆盖现有改动。
- `.env` 含真实密钥并被 `.gitignore` 忽略。只能查看必要的布尔开关，禁止输出、提交或复制密钥值。
- 不要删除 `PDF资料/` 中的用户资料，也不要擅自更改其提交状态。
- Windows PowerShell 5 读取中文文件时显式使用 `-Encoding UTF8`。
- 真实验收不得自动切换 Mock；未运行真实外部服务时必须写 N/A 或未验证。

## 当前工作区结论

本轮用户限定只完成原规划中的：

1. 第一阶段：建立基线。
2. 第二阶段：代码去重与失效代码清理。
3. 第三阶段：接口矩阵与契约收敛。
4. 第九阶段：项目技术面试文档。

真实 E2E、可观测性改造、性能成本采集、故障注入及修复后的第二轮真实验收不在本轮范围内。不能用本轮的 170 个自动化测试宣称完整真实验收通过。

当前 Git 工作区是脏的。主要变更约为 48 个已跟踪文件、126 行新增、671 行删除，另有以下未跟踪交付物：

- `backend/app/services/generation_task_service.py`
- `docs/acceptance/`
- `PROJECT_TECHNICAL_INTERVIEW_GUIDE.md`

提交前必须重新查看 `git status --short`，数字以当时结果为准。

## 当前运行状态

以下为 2026-08-24 本轮只读探测结果：

| 服务 | 当前状态 | 地址/证据 |
| --- | --- | --- |
| Frontend | 未运行 | `127.0.0.1:5173` 不可连接 |
| Backend | 未运行 | `127.0.0.1:8000` 不可连接，`/health` 不可用 |
| Supabase | 端口可连接 | `http://127.0.0.1:18000` |
| Mailpit | 端口可连接 | `http://127.0.0.1:8025` |
| Redis | 端口可连接 | `127.0.0.1:6379` |
| Celery Worker | 在线 | `celery@sky: OK / pong`，1 node |
| Celery Beat | 本轮未单独复验 | N/A |

启动与停止：

```powershell
.\start-project.ps1 -NoBrowser
.\stop-project.ps1
```

启动器负责本地 Supabase、Redis/Celery 组件、Windows Worker、FastAPI 与 Vite。Windows Worker 的历史原因是 Docker/WSL 到阿里云 OSS 曾出现 TLS `UNEXPECTED_EOF_WHILE_READING`，Windows 主机直连正常。

## 本轮已完成：基线与回归

### 清理前基线

| 门禁 | 结果 |
| --- | --- |
| 后端完整测试 | `170 passed, 3 warnings`，15.47s |
| 前端 lint（`tsc --noEmit`） | 通过 |
| 前端生产 build | 通过，7.46s |
| 最大 chunk | 509.75 kB，gzip 150.70 kB |
| OpenAPI | 147 paths / 177 operations |

### 清理后最终回归

| 门禁 | 结果 |
| --- | --- |
| 后端完整测试 | `170 passed, 3 warnings`，10.27s |
| 受影响测试 | `35 passed, 1 warning` |
| 前端 lint | 通过 |
| 前端生产 build | 通过，6.27s |
| 最大 chunk | 509.37 kB，gzip 150.58 kB；仍有 Vite 警告 |
| Ruff `F` 类 | 通过，0 条 |
| Knip | 通过，0 个未使用依赖/文件/导出 |
| E2E 脚本 | `py_compile` 通过；未执行真实 E2E |
| OpenAPI | 62 paths / 75 operations，当前契约校验通过 |

pytest 的 3 条警告来自 Starlette TestClient/httpx2 迁移，以及 Supabase client 的 `timeout`/`verify` 弃用参数，不是本轮回归失败。

## 本轮已完成：API 收敛

### 唯一业务前缀

- 所有业务 API 只挂载在 `/api/v1`。
- `/health` 是唯一无版本公开路径。
- 删除 68 条无前缀业务镜像。
- 前端 `apiV1()`、自动化测试和 E2E 脚本均已改为 `/api/v1`。

### 删除 Workbench Mock

- 删除 `backend/app/api/workbench.py`（121 行占位数据）。
- 删除 `/api/workbench/*` 的 10 个 path。
- 删除对应占位测试和前端 `VITE_MOCK_APP` 分支。
- `.env.example` 与 `frontend/.env.example` 不再声明 `VITE_MOCK_APP`。
- 本地真实 `.env` 里即使还保留历史 `VITE_MOCK_APP=false`，代码也不再读取它。

`mock_external_service.py` 仍保留，用于自动化测试的确定性模型替身；它与已删除的无认证 Workbench Mock 不同。真实验收必须设置 `MOCK_EXTERNAL_APIS=false`。

### 重复业务入口

| 已删除入口 | 唯一替代入口 |
| --- | --- |
| `/exams/attempts/*` | `/api/v1/exam-attempts/*` |
| `/outline/generate` | `/api/v1/artifacts/outlines` |
| `/quiz/generate` | `/api/v1/exams/generations` |
| `POST /api/v1/exams` 同步生成 | `POST /api/v1/exams/generations` |
| `POST /api/v1/study-plans` 同步生成 | `POST /api/v1/study-plans/generations` |
| 错题本页面/公开说明 | 练习表现分析、掌握度与学习信号 |

考试和复习计划的内部 service 仍保留，供 Celery Worker 与 assistant 编排调用；删除的是重复的同步 HTTP 入口。

### 错题本边界

- 已删除前端旧重定向、README 公开错题本说明和失效静态验收脚本。
- router agent 仍识别“错题”等旧用户表达，将其映射为“分析练习表现”；这不是错题本入口。
- `wrong_answers` 历史表按用户要求暂时保留。
- 隐私导出、数据删除和账户删除仍覆盖该表。

## 本轮已完成：代码去重

### Generation task 公共实现

考试与计划 generation service 原本各自实现：

- payload 规范化；
- SHA-256 指纹；
- queued/running 活跃任务查询；
- 幂等复用；
- `processing_tasks` 创建与元数据初始化。

现在统一到：

- `backend/app/services/generation_task_service.py`

两个原 service 保留为薄适配器，仅传入 task type、idempotency 前缀和结果字段（`examId` / `planId`）。指纹稳定性有自动化测试保护。

### 静态扫描结果

| 工具 | 清理前 | 清理后 |
| --- | --- | --- |
| Knip | 2 个未使用依赖、11 个未使用导出 | 0 |
| Ruff 未使用/未定义符号 | 存在真实未使用 import | `--select F` 为 0 |
| Vulture 80% | — | 仅 2 个 Pydantic validator `cls` 反射误报 |
| jscpd 克隆块 | 19 | 14 |
| jscpd 重复行 | 133（1.01%） | 91（0.71%） |

已删除的典型失效代码：4 个旧 agent 占位模块、旧 constants/eval/logger 包装、同步 LLM 包装、旧 parse 包装、`verify_plan_coverage.py`、未使用的 GSAP 依赖和前端同步 `createExam` 方法。

### 有意保留的候选

- `/api/v1/materials/upload` 同步接口仍存在，目前由后端处理链路测试使用；正式前端和 E2E 已统一到 `/materials/uploads`。删除前应先把同步处理测试下沉到 service 层。
- jscpd 剩余 14 个短克隆多为 API 适配、模型字段或 assistant 分支；继续抽取未必提高可读性。
- Ruff 首次全规则有 214 条，其中大量是 FastAPI `Depends` 的 B008、导入排序和宽泛异常历史债；本轮没有用自动格式化扩大修改范围。

## 新增交付文档

| 文档 | 内容 |
| --- | --- |
| `docs/acceptance/ACCEPTANCE_PLAN.md` | 本轮范围、环境、基线、实施结果和回归证据 |
| `docs/acceptance/API_ACCEPTANCE_MATRIX.md` | 页面 → 前端方法 → HTTP → Service → 数据表 → 测试 |
| `docs/acceptance/DUPLICATION_AUDIT.md` | Ruff/Vulture/Knip/jscpd 候选、处理和保留理由 |
| `docs/acceptance/openapi-before.json` | 清理前 147 paths / 177 operations |
| `docs/acceptance/openapi-after.json` | 清理后 62 paths / 75 operations |
| `PROJECT_TECHNICAL_INTERVIEW_GUIDE.md` | 架构、时序、技术选型、RAG、异步、安全、40 个问答和演示流程 |

旧 `backend/BASELINE.md` 已删除，避免继续传播 `88 passed` 和失效静态脚本结果。

## 历史真实链路修复（2026-08-23 证据）

以下是上一轮已完成并写入原交接文档的真实运行事实。本轮没有重新执行真实 E2E，不应把它们当作 2026-08-24 新验收结果。

### 认证、UUID 与账号隔离

- 前端不再用 `math` 等 Mock 学科 ID 调用 UUID 接口。
- localStorage 当前学科按账号隔离，并验证 UUID。
- 非 UUID 学科输入返回明确校验错误，不再导致数据库 500。

### MinerU 与 Worker 恢复

- MinerU Token 当时已验证有效，能签发上传票据。
- `mineru_client.py` 控制请求和文件传输不读取失效系统代理。
- Worker 重启会恢复 queued/running 任务；终态重复投递保持幂等。
- 相关代码：`backend/app/worker/recover.py`、`scripts/dev-worker.ps1`。

### LightRAG 降级

- MinerU、内容块与向量化完成后，LightRAG 不再阻塞材料 ready。
- LightRAG 有 180 秒总超时；失败时记录 index failed，但关键词与 pgvector 继续使用。
- 当时的 Embedding 为 4096 维，而 PostgreSQL pgvector HNSW 索引限制为最多 2000 维；LightRAG 图索引不能按当前方案建立 HNSW。
- 不要为了恢复 LightRAG 再次让它阻塞材料 ready。可选长期方案：LightRAG 单独低维 Embedding 或替换向量存储。

### `What is strategy` 历史回归

- 查询 Embedding 不再读取失效系统代理。
- 定义类问题支持中英文查询扩展和同页上下文补充。
- 历史实测检索耗时约 0.74s，首条证据为 `Lecture 2.pdf` 第 33 页，召回 Chandler（1962）定义。
- 该耗时是历史单次结果，不是 p50/p95。

### 真实模型历史配置

- 上一轮记录为 `MOCK_EXTERNAL_APIS=false`。
- Provider：`openai_compatible`。
- Chat：`deepseek-ai/DeepSeek-V4-Flash`。
- Embedding：`Qwen/Qwen3-VL-Embedding-8B`。
- 历史 Chat 日志延迟约 9–12s。

本轮只确认设置默认值与文档，没有输出密钥，也没有重新发起模型请求。真实验收前必须再次检查布尔开关与 `generation.mocked=false`。

### 专项练习

- practice 的主题必填；单题型数量允许 0～20，总数至少为 1，页面总上限 20。
- `course_first` 默认以课程资料为准，公开知识失败时安全降级并记录 warning。
- 生成按批次执行，默认每批 4 题、60 秒超时、失败批次局部重试 1 次。
- checkpoint 保存已完成题目和证据；Worker 重启后可从剩余批次继续。

## 关键代码位置

| 功能 | 文件 |
| --- | --- |
| FastAPI 挂载与异常 | `backend/app/main.py` |
| API router | `backend/app/api/router.py` |
| 配置 | `backend/app/config/settings.py` |
| 统一 generation task | `backend/app/services/generation_task_service.py` |
| 考试异步入口 | `backend/app/api/exams.py` |
| 考试作答入口 | `backend/app/api/exam_attempts.py` |
| 考试生成与校验 | `backend/app/services/exam_service.py` |
| 考试证据检索 | `backend/app/services/exam_retrieval_service.py` |
| 计划异步入口 | `backend/app/api/study_plans.py` |
| 计划排程 | `backend/app/services/study_plan_service.py` |
| MinerU | `backend/app/services/mineru_client.py`、`mineru_parser.py` |
| 资料入队/处理 | `backend/app/services/ingestion_service.py`、`material_service.py` |
| 混合检索 | `backend/app/services/retrieval_service.py` |
| LightRAG | `backend/app/services/lightrag_service.py` |
| RAG 回答 | `backend/app/services/rag_service.py` |
| Worker 任务/恢复 | `backend/app/worker/tasks.py`、`recover.py` |
| 前端 API | `frontend/src/api/client.ts` |
| 账号隔离状态 | `frontend/src/stores/useAppStore.ts` |
| 考试页面 | `frontend/src/pages/Exams/index.tsx` |
| 计划页面 | `frontend/src/pages/Plan/index.tsx` |
| 动态 E2E | `backend/scripts/e2e_acceptance.py` |

## 环境与验收命令

### 只显示关键布尔值

不要打印整个 `.env`：

```powershell
$names = 'MOCK_EXTERNAL_APIS','CELERY_TASK_ALWAYS_EAGER','ENABLE_MINERU'
foreach ($name in $names) {
  Get-Content .env |
    Where-Object { $_ -match ('^' + [regex]::Escape($name) + '=') } |
    Select-Object -Last 1
}
```

真实验收硬门槛：

```text
MOCK_EXTERNAL_APIS=false
CELERY_TASK_ALWAYS_EAGER=false
ENABLE_MINERU=true
```

前端已没有 `VITE_MOCK_APP` 模式。

### 自动化回归

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe -m py_compile scripts\e2e_acceptance.py

Set-Location ..\frontend
npm run lint
npm run build
```

### 服务健康

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health

Set-Location .\backend
.\.venv\Scripts\python.exe -m celery `
  -A app.worker.celery_app:celery_app inspect ping --timeout 5
```

### OpenAPI 保护

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -c "from app.main import app; p=app.openapi()['paths']; assert not any(x.startswith('/api/workbench') for x in p); assert '/subjects' not in p; assert '/api/v1/subjects' in p; print(len(p))"
```

预期输出：`62`。

## 当前数据状态（历史，未在本轮复验）

- `Lecture 2.pdf`：历史状态 ready，任务 succeeded，160/160 切片有向量。
- `Lecture 3.pdf`：历史状态 ready，任务 succeeded，127/127 切片有向量。
- 两个文件历史 LightRAG 状态为 failed，但关键词和向量问答可用。
- 本轮没有查询数据库重新确认，是否需要重新上传应先通过真实 API/数据库检查，不要仅依据本文猜测。

## 已知限制

- 本轮未执行真实 Supabase 登录、邮件、真实 PDF、MinerU、Embedding、Chat、双用户隔离或故障注入。
- p50/p95/max、Token、模型成本和外部服务成本均为 N/A，不能写成 0。
- 前端主 chunk 仍超过 500 kB。
- `/api/v1/materials/upload` 同步迁移候选尚未删除。
- OpenAPI 与前端类型尚未自动生成绑定，当前靠手写适配、lint 和接口矩阵保护。
- Ruff 全规则历史债尚未建立正式项目配置。

## 建议的后续任务

按优先级：

1. 提交或按主题拆分当前工作区，先保住阶段 1/2/3/9 成果。
2. 启动 FastAPI/Vite 后执行真实环境预检，确认所有关键服务和 Mock 开关。
3. 建立 20～30 个带页码 Golden Questions，执行 Recall@5、引用页码和跨学科污染评估。
4. 用两个真实用户完成认证、资源 UUID 越权、缓存与隐私隔离测试。
5. 执行真实异步资料、考试、评分、学习信号和计划闭环。
6. 注入 Redis、Worker、MinerU、模型、LightRAG、Token 与网络异常。
7. 补齐阶段耗时、Token、模型价格和 JSONL/CSV 成本报告。
8. 修复问题后执行第二轮完整真实回归，不能只重跑失败步骤。
9. 将 `/materials/upload` 的处理测试下沉 service 后删除同步入口。
10. 做路由/依赖拆包，解决 509.37 kB chunk 警告。

## 提交建议

不要提交 `.env`、`.env.worker`、`.run/`、日志、缓存或密钥。可按以下主题拆分：

1. `refactor(api): remove legacy and workbench routes`
2. `refactor(tasks): unify generation idempotency`
3. `test(api): protect canonical v1 contracts`
4. `docs: add baseline audit matrix and interview guide`

提交前再次运行后端完整测试、前端 lint/build 和 `git diff --check`。

## 给后续助手的建议提示词

> 请先阅读 `C:\Users\xingk\Desktop\Final-Term-main\HANDOFF.md`、`docs/acceptance/ACCEPTANCE_PLAN.md` 和当前 `git status`。保留所有现有改动与密钥安全约束。业务接口只允许 `/api/v1`，不要恢复无前缀路由、`/api/workbench/*`、同步考试/计划入口或公开错题本。未执行真实链路时必须写 N/A，不要把自动化测试当成真实验收。

## 2026-08-24 阶段 4–6 续作

已完成可观测性与真实 E2E 改造，并执行真实后端验收。最终 run：`acceptance-20260824T021739-934fed33`，42/47 通过；Golden Recall@5 为 0.90。真实 Supabase 双账号、真实 PDF、MinerU、Embedding、Chat、异步考试/评分、复习计划、导出和隐私清理均已运行。思维导图真实调用仍为 502；Andrews/Johnson 两条 Golden Questions 未命中目标页；前端真实登录态因内置浏览器插件初始化冲突为 N/A。详见 `docs/acceptance/PHASE_4_6_ACCEPTANCE.md`。

新增迁移 `backend/migrations/027_observability_trace_context.sql` 只需应用一次。不要再次用验收脚本重放全部历史迁移；历史 migration 中 `search_content_blocks` 返回类型变更不可重复执行。

最终 run 时旧 `.env` 零价导致原始报告成本错误显示为 0；现已把本地非敏感价格键修正为 SiliconFlow 官方 CNY 价格，并在 E2E 中增加正价格硬门槛。原始 0 不得作为成本证据。
