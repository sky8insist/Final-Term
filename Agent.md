# Exam AI Assistant 项目协作说明

本文档是本项目的开发协作基准，面向后续 Codex/Agent 和开发者。它描述项目身份、MVP 链路、技术约定、模块边界、数据设计和验收标准。若代码与本文档冲突，应先核对当前实现，再更新文档或代码。

## 1. 项目身份

本项目是一个面向短期考试复习的 AI 学习助手。

核心能力是让用户围绕某个学科上传资料，并基于这些资料进行提问、获得带引用的中文回答，同时记录问答历史和复习进度。

项目不是通用聊天机器人，也不是完整 LMS 学习平台。MVP 阶段只聚焦“资料驱动的考试复习问答链路”。

从架构定位上看，本项目是面向考试复习场景的 Agentic RAG 项目，不只是普通 CRUD + RAG 应用。即使当前只完成 MVP，也必须从一开始保持 Agent 项目的分层边界：Agent 负责决策，Skill 负责能力封装，MCP 负责工具调用协议 / 外部工具接入，Service 负责具体业务实现，Supabase 负责数据存储。

## 2. 项目背景

用户通常会在考试前集中准备大量 PDF、TXT、DOCX 资料。传统检索和阅读方式难以快速定位重点、生成针对性解释，也难以持续记录复习状态。

本项目通过 RAG 链路把用户资料转成可检索知识库，再使用 LLM 生成答案、引用来源，并为后续复习规划、测验、提纲和记忆进度提供基础数据。

当前仓库已有后端 FastAPI 骨架、前端 React + Vite 骨架、本地自托管 Supabase 配置，以及若干服务层/Agent 层占位实现。

## 3. 项目目标

MVP 目标：

- 用户可以通过 Supabase Auth 登录。
- 用户可以创建学科。
- 用户可以向某个学科上传 PDF / TXT / DOCX 资料。
- 后端可以解析资料文本、切分 chunk、生成 embedding。
- 向量数据最终存入 Supabase Postgres + pgvector。
- 用户可以基于某个学科资料提问。
- 系统使用 HKUDS/LightRAG 检索相关内容。
- LLM 生成中文答案，并返回引用片段。
- 系统记录问答历史和复习进度。

非目标：

- 不做通用知识问答。
- 不优先做复杂课程体系、班级、作业、支付、权限后台。
- 不把原始上传文件作为长期存储目标。

## 4. MVP 最小链路

MVP 链路固定为：

```text
用户登录
  ↓
创建学科
  ↓
上传 PDF / TXT / DOCX 资料
  ↓
后端解析文档内容
  ↓
文档切分 chunk
  ↓
生成 embedding
  ↓
存入 Supabase / 向量库
  ↓
用户基于资料提问
  ↓
LightRAG 检索相关内容
  ↓
LLM 生成答案
  ↓
返回答案 + 引用片段
  ↓
记录问答历史和复习进度
```

当前已完成：

- 模块 0：前后端环境配置和启动骨架。
- 模块 1：Supabase Auth 登录骨架，包括前端 Supabase client、Bearer token 自动携带、后端 `/auth/me` token 验证。
- 模块 2：学科数据模型和接口，包括本地 Supabase `subjects` 表、RLS、后端 CRUD API、前端 Dashboard 最小闭环。
- 模块 3：资料上传入口和状态模型，包括本地 Supabase `materials` 表、RLS、后端上传/列表 API、前端资料上传最小闭环。
- 模块 4：文档解析与 chunk，包括 TXT / PDF / DOCX 文本解析、同步 chunk 切分、本地 Supabase `material_chunks` 表、RLS、材料状态流转。
- 模块 5：embedding 与向量入库，包括通过硅基流动 OpenAI-compatible `/embeddings` 接口调用 `Qwen/Qwen3-VL-Embedding-8B`、安装 pgvector、写入 `material_chunks.embedding`。
- 模块 6：LightRAG 检索接入，包括 HKUDS/LightRAG Core 初始化、材料同步索引、`/retrieval/search` 检索接口和前端检索调试面板。
- 模块 7：问答生成、引用、历史和进度，包括 `/chat/ask` 真实问答链路、LLM 中文答案生成、引用片段返回、问答历史记录、复习进度自动累计和前端问答页。

规划中：

- 暂无。

## 5. 开发优先级

优先级顺序：

