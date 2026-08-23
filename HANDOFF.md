# 项目交接文档

更新时间：2026-08-23  
项目路径：`C:\Users\xingk\Desktop\Final-Term-main`

## 新窗口首先执行

请先阅读本文，然后在项目根目录执行：

```powershell
git status --short
Get-Content -Encoding UTF8 .\HANDOFF.md
```

重要约束：

- 当前工作区有大量尚未提交的连续修复，不要执行 `git reset --hard`、`git checkout --` 或覆盖现有改动。
- `.env` 包含真实密钥且已被 `.gitignore` 忽略，禁止输出、提交或复制其中的值。
- `PDF资料/Lecture 2.pdf` 是用户提供的测试资料，不要删除或提交，除非用户明确要求。
- Windows PowerShell 5 读取中文文件时应显式使用 `-Encoding UTF8`。

## 当前运行状态

最近一次检查结果：

| 服务 | 状态 | 地址 |
| --- | --- | --- |
| Frontend | 运行中 | `http://localhost:5173` |
| Backend | 健康 | `http://localhost:8000` |
| Backend health | `ok` | `http://localhost:8000/health` |
| Supabase | 运行中 | `http://localhost:18000` |
| Mailpit | 运行中 | `http://localhost:8025` |
| Redis | 运行中 | `localhost:6379` |
| Celery Worker | Windows 主机进程 | `solo` pool，单并发 |
| Celery Beat | Docker | 正常运行 |

启动与停止：

```powershell
.\start-project.ps1 -NoBrowser
.\stop-project.ps1
```

一键启动脚本会：

1. 启动本地 Supabase。
2. 在 Docker 中启动 Redis 与 Celery Beat。
3. 停止 Docker Worker。
4. 在 Windows 主机启动 Celery Worker。
5. 启动或复用 FastAPI 与 Vite。

Worker 放在 Windows 主机运行，是因为当前机器的 Docker/WSL 到阿里云 OSS 存在 TLS `UNEXPECTED_EOF_WHILE_READING`，而 Windows 主机直连正常。

## 已完成的重要修复

### 1. 登录后的 API 500/404

- 前端不再使用 `math` 等旧 Mock 学科 ID 调用 UUID 接口。
- localStorage 学科状态按账号隔离，并验证 UUID。
- 后端对学科 ID 做统一校验，非法 ID 返回明确错误，不再产生数据库 500。
- 邮箱相关修复由用户此前完成，位于 `backend/app/models/user.py`，需保留。

### 2. MinerU 文件长期“解析中”

- MinerU Token 已验证有效，不是假密钥。
- MinerU 能成功签发上传票据；Windows 主机能够直传签名 OSS URL。
- `mineru_client.py` 的控制请求和文件传输不再读取失效的系统代理。
- Worker 重启时会恢复 `queued/running` 任务，代码位于：
  - `backend/app/worker/recover.py`
  - `scripts/dev-worker.ps1`
- 重复投递只处理 `queued/running` 状态，终态任务保持幂等。

### 3. LightRAG 卡住资料入库

- MinerU、内容块和向量化完成后，LightRAG 不再阻塞资料可用状态。
- LightRAG 建图增加 180 秒总超时。
- LightRAG 失败时：
  - `lightrag_material_index.status = failed`
  - `materials.status = ready`
  - 关键词和 pgvector 检索继续可用
- `Lecture 2.pdf` 与 `Lecture 3.pdf` 已恢复为 `ready/succeeded/100%`。

已知 LightRAG 限制：

- 当前 Embedding 为 4096 维。
- PostgreSQL pgvector HNSW 当前限制为最多 2000 维。
- LightRAG 图谱表因此无法建立 HNSW 索引，并且已有模型调用超时。
- 检索代码在没有 `indexed` 图谱时会直接跳过 LightRAG，避免无效初始化和额外延迟。
- 当前可靠链路是“关键词 + 定义查询扩展 + pgvector + RRF + 同页上下文”。

