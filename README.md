# Exam AI Assistant

一个面向短期考试复习场景的 AI 学习助手。用户可以按学科上传 PDF、TXT、DOCX 资料，系统会解析文档、切分文本、生成向量索引，并通过 LightRAG + LLM 提供基于资料的中文问答、引用片段、问答历史和复习进度记录。

## 功能特性

- Supabase Auth 用户注册、登录与后端 Bearer Token 校验
- 学科创建、查询、更新、删除
- PDF / TXT / DOCX 学习资料上传
- 文档文本解析、chunk 切分与材料处理状态记录
- OpenAI-compatible Embedding API 调用
- Supabase Postgres + pgvector 向量存储
- LightRAG 混合检索与资料索引
- 基于检索上下文的中文问答生成
- 回答引用来源片段，避免脱离资料编造
- 问答历史记录
- 复习进度统计
- 提纲、测验、思维导图模块预留

## 技术栈

### 前端

- React 19
- TypeScript
- Vite
- Supabase JS Client

### 后端

- Python
- FastAPI
- Uvicorn
- Pydantic / pydantic-settings
- Supabase Python Client
- PyJWT
- pypdf
- python-docx
- httpx

### 数据与检索

- Supabase Auth
- Supabase Postgres
- Row Level Security
- pgvector
- HKUDS LightRAG
- OpenAI-compatible Chat Completion / Embedding API

## 项目结构

```text
backend/
  app/
    api/          # FastAPI 路由
    agents/       # Agent 分层预留与编排模块
    config/       # 配置项
    db/           # Supabase 与向量存储适配
    models/       # Pydantic 数据模型
    prompts/      # LLM Prompt 模板
    services/     # 文档解析、切分、Embedding、RAG、LLM、记忆服务
    utils/        # 通用工具
  migrations/     # 数据库迁移 SQL
  scripts/        # 端到端验收脚本
  tests/          # 后端测试
  requirements.txt

frontend/
  src/
    api/          # 前端 API 请求封装
    components/   # UI 组件
    lib/          # Supabase Client
    pages/        # 页面模块
    stores/       # 前端状态
    types/        # TypeScript 类型
    utils/        # 工具函数
  package.json

supabase-project/
  docker-compose.yml
  volumes/        # 本地 Supabase 运行配置
```

## 环境变量

后端默认读取 `.env`：

```env
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:5173

SUPABASE_URL=http://localhost:18000
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_JWT_SECRET=your_supabase_jwt_secret
DATABASE_URL=postgresql://postgres:your_password@localhost:15432/postgres

EXAMAI_OPENAI_API_KEY=your_model_api_key
EXAMAI_OPENAI_BASE_URL=https://api.siliconflow.cn/v1
EXAMAI_LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
EXAMAI_EMBEDDING_MODEL=Qwen/Qwen3-VL-Embedding-8B

LIGHTRAG_WORKING_DIR=backend/data/lightrag
DEFAULT_ANSWER_LANGUAGE=zh-CN
MAX_UPLOAD_MB=200
```

前端默认读取 `.env`：

```env
VITE_SUPABASE_URL=http://localhost:18000
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
VITE_API_BASE_URL=http://localhost:8000
```

## 本地启动

### 1. 启动 Supabase

```bash
cd supabase-project
docker compose up -d
```

### 2. 安装后端依赖

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 执行数据库迁移

将 `backend/migrations/` 下的 SQL 按编号顺序应用到本地 Supabase Postgres。

也可以在启动后端和 Supabase 后运行验收脚本自动应用：

```bash
python scripts/e2e_acceptance.py --apply-migrations
```

### 4. 启动后端

```bash
cd backend
uvicorn app.main:app --reload
```

后端默认地址：

```text
http://localhost:8000
```

健康检查：

```text
GET /health
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认地址：

```text
http://localhost:5173
```

## 主要 API

| 模块 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 健康检查 | GET | `/health` | 服务状态 |
| 用户 | GET | `/auth/me` | 获取当前登录用户 |
| 学科 | GET | `/subjects` | 获取学科列表 |
| 学科 | POST | `/subjects` | 创建学科 |
| 学科 | GET | `/subjects/{subject_id}` | 获取学科详情 |
| 学科 | PATCH | `/subjects/{subject_id}` | 更新学科 |
| 学科 | DELETE | `/subjects/{subject_id}` | 删除学科 |
| 资料 | GET | `/materials` | 获取资料列表 |
| 资料 | POST | `/materials/upload` | 上传资料并建立索引 |
| 检索 | POST | `/retrieval/search` | 检索学科资料上下文 |
| 问答 | POST | `/chat/ask` | 基于资料问答 |
| 问答 | GET | `/chat/history/{subject_id}` | 获取问答历史 |
| 复习 | GET | `/review/{subject_id}/progress` | 获取复习进度 |
| 复习 | PATCH | `/review/{subject_id}/progress` | 更新复习进度 |
| 提纲 | POST | `/outline/generate` | 提纲生成接口预留 |
| 测验 | POST | `/quiz/generate` | 测验生成接口预留 |

## 支持的上传文件

- PDF：支持可提取文本的 PDF，暂不包含 OCR
- TXT：要求 UTF-8 编码
- DOCX：支持正文段落文本提取
- 默认最大上传大小：200MB

## 数据表

当前业务表包括：

- `subjects`：用户创建的学科
- `materials`：上传资料元数据与处理状态
- `material_chunks`：文档切片、embedding 与元数据
- `lightrag_material_index`：LightRAG 索引状态
- `chat_messages`：问答历史
- `review_progress`：复习进度

所有核心业务表按 `user_id` 隔离，并启用 RLS 策略。

## 测试与验收

运行后端单元测试：

```bash
cd backend
pytest
```

生成验收数据：

```bash
cd backend
python scripts/e2e_acceptance.py --generate-only
```

运行端到端验收：

```bash
cd backend
python scripts/e2e_acceptance.py
```

验收脚本会检查 Supabase Auth、数据库迁移、学科隔离、资料上传、检索引用、问答生成、历史记录、复习进度和跨用户隔离等核心链路。

## 当前状态

项目已完成短期备考问答 MVP 的主要后端链路，包括用户认证、学科管理、资料上传、文档解析、embedding 入库、LightRAG 检索、LLM 回答、引用片段、历史记录和复习进度。

前端已实现基础页面与接口调用，包括登录、学科管理、资料上传和材料问答。提纲、测验、思维导图目前为预留模块，后续可继续扩展为完整的复习辅助能力。

## 适用场景

- 考前集中复习
- 基于课程资料的问答
- 根据个人上传资料定位重点
- 带引用来源的知识解释
- 学科维度的复习记录与进度跟踪

## 设计原则

- 回答尽量基于用户上传资料
- 引用必须来自检索到的文档片段
- 当资料不足时明确提示，而不是编造答案
- 用户数据按账号隔离
- 后端保持 API、Service、Agent、DB 分层
- 模型配置使用 `EXAMAI_*` 前缀，避免与系统通用环境变量冲突