1. 项目可启动、配置清晰、密钥不泄露。
2. 登录和用户身份识别。
3. 学科 CRUD 和用户数据隔离。
4. 资料上传、解析、状态记录。
5. chunk、embedding、pgvector 入库。
6. LightRAG 检索。
7. LLM 生成中文答案和引用。
8. 问答历史、复习进度。
9. 复习提纲、测验、思维导图等增强能力。
10. UI 美化、复杂交互、异步任务队列和运维增强。

每次开发应先完成一个可验收的模块，不跨模块大范围改动。

## 6. 输入设计

主要用户输入：

- 登录输入：邮箱、密码。MVP 使用邮箱密码登录，自动确认邮箱。
- 学科输入：学科名称、可选描述。
- 资料输入：PDF、TXT、DOCX 文件。
- 问答输入：某个学科下的自然语言问题。
- 复习输入：后续可扩展为目标、考试日期、掌握程度、错题反馈。

文件输入约束：

- 上传大小上限：200MB。
- PDF：MVP 先支持可复制文字的 PDF，不优先做 OCR。
- TXT：按 UTF-8 文本读取。
- DOCX：MVP 需要支持。
- 原始文件不作为长期存储目标；后端可临时保存用于解析，解析完成后以材料元数据和 chunk 为主。

## 7. 输出设计

主要系统输出：

- 登录状态和当前用户信息。
- 学科列表、学科详情。
- 资料上传结果和处理状态。
- 问答结果：
  - `answer`：中文答案。
  - `citations`：引用片段列表。
  - `material_id`：引用来源材料。
  - `filename`：引用来源文件名。
  - `chunk_text`：引用片段文本。
  - `score`：相关性分数，允许为空。
- 问答历史。
- 复习进度。

回答必须尽量基于检索上下文，不能伪造引用。无法从资料中确定时，应明确说明资料中未找到足够依据。

## 8. 技术栈

后端：

- Python
- FastAPI
- Uvicorn
- Pydantic / pydantic-settings
- PyJWT
- Supabase Python client

前端：

- React
- Vite
- TypeScript
- Supabase JS client

数据库与基础设施：

- 本地自托管 Supabase
- Supabase Auth
- Supabase Postgres
- pgvector
- RLS

RAG / 模型：

- HKUDS/LightRAG
- 硅基流动 OpenAI-compatible API
- LLM：`deepseek-ai/DeepSeek-V4-Flash`
- Embedding：`Qwen/Qwen3-VL-Embedding-8B`

本地端口约定：

- Supabase API：`http://localhost:18000`
- 后端 API：`http://localhost:8000`
- 前端：`http://localhost:5173`

环境变量约定：

- 后端模型相关变量使用 `EXAMAI_*` 前缀：
  - `EXAMAI_OPENAI_API_KEY`
  - `EXAMAI_OPENAI_BASE_URL`
  - `EXAMAI_LLM_MODEL`
  - `EXAMAI_EMBEDDING_MODEL`
- 不使用裸 `OPENAI_API_KEY`、`LLM_MODEL` 等通用变量，避免被系统环境变量覆盖。

Agent 项目分层架构：

- Agent 负责决策：
  - 识别用户意图。
  - 规划任务步骤。
  - 选择需要调用的能力。
  - 判断是否需要检索、生成、评估或记录 memory。
  - 组织最终响应。

- Skill 负责能力封装：
  - 封装可复用能力，如文档解析、资料检索、问答生成、测验生成、提纲生成、复习规划。
  - Skill 面向 Agent 暴露稳定能力接口。
  - 一个 Skill 可以组合多个 Service。
  - 当前 MVP 尚未创建 `skills/` 目录，不代表项目不需要 Skill 层；后续复杂能力应优先沉淀为 Skill。

- MCP 负责工具调用协议 / 外部工具接入：
  - 统一抽象未来外部工具调用，例如文件系统、数据库管理工具、浏览器、第三方知识库、学习平台或其他模型工具。
  - MCP 层只负责工具协议和适配，不直接承载业务决策。
  - 当前 MVP 不实现完整 MCP Server，但架构上应为后续接入保留边界。

- Service 负责具体业务实现：
  - 执行确定性业务逻辑，例如上传校验、文本解析、chunk、embedding、写库、读库、调用模型 API。
  - Service 不负责自主决策，不直接决定用户意图和多步骤任务计划。