不要为了恢复 LightRAG 再次让它阻塞资料 `ready`。若后续修复，可考虑为 LightRAG 单独使用不超过 2000 维的 Embedding 模型，或更换向量存储策略。

### 4. `What is strategy` 回答质量差

问题原因：

1. 查询 Embedding 请求读取了 Windows 失效代理，向量检索被静默降级。
2. MinerU 将幻灯片标题和定义拆成不同内容块。
3. 原检索只搜索原问题，没有定义式查询扩展。
4. 原回答提示词中的部分中文规则出现过乱码。

现有修复：

- OpenAI-compatible Chat/Embedding 默认 `trust_env=false`。
- 对以下问题生成定义式关键词扩展：
  - `What is X?`
  - `Define X`
  - `什么是 X？`
  - `X 是什么？`
- 命中幻灯片某个块后，自动拼接同页内容，避免标题与正文分离。
- 定义题提示词要求先给资料定义，再解释关键词。
- LightRAG 不可用时仍返回关键词和向量结果。

真实回归结果：

- 查询：`What is strategy`
- 检索耗时约：`0.74 s`
- 首条证据：`Lecture 2.pdf` 第 33 页
- 成功召回 Chandler（1962）完整定义：长期目标、行动方案、资源配置。
- 真实 Chat 模型能基于该定义生成中文解释。

### 5. 确保不是 Mock 回答

当前运行配置已验证：

- `MOCK_EXTERNAL_APIS=false`
- Provider：`openai_compatible`
- Chat 模型：`deepseek-ai/DeepSeek-V4-Flash`
- Embedding 模型：`Qwen/Qwen3-VL-Embedding-8B`
- 模型密钥已配置，但本文不记录密钥内容。

保障机制：

- 如果 `MOCK_EXTERNAL_APIS=true`，AI 问答直接返回 HTTP 503，不会伪装成真实答案。
- 没有检索上下文或引用时，不调用模型生成事实答案，而是明确提示资料依据不足。
- 新回答返回 `generation` 元数据：Provider、模型、是否 Mock、是否有资料依据、引用数量、检索来源。
- 前端回答卡显示：`真实模型调用 · 基于课程资料 · N 条引用`。
- 四种学习模式现在会传给后端，并影响回答组织：详细讲解、快速复习、苏格拉底、考官模式。

最近验证过真实模型调用日志，Chat 请求状态为 `succeeded`，延迟约 9～12 秒；这不是本地 Mock 的即时固定文本。

### 6. `.env` 中文乱码

根因：`.env` 注释曾被错误编码读取后再次保存，形成二次转码乱码；配置值没有损坏。

已完成：

- 使用 `.env.example` 的正常中文注释重建 `.env`。
- 原样迁移 69 个已有配置值。
- 保持 `MOCK_EXTERNAL_APIS=false`。
- 新文件为 UTF-8 无 BOM，乱码注释扫描为 0。
- 原文件备份位于 `.run/env-encoding-backups/`，该目录被 Git 忽略。
- 可重复修复脚本：`scripts/repair-env-encoding.ps1`。
- 通用终端编码脚本：`scripts/enable-utf8.ps1`。
- VS Code 编码固定在 `.vscode/settings.json`。

### 7. 练习题模块：主题、混合检索与生成超时

原问题：

- 专项练习允许不填写主题，导致检索范围不明确。
- 页面没有传递外部知识策略，`externalRatio` 默认值又是 0，因此通常只检索课程资料。
- 整套最多 20 道题一次性要求模型返回完整 JSON；提示词同时包含大量证据和历史题干，固定 75 秒内很容易超时。
- 异步任务入队后保存的是 snake_case 字段，Worker 却按 camelCase 重建请求，曾出现 `subjectId`、`questionTypes Field required`。
- 题型数量输入曾强制最小值为 1，不方便只生成一种题型。

现有修复：