- Supabase 负责数据存储：
  - 负责 Auth、Postgres、pgvector、RLS、业务表、问答历史、复习进度和材料状态。
  - Supabase 是数据事实来源，不负责 Agent 决策。

## 9. 推荐目录结构

当前推荐结构基于现有仓库：

```text
backend/
  app/
    api/          # HTTP 路由层
    agents/       # Router / Retriever / Generator / Planner / Evaluator
    config/       # settings、常量
    db/           # Supabase、向量库适配器
    skills/       # 后续可选：可复用能力封装，当前 MVP 尚未创建
    mcp/          # 后续可选：MCP/tool adapter，当前 MVP 尚未创建
    models/       # Pydantic/domain models
    prompts/      # Prompt 模板
    services/     # 解析、chunk、embedding、RAG、LLM、memory 等服务
    utils/        # 响应、日志、错误处理
  tests/
  .env.example
  requirements.txt

frontend/
  src/
    api/          # 前端 API 调用
    components/   # UI 组件
    lib/          # Supabase client 等基础库
    pages/        # 页面
    stores/       # 简单状态
    types/        # TypeScript 类型
    utils/        # 请求、格式化、文件工具
  .env.example
  package.json

supabase-project/
  .env            # 本地 Supabase 配置，包含敏感信息，不写入文档
  docker-compose.yml
  volumes/
```

后续如果新增 migration，推荐放在项目可维护的位置，并保持命名递增，例如 `backend/migrations/001_subjects.sql` 或 Supabase 本地约定目录。选择后不要混用多个 migration 目录。

目录演进规则：

- 当前 MVP 可以暂不创建 `backend/app/skills/` 和 `backend/app/mcp/`。
- 当某个能力开始被多个 Agent 或 API 复用时，应优先沉淀到 Skill 层。
- 当项目需要接入外部工具、外部知识库或标准化工具调用协议时，应放入 MCP/tool adapter 层。
- 不要把 Agent 决策、Skill 能力封装、Service 业务执行和 Supabase 数据访问混在同一个模块里。

## 10. 数据库设计

数据库目标使用 Supabase Postgres，并启用 RLS 和 pgvector。

规划表：

- `subjects`
  - 用户创建的学科。
  - 当前已实现到本地 Supabase。
  - 字段：`id`、`user_id`、`name`、`description`、`created_at`、`updated_at`。
  - 已启用 RLS。
  - 已创建 select / insert / update / delete 四类用户隔离策略。
  - 已添加 `(user_id, created_at desc)` 索引。
  - 已添加 `updated_at` 自动更新时间 trigger。

- `materials`
  - 用户上传资料的元数据和处理状态。
  - 字段目标：`id`、`user_id`、`subject_id`、`filename`、`content_type`、`status`、`error_message`、`created_at`、`updated_at`。

- `material_chunks`
  - 文档切分后的 chunk 和 embedding。
  - 字段目标：`id`、`user_id`、`subject_id`、`material_id`、`chunk_index`、`content`、`embedding`、`metadata`、`created_at`。

- `chat_messages`
  - 问答历史。
  - 字段目标：`id`、`user_id`、`subject_id`、`role`、`content`、`citations`、`created_at`。

- `review_progress`
  - 复习进度。
  - 字段目标：`id`、`user_id`、`subject_id`、`mastered_count`、`total_count`、`metadata`、`updated_at`。

当前状态：

- `backend/migrations/001_subjects.sql` 已完成并已执行到本地 Supabase。
- `subjects` 表已完成。
- 其他业务表 migration 尚未完成。
- `pgvector` 可用但尚未安装到数据库。
- `subjects` RLS 策略已完成；其他业务表 RLS 策略尚未完成。

RLS 目标：

- 所有业务表按 `user_id = auth.uid()` 隔离。
- 前端只使用 anon key。
- 后端可使用 service role，但必须先验证 Bearer token，并显式使用当前用户 ID 进行读写约束。

## 11. 核心模块职责

总体分层职责：

- Agent 负责决策。
- Skill 负责能力封装。
- MCP 负责工具调用协议 / 外部工具接入。
- Service 负责具体业务实现。
- Supabase 负责数据存储。

调用关系建议：

```text
API 层
  ↓
Agent 层：决策、规划、选择能力
  ↓
Skill 层：封装可复用能力
  ↓
Service 层：执行具体业务
  ↓
Supabase / 外部模型 / LightRAG / MCP 工具
```

在当前 MVP 中，Skill 和 MCP 可以先作为架构约束存在；代码可暂时由 Agent 直接编排 Service，但不得让 Agent 直接写数据库、直接解析文件或直接调用底层模型 API。

`auth`：

- 前端通过 Supabase client 登录、注册、恢复 session、登出。
- 后端验证 Bearer token，并提供当前用户信息。

`subjects`：

- 管理用户学科。
- 所有学科必须归属用户。

`materials`：

- 管理上传资料、文件类型校验、处理状态。
- 不负责长期保存原始文件。

`parse_service`：

- 将 TXT / PDF / DOCX 解析成纯文本。
- PDF MVP 只处理可复制文字，不做 OCR。

`chunk_service`：

- 将长文本切成可 embedding 的 chunk。
- 默认 chunk 参数当前为 `chunk_size=800`、`overlap=120`，后续可按效果调整。

`embedding_service`：

- 调用硅基流动 embedding 模型。
- 返回与 pgvector 维度一致的向量。
- embedding 维度必须在建表前确认或通过 API 探测。

`vector_store`：

- 负责向量写入和向量检索。
- 最终目标是 Supabase Postgres + pgvector。

`rag_service`：

- 负责把检索、Prompt、LLM 生成、引用组织成完整问答流程。

`llm_service`：

- 调用硅基流动 OpenAI-compatible Chat Completion。
- 默认输出中文。

`memory_service`：

- 记录问答历史、复习进度、学习事件。

`skills` 后续目标：

- `document_skill`：封装文档解析、chunk 和材料处理能力。
- `retrieval_skill`：封装 LightRAG / pgvector 检索能力。
- `qa_skill`：封装基于资料的问答能力。
- `quiz_skill`：封装测验生成能力。
- `outline_skill`：封装提纲生成能力。
- `review_skill`：封装复习计划和进度能力。

`mcp` 后续目标：

- 作为外部工具接入层。
- 用统一协议暴露文件、数据库、知识库、浏览器或其他工具。
- 不承载业务规则和用户意图判断。

## 12. Agent 模块设计

`router_agent`：

- 判断用户意图。
- 当前目标意图包括 `qa`、`quiz`、`outline`、`mind_map`、`review_plan`。
- MVP 优先处理 `qa`。

`retriever_agent`：

- 根据 `subject_id` 和用户问题检索相关上下文。
- 后续接入 LightRAG。

`generator_agent`：

- 基于上下文生成答案、提纲、测验。
- 生成结果必须遵守 Prompt 规范和引用规则。

`planner_agent`：

- 后续用于复习计划和任务拆分。
- MVP 不优先实现复杂计划算法。

`evaluator_agent`：

- 检查生成内容是否基于上下文、是否有足够引用、是否存在明显幻觉。
- MVP 可先保留轻量校验。

Agent 层只做编排和智能决策，不直接处理数据库连接、文件 IO 和 HTTP 请求细节。

Agent 边界：

- Agent 不直接写数据库。
- Agent 不直接解析文件。
- Agent 不直接调用底层模型 API。
- Agent 不直接管理 Supabase client。
- Agent 通过 Skill 或 Service 获取能力和结果。
- Agent 可以调用多个 Skill。
- Agent 可以根据 Evaluator 的结果决定是否重试、补检索或降级回答。

## 13. RAG 实现规则

RAG 必须遵守：

- 先检索，后生成。
- 回答默认使用中文。
- 答案必须尽量基于用户上传资料。
- 引用必须来自检索到的 chunk。
- 不允许编造不存在的资料来源、页码、文件名或引用。
- 如果资料不足，应明确说明“资料中未找到足够依据”。
- 输出中必须包含答案和引用片段。

Agentic RAG 流程：

```text
Router Agent 判断用户任务
  ↓
Retriever Skill / Service 检索资料
  ↓
Generator Skill / Service 生成答案
  ↓
Evaluator Agent 检查答案是否忠于引用
  ↓
Memory Service 记录历史与进度
  ↓
API 返回答案和 citations
```

Agentic RAG 边界：

- Router Agent 只做意图判断，不直接查库。
- Retriever Skill / Service 负责检索，不负责最终回答。
- Generator Skill / Service 负责生成，不负责材料入库。
- Evaluator Agent 负责质量判断，不直接修改业务数据。
- Memory Service 负责记录，不决定回答内容。