- `assessmentType=practice` 时 `scope` 必填；前端与后端同时校验，空格主题也会拒绝。
- 单个题型数量允许 `0～20`，0 表示不生成；所有题型总数仍必须至少为 1，页面单次上限为 20。
- 练习默认 `knowledgePolicy=course_first`，也可选 `expanded`；课程资料始终决定答案口径。
- 公共知识通过已存在的专业 Web Search 配置或 Wikipedia 兜底接入。公开服务不可用时，`course_first` 安全降级到课程资料，并在任务结果中记录 warning。
- “战略的作用”这类自然语言主题会抽取核心公共检索词“战略”，避免直接把整句交给百科检索。
- 课程检索对主题执行三路查询：原主题、定义/核心关系、作用/应用/误区。
- 课程证据和公共证据统一计算 `relevanceScore`、`importanceScore`、`authorityScore` 和 `finalScore`。
- 先执行最低相关性门槛，再去重和限制单资料占比；低相关公共结果不能直接进入命题上下文。
- 课程知识点重要度来自 `knowledge_points.importance`，并参与最终排序。
- 生成改为每批最多 4 题，默认单批 60 秒、失败批次局部重试 1 次。
- 每批成功后把题目和证据写入任务 checkpoint；Worker 重启后能够继续剩余批次。
- Worker 元数据记录当前批次、已完成题数、课程/公开证据数量、检索 warnings 和最终证据摘要。
- 题目列表会展示命题依据统计；旧版 Pydantic 内部错误不再原样暴露给用户。
- 异步请求模型现同时接受字段名和 API 别名，并按 camelCase 持久化，修复 Worker 反序列化失败。

主要代码：

- `backend/app/models/exam.py`
- `backend/app/services/exam_retrieval_service.py`
- `backend/app/services/exam_service.py`
- `backend/app/services/exam_generation_service.py`
- `backend/app/worker/tasks.py`
- `frontend/src/pages/Exams/index.tsx`
- `frontend/src/pages/Exams/components/QuestionTypeSelector.tsx`
- `frontend/src/pages/Exams/components/ExamQuestionList.tsx`

新增可配置项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `EXAM_RETRIEVAL_TIMEOUT_SECONDS` | `30` | 单个课程检索方向的超时上限 |
| `EXAM_BATCH_SIZE` | `4` | 单次模型调用最多生成题数 |
| `EXAM_BATCH_TIMEOUT_SECONDS` | `60` | 单批模型调用超时 |
| `EXAM_BATCH_RETRIES` | `1` | 单批局部重试次数 |

验证情况：

- Wikipedia API 已使用“战略”和“战略的作用”做过真实连通测试；终端中文标题显示乱码只是 PowerShell 输出编码，不是响应内容损坏。
- 旧的失败任务卡片仍保留在数据库中，但不会影响新任务。
- 尚未通过浏览器自动化完成一次真实登录态的完整组卷；浏览器控制插件在连接时出现 `Cannot redefine property: process`。后端契约、检索、批次重试和 Worker 路径已有自动化覆盖。

## 关键代码位置

| 功能 | 文件 |
| --- | --- |
| 配置 | `backend/app/config/settings.py` |
| 模型 HTTP 适配 | `backend/app/providers/openai_compatible.py` |
| MinerU | `backend/app/services/mineru_client.py` |
| 资料处理 | `backend/app/services/material_service.py` |
| LightRAG | `backend/app/services/lightrag_service.py` |
| 混合检索 | `backend/app/services/retrieval_service.py` |
| 练习题证据检索与排序 | `backend/app/services/exam_retrieval_service.py` |
| 练习题生成与校验 | `backend/app/services/exam_service.py` |
| 练习题异步任务创建 | `backend/app/services/exam_generation_service.py` |
| RAG 回答 | `backend/app/services/rag_service.py` |
| Chat API 与学习模式 | `backend/app/api/chat.py` |
| Worker 任务 | `backend/app/worker/tasks.py` |
| Worker 恢复 | `backend/app/worker/recover.py` |
| 前端 API 客户端 | `frontend/src/api/client.ts` |
| AI 学习室 | `frontend/src/pages/AIStudyRoom/index.tsx` |
| 练习题页面 | `frontend/src/pages/Exams/index.tsx` |
| 资料状态页 | `frontend/src/pages/Materials/index.tsx` |
| 前端状态与账号隔离 | `frontend/src/stores/useAppStore.ts` |
| 项目启动器 | `start-project.ps1` |
| Windows Worker | `scripts/dev-worker.ps1` |
| UTF-8 设置 | `scripts/enable-utf8.ps1` |