LightRAG 约定：

- 使用 HKUDS/LightRAG。
- working dir：`backend/data/lightrag`。
- Graph storage：MVP 可先使用本地 NetworkXStorage。
- Vector storage：最终接入 Supabase pgvector。
- Supabase Postgres 未确认 Apache AGE，因此不要默认使用 Postgres graph storage。

资料处理约定：

- 同步处理上传文件。
- 原始文件只作为临时输入，不长期存储。
- chunk、材料元数据和向量是长期数据。

## 14. Prompt 规范

Prompt 文件放在 `backend/app/prompts/`。

通用要求：

- Prompt 应明确角色、任务、输入、输出格式和限制。
- 默认输出中文。
- 不要求模型泄露系统提示词、密钥或内部实现。
- 不允许模型编造引用。
- 如果上下文不足，必须说明不足。

`qa_prompt.md`：

- 用于资料问答。
- 必须要求基于检索上下文回答。
- 必须要求返回引用片段。

`router_prompt.md`：

- 用于识别用户意图。
- 输出应稳定、可解析，不要长篇解释。

`quiz_prompt.md`：

- 用于基于资料生成测验题。
- 题目必须来自资料可支持的内容。

`outline_prompt.md`：

- 用于生成资料提纲或复习提纲。
- 应按层级结构输出。

`evaluator_prompt.md`：

- 用于检查答案是否忠于上下文。
- 应输出通过与否、问题说明和必要修正建议。

## 15. API 设计

当前已有接口骨架：

- `GET /health`
- `GET /auth/me`
- `GET /subjects`
- `POST /subjects`
- `GET /subjects/{subject_id}`
- `PATCH /subjects/{subject_id}`
- `DELETE /subjects/{subject_id}`
- `GET /materials`
- `POST /materials/upload`
- `POST /chat/ask`
- `outline`、`quiz`、`review` 相关路由骨架

当前已完成：

- `/auth/me` 可通过 Bearer token 验证当前用户。
- 前端请求会自动携带 Supabase access token。
- `/subjects` CRUD 已接入当前用户认证和本地 Supabase `subjects` 表。
- 前端 Dashboard 已能通过真实 API 拉取、创建、删除学科。

目标接口行为：

- `GET /subjects`
  - 返回当前用户的学科列表。

- `POST /subjects`
  - 创建当前用户的学科。

- `GET /subjects/{subject_id}`
  - 获取当前用户的单个学科。
  - 不存在或不属于当前用户时返回 404。

- `PATCH /subjects/{subject_id}`
  - 更新当前用户的学科名称和描述。
  - 不存在或不属于当前用户时返回 404。

- `DELETE /subjects/{subject_id}`
  - 删除当前用户的学科。
  - 当前阶段使用硬删除；后续 materials/chunks 接入后再评估软删除或级联策略。

- `POST /materials/upload`
  - 接收 `subject_id` 和文件。
  - 校验类型和大小。
  - 同步完成解析、chunk、embedding、入库。
  - 返回材料状态。

- `POST /chat/ask`
  - 接收 `subject_id` 和 `question`。
  - 检索相关资料。
  - 生成中文答案。
  - 返回 `answer` 和 `citations`。
  - 写入问答历史。

接口设计规则：

- 所有业务接口必须要求登录。
- 后端不得相信前端传来的 `user_id`。
- 用户身份一律来自 Bearer token。
- 错误响应应统一、可读、避免泄露内部堆栈。

## 16. Memory 设计

Memory 在本项目中指学习过程记录，不是 LLM 隐式记忆。

MVP Memory 包括：

- 问答历史：
  - 用户问题。
  - AI 回答。
  - 引用片段。
  - 所属学科。
  - 创建时间。

- 复习进度：
  - 学科维度的掌握数量和总数量。
  - 后续可扩展错题、薄弱点、复习计划。

- 材料处理状态：
  - uploaded
  - processing
  - ready
  - failed

Memory 规则：

- 必须按用户隔离。
- 不存储不必要的敏感信息。
- 引用片段应能追溯到材料和 chunk。

## 17. 错误处理规范

后端错误：

- 认证失败返回 401。
- 权限不足返回 403。
- 资源不存在返回 404。
- 文件类型不支持返回 400。
- 上传过大返回 413。
- 解析、embedding、LLM、RAG 失败返回可读错误，并记录日志。

前端错误：

- 登录失败显示 Supabase 返回的安全错误信息。
- 上传失败显示失败状态。
- 问答失败保留用户问题，不清空输入上下文。

错误信息原则：

- 给用户的信息要可理解。
- 给日志的信息要可定位。
- 不向前端暴露密钥、连接串、堆栈、数据库细节。

## 18. 安全规则

密钥规则：

- 不在文档、前端代码、日志中写入真实密钥。
- `.env` 不提交。
- `.env.example` 只写变量名和占位符。
- 前端只允许使用 Supabase anon key。
- service role key 只能用于后端。

认证规则：

- 登录交给 Supabase Auth。
- 后端业务接口必须验证 Bearer token。
- 后端不得接受前端传入的 `user_id` 作为可信身份。

数据隔离：

- 所有业务数据按用户隔离。
- RLS 必须开启。
- 后端使用 service role 时仍要显式按当前用户过滤。

上传安全：

- 限制文件类型和大小。
- 不执行上传文件中的任何内容。
- 临时文件处理后应清理。

## 19. 代码规范

后端：

- 路由层只处理 HTTP 入参、认证依赖和响应。
- 业务逻辑放在 `services/`。
- Agent 编排放在 `agents/`。
- 数据访问放在 `db/`。
- 配置只从 `settings.py` 读取。
- 类型使用 Pydantic model 或明确的 dict 结构。

前端：

- API 调用放在 `src/api/`。
- Supabase client 放在 `src/lib/`。
- 共享类型放在 `src/types/`。
- 可复用 UI 放在 `src/components/`。
- 页面放在 `src/pages/`。

通用：

- 一次任务只改相关文件。
- 不把未完成的占位实现伪装成已完成能力。
- 不提交真实密钥。
- 新增核心能力时同步更新测试或验收说明。

## 20. 测试与验收要求

模块 0 验收：

- 后端 app 可导入。
- 前端可构建。
- `.env.example` 完整但不含真实密钥。

模块 1 验收：

- 可以通过 Supabase Auth 登录。
- 普通注册流程当前存在环境风险：Supabase Auth 容器仍会尝试发送确认邮件，但本地缺少 `supabase-mail`，需要后续重启/修正自动确认配置。
- 前端可以恢复 session。
- 前端请求后端自动携带 Bearer token。
- `/auth/me` 可以返回当前用户。

模块 2 验收：

- 登录用户可以创建学科。
- 刷新后仍能看到自己的学科。
- 未登录访问业务接口返回 401。
- 用户之间数据隔离。
- 登录用户可以读取、更新、删除自己的学科。
- 访问不存在或不属于自己的学科返回 404。
- 本地 Supabase 中 `subjects` 表存在，RLS 已开启，policy 数量为 4。
- 前端生产构建通过，Dashboard 使用真实 API 显示和创建学科。

完整 MVP 验收：

- 使用一个 TXT、一个可复制文字 PDF、一个 DOCX 跑通上传处理。
- Supabase 中可看到材料、chunk、向量和历史数据。
- 用户可以基于资料提问。
- 答案为中文。
- 答案包含引用片段。
- 问答历史和复习进度被记录。

## 21. 当前不要优先做的事情

当前不要优先做：

- OCR 扫描版 PDF。
- 多租户组织、班级、教师端。
- 支付、订阅、额度系统。
- 复杂 UI 美化和动效。
- 手机验证码登录。
- 第三方 OAuth 登录。
- 异步任务队列。
- 分布式部署。
- 复杂学习算法。
- 完整课程管理系统。
- Apache AGE graph storage，除非确认 Supabase Postgres 支持并有明确收益。
- MCP Server 完整实现。
- Skill 插件市场。
- 多 Agent 编排框架。

这些能力可以后续扩展，但不得阻塞 MVP 主链路。

虽然以上内容不优先实现，但 Agent / Skill / MCP / Service / Supabase 的架构边界必须从现在开始遵守。

## 22. Codex 每次完成任务后的输出格式

Codex 每次完成任务后，应按以下格式简洁汇报：

```text
完成内容：
- ...

验证结果：
- ...

未完成 / 风险：
- ...

下一步建议：
- ...
```

如果任务只改文档，可以说明“不运行代码测试”。如果无法运行测试，必须说明原因。若涉及环境变量或密钥，只说明变量是否存在，不输出真实值。