## 验证结果

最近完成的验证：

```text
Backend full suite: 161 passed
Frontend TypeScript/lint: passed
Frontend production build: passed
Impeccable UI mechanical detector: completed；发现的彩色背景文字对比度警告已修正
Backend /health: ok
Wikipedia public knowledge connectivity: passed
Celery generate_exam registered: yes
Celery ping: pong
```

推荐命令：

```powershell
# 后端完整测试。限定 tests 目录，避免 pytest 误收集缓存目录。
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider

# 前端检查
Set-Location ..\frontend
npm run lint
npm run build

# 服务健康
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health

# Worker 健康
Set-Location ..\backend
.\.venv\Scripts\python.exe -m celery -A app.worker.celery_app:celery_app inspect ping --timeout 5
```

已知非阻塞警告：

- pytest 可能无法写入 `.pytest_cache`，但不影响正式 `tests/` 目录测试。
- Vite 构建提示主 chunk 超过 500 kB，当前不影响功能；后续可做路由级动态导入。
- 浏览器自动化插件曾出现 `Cannot redefine property: process`，属于工具连接问题，不是项目运行错误。

## 当前数据状态

- `Lecture 2.pdf`：资料 `ready`，任务 `succeeded`，160/160 个切片有向量。
- `Lecture 3.pdf`：资料 `ready`，任务 `succeeded`，127/127 个切片有向量。
- 两个文件的 LightRAG 图谱状态为 `failed`，但关键词和向量问答可正常使用。
- 不需要重新上传这两个文件。

## 工作区状态与提交建议

当前改动尚未提交，包含用户原有修改和本轮连续修复。提交前应：

1. 阅读 `git status --short`。
2. 不要提交 `.env`、`.env.worker`、`.run/`、日志、缓存或密钥。
3. 确认是否需要提交用户提供的 `PDF资料/Lecture 2.pdf`；默认不要提交。
4. 可按主题拆分提交：
   - 认证与 UUID 隔离
   - MinerU/Worker 网络与恢复
   - LightRAG 降级
   - 混合检索与真实回答审计
   - UTF-8 与 Windows 启动脚本
5. 提交前重新执行后端测试和前端构建。

## 建议的后续任务

按优先级排序：

1. 使用更多真实问题对 Lecture 2/3 做检索质量评估，并记录 Recall@K/答案引用正确率。
2. 为定义式查询扩展和同页上下文增加更多中英文回归样本。
3. 决定 LightRAG 的长期方案：单独低维 Embedding、替换存储，或正式移除阻塞式图谱建图。
4. 给历史消息补充 `generation` 审计元数据；目前只有新回答即时显示真实性标记。
5. 对前端做路由级代码拆分，解决 Vite 500 kB chunk 警告。
6. 在真实登录态下执行一次专项练习端到端验收：主题“战略的作用”、单选题 10、其他题型 0，并检查课程/公开证据统计。
7. 观察真实公共检索结果的相关性分布；若 Wikipedia 对专业主题覆盖不足，再配置专业 Web Search API 或增加 OpenAlex provider。
8. 整理并提交当前脏工作区，避免后续窗口误覆盖已完成修复。

## 给后续助手的建议提示词

新窗口可直接输入：

> 请先阅读 `C:\Users\xingk\Desktop\Final-Term-main\HANDOFF.md` 和当前 `git status`，保留所有现有改动与密钥安全约束，然后继续处理我的下一项需求。不要重新实现已经完成的 MinerU、Worker、LightRAG 降级、混合检索和练习题分批生成修复。
