# 前六阶段综合验收报告

> 项目：Final-Term-main（AI 学习平台）
> 验收日期：2026-08-24（Asia/Shanghai）
> 基线提交：`2a058b8d511f3d58bf204798d95a747eda8f269a`
> 真实 E2E Run：`acceptance-20260824T021739-934fed33`
> 报告口径：阶段 1–6 既有验收证据 + 当前本地回归复核

## 一、综合结论

**综合验收结论：有条件通过，整改后需重新执行完整验收。**

阶段 1–5 的主要工程目标已经完成，阶段 6 的真实后端 E2E 为 **42/47 通过，通过率 89.36%**。当前补跑的本地自动化回归、静态检查、前端类型检查、生产构建和 OpenAPI 契约检查均通过。

但目前仍不能宣布“最终验收全部通过”，原因如下：

1. 思维导图在真实模型链路中连续返回 `502`，属于核心功能失败。
2. 前端真实登录态浏览器验收未执行完成，不能用 lint/build 代替 UI 运行时验收。
3. Golden Questions 中 Andrews、Johnson 两条未进入 Top 5，作者定义类检索仍不稳定。
4. 最终真实 run 中的 `0.0 CNY` 是价格配置错误，不是有效成本结果。
5. 六阶段改造仍处于未提交工作区，尚未形成可追溯、可回滚的验收版本。

### 当前判定

| 维度 | 结论 | 主要证据 |
| --- | --- | --- |
| 本地质量门禁 | 通过 | 后端 `171 passed, 3 warnings`；Ruff F 类通过；前端 lint/build 通过 |
| API 契约 | 通过 | 62 paths / 75 operations；旧 Workbench 和无前缀业务路由未回归 |
| 真实后端 E2E | 有条件通过 | 42/47；认证、资料、模型、隔离、考试、计划和隐私主链路通过 |
| 检索质量 | 部分通过 | Golden Recall@5 为 18/20，即 0.90 |
| 前端真实浏览器 | 未完成 | 验收浏览器插件初始化冲突，结果为 N/A |
| 成本 | 无有效结论 | `0.0 CNY` 源于历史零价配置，必须视为 N/A |
| 发布建议 | 暂不建议最终签署 | 可进入整改和演示准备，不建议宣称生产级最终验收通过 |

---

## 二、验收依据与证据边界

### 2.1 已参考的验收材料

1. [阶段 1–3 实施与基线报告](./ACCEPTANCE_PLAN.md)
2. [API 验收矩阵](./API_ACCEPTANCE_MATRIX.md)
3. [代码去重与失效代码审计](./DUPLICATION_AUDIT.md)
4. [阶段 4–6 可观测性与真实验收报告](./PHASE_4_6_ACCEPTANCE.md)
5. [Golden Questions 数据集](./golden_questions.json)
6. `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.jsonl`
7. `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.csv`
8. `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.md`
9. 当前工作区代码、Git 状态和本次补跑的本地门禁结果。

### 2.2 本次补跑的检查

| 检查 | 当前结果 |
| --- | --- |
| 后端完整测试 | `171 passed, 3 warnings`，24.29s |
| Ruff F 类 | `All checks passed!` |
| 前端 TypeScript | `npm run lint` 通过 |
| 前端生产构建 | 通过，最大 chunk 509.37 kB，仍有 Vite 警告 |
| 健康检查 | `GET /health` 返回 `status=ok, apiVersion=v1` |
| OpenAPI | 62 paths；无 `/api/workbench`；无 `/subjects`；存在 `/api/v1/subjects` |
| 本地端口 | 5173、8000、18000、8025、6379 当前均可连接 |
| `git diff --check` | 无空白错误；存在 LF→CRLF 提示 |

### 2.3 本次没有重新执行的真实外部操作

本报告编制没有重新运行会创建账号、写入业务数据、消耗模型额度或修改第三方状态的完整真实 E2E。以下内容引用最终 run 的历史证据：

- 真实 Supabase 双账号、真实 PDF、MinerU、Embedding、Chat、异步考试、评分和复习计划。
- 隐私导出、数据清理、Worker 重启恢复和 LightRAG 降级。
- Golden Questions 的 20 条检索结果。

以下项目仍没有完整通过证据：

- 音频验收：最终 run 明确为 N/A，因为没有配置验收音频。
- SMTP 真实投递：本地 Mailpit 可连接不等于真实邮件服务已验收。
- 前端真实登录态：lint/build 通过不等于浏览器运行时通过。
- 长期性能：单次 run 和 21 个 operation metrics 不足以形成 p50/p95/SLA。
- 真实成本：原报告的零成本无效，尚未形成修正后的新 run。

---

## 三、六个阶段逐项验收结论

| 阶段 | 验收目标 | 当前结论 | 完成情况 | 保留问题 |
| --- | --- | --- | --- | --- |
| 阶段 1 | 建立基线 | 通过 | 已记录提交、环境、测试、OpenAPI 和范围边界 | 六阶段成果尚未对应新 commit |
| 阶段 2 | 去重与失效代码清理 | 通过，有历史债 | 重复行率降至 0.71%，失效路由和死代码已清理 | 14 个短克隆、Ruff 全规则历史债、同步上传旧入口 |
| 阶段 3 | API 契约与矩阵 | 通过 | 业务统一 `/api/v1`，OpenAPI 收敛到 62 paths | 前端类型仍为手写，缺少 OpenAPI 自动绑定 |
| 阶段 4 | 可观测性 | 实现通过，样本不足 | request/trace/run ID 已贯通，关键阶段已有指标 | 错误分类过粗，缺少长期分位数和稳定性趋势 |
| 阶段 5 | 真实验收能力建设 | 基本完成 | 双账号、真实资料、模型、异步任务、隔离、隐私已覆盖 | 前端浏览器、音频、SMTP、有效成本证据有缺口 |
| 阶段 6 | 执行真实验收 | 有条件通过 | 42/47；多数核心后端闭环已通过 | 思维导图、检索精度、前端 UI 和成本未闭环 |

### 3.1 阶段 1：基线建立

**结论：通过。**

已记录的历史基线包括：

- 基线提交：`2a058b8d511f3d58bf204798d95a747eda8f269a`。
- 清理前后后端测试均为 170 passed。
- 清理前 OpenAPI 为 147 paths / 177 operations。
- 清理后 OpenAPI 为 62 paths / 75 operations。
- 前端 lint 和生产构建均通过。

本次补跑后端测试为 **171 passed**，比历史文档多 1 条，当前没有本地自动化回归。

**问题：**基线 commit 是改造前版本，六阶段成果仍在脏工作区中。当前报告能够描述成果，但还不能通过 commit 精确复现交付状态。

### 3.2 阶段 2：代码去重和失效代码清理

**结论：通过，但仍有可管理的技术债。**

已完成：

- 删除无前缀业务路由和 `/api/workbench/*` Mock 路由。
- 删除 `/outline/generate`、`/quiz/generate`、`/exams/attempts/*` 等重复入口。
- 删除考试和计划的重复同步 HTTP 生成入口。
- 抽取统一的 generation task 指纹、幂等和任务创建逻辑。
- 删除 4 个旧 agent 占位模块、旧 constants/eval/logger 包装和未使用 GSAP 依赖。
- Knip 清理后为 0 个未使用依赖/导出。
- jscpd 重复行由 133 降为 91，重复行率由 1.01% 降为 0.71%。

保留问题：

- jscpd 仍有 14 个短克隆块。
- Ruff 全规则历史扫描有 214 条，目前只把 F 类设为硬门禁。
- `/api/v1/materials/upload` 同步接口仍被后端处理链路测试依赖。

这些问题暂不构成阶段 2 失败，但应进入后续维护计划。

### 3.3 阶段 3：API 矩阵和契约收敛

**结论：通过。**

当前 API 状态：

- 业务接口统一挂载在 `/api/v1`。
- `/health` 是唯一无版本公开路径。
- OpenAPI 为 62 paths / 75 operations。
- `/api/workbench/*`、无前缀 `/subjects` 和旧考试/计划同步入口均未回归。
- 页面、前端方法、HTTP、Service、数据表和测试已经形成验收矩阵。

**保留问题：**前端请求和响应类型仍由人工维护。TypeScript 编译和接口矩阵可以降低风险，但不能完全避免后端 schema 改动后的运行时契约漂移。

### 3.4 阶段 4：可观测性

**结论：实现通过，运营级证据不足。**

已完成：

- HTTP、Celery、Worker 恢复任务和模型调用传播 `requestId`、`traceId`、`acceptanceRunId`。
- 材料、检索、考试、计划、MinerU 和模型调用记录阶段耗时与状态。
- 验收脚本能够生成 JSONL、CSV 和 Markdown 报告。
- 最终 run 记录 129 个 HTTP 调用、21 个 operation metrics 和 7 个模型调用。

当前指标：

| 指标 | 最终 run 结果 | 解释 |
| --- | ---: | --- |
| 检索 complete 平均耗时 | 658ms | 只有 3 个样本 |
| vector 平均耗时 | 577ms | 只有 3 个样本 |
| keyword 平均耗时 | 15ms | 只有 3 个样本 |
| 考试生成 | 32.186s | 单次真实样本 |
| 复习计划生成 | 45.249s | 单次真实样本 |
| 计划 model guidance | 45.185s | 单次真实样本 |

**问题：**这些数据只能作为单次验收样本，不能表述为长期平均、p50、p95 或 SLA。模型失败主要被压缩为 `timeout` 或 `http_error`，定位粒度不足。

### 3.5 阶段 5：真实验收能力建设

**结论：主体完成。**

验收脚本已经支持：

- 真实模式硬门槛：Mock 关闭、Celery 异步、MinerU 开启。
- 真实 Supabase 双账号。
- 真实 PDF 上传和异步处理。
- 真实 MinerU、Embedding 和 Chat。
- Golden Questions 和 Recall@5。
- 双用户资源和历史隔离。
- AI 学习室角色切换和 Hermes 冻结快照。
- 异步考试、作答、评分和 PDF 导出。
- 异步复习计划。
- 隐私导出和测试账号清理。
- Worker 恢复和 LightRAG 超时降级。

**缺口：**

- 前端 UI 验收依赖内置浏览器插件，没有仓库内独立 E2E 方案。
- 音频没有验收样本。
- SMTP 没有真实投递证据。
- 成本正价格预检虽已修复，但未执行新的完整 run 证明修复闭环。

### 3.6 阶段 6：真实验收执行

**结论：有条件通过。**

最终真实 run：`acceptance-20260824T021739-934fed33`。

- 总检查项：47。
- 通过：42。
- 失败：5。
- 通过率：89.36%。
- Golden Recall@5：18/20，即 0.90。

主要通过项包括：

- 真实模式硬门槛。
- Supabase schema、pgvector、认证和双账号。
- `Lecture 2.pdf` 上传、处理和 ready。
- MinerU、Embedding、Chat 真实调用。
- 双用户学科、资料和历史隔离。
- 跨学科污染保护。
- 学习室角色切换、Hermes 冻结快照和闪卡。
- 异步考试、作答、评分和考试 PDF 导出。
- 自适应复习计划和 3 个间隔任务。
- 隐私导出、测试账号和学习数据清理。
- Worker 重启恢复。
- LightRAG 180 秒超时后降级，材料仍保持 ready。

失败项如下：

| 失败检查 | 直接结果 | 实际归属 |
| --- | --- | --- |
| `retrieval Chandler page` | 专项检索没有按断言命中 Chandler 目标页 | 检索排序或检查口径不一致 |
| `golden strategy-andrews` | 期望第 7 页；实际为 1、4、23、33、34 | 检索排序 |
| `golden strategy-johnson` | 期望第 9 页；实际为 3、25、26、27、29 | 检索排序 |
| `mind map` | 连续真实调用返回 502 | Provider、JSON 返回或结构校验链路 |
| `artifacts` | 要求思维导图与闪卡均成功，因思维导图失败而失败 | 汇总依赖，不是独立根因 |

因此，5 个失败检查可归并为：

1. 检索定向召回问题。
2. 思维导图生成问题。
3. artifacts 汇总检查被思维导图连带失败。

前端真实浏览器验收不在上述 5 个失败项内，而是单独标记为 N/A。

---

## 四、当前运行和交付状态

| 项目 | 当前状态 | 风险说明 |
| --- | --- | --- |
| Backend | 在线，`/health` 通过 | 只证明当前进程可达 |
| Frontend | 5173 端口在线 | 未完成真实登录态 UI 验收 |
| Supabase | 18000 端口在线 | 本次没有重新执行双账号真实验收 |
| Mailpit | 8025 端口在线 | 不等于生产 SMTP 已通过 |
| Redis | 6379 端口在线 | 本次没有重新注入 Redis 故障 |
| 本地回归 | 171 passed | 不等于真实外部链路全部通过 |
| 前端构建 | 通过 | 最大 chunk 仍超过 500 kB |
| Git 工作区 | 脏 | 59 个已跟踪文件有差异，另有未跟踪交付物 |

端口在线、健康检查通过、单元测试通过和真实 E2E 通过是不同层次的证据，不能相互替代。

---

## 五、问题清单、具体位置和整改方案

### ISSUE-01：思维导图真实生成失败

- **优先级：P0，阻断最终验收。**
- **验收证据：**最终 run 中 `mind map` 连续真实调用返回 `502 Bad Gateway`，`artifacts` 汇总检查被连带判为失败。
- **问题位置：**
  - `backend/app/mindmap/service.py:97–134`
  - `backend/app/services/llm_service.py:34–51`
- **当前代码行为：**思维导图最多尝试两次；超时返回 504；`LLMServiceError` 或结构校验错误最终统一返回 502。LLM 层把 Provider HTTP 异常统一记录为 `http_error`。
- **问题影响：**思维导图是核心学习产物。真实模型出现异常时，用户得到整体失败，演示和生产流程都可能中断。
- **当前能确定的原因：**故障发生在真实模型调用、JSON 返回或结构校验链路。
- **当前不能确定的原因：**现有报告无法区分 Provider 原始 502、返回体格式错误、JSON 修复失败、节点结构不合法或两次重试重复收到同类错误。

建议优化：

1. 记录 `providerStatus`、`providerRequestId`、`errorClass`、`responseContentType` 和截断脱敏后的响应摘要。
2. 将“网络/Provider 重试”和“JSON/结构修复重试”拆开，分别计数和记录。
3. 使用 Provider 支持的 JSON schema 或结构化输出能力，降低格式漂移。
4. 两次尝试必须在同一个 `acceptanceRunId` 和 trace 下可关联。
5. 为思维导图增加独立 operation metrics，而不是只记录通用模型调用。

替代方案：

- 短期切换到已经验证能稳定返回 JSON 的备用模型。
- 使用检索结果先生成确定性的基础层级树，再让模型只负责标题归并和润色。
- Provider 不可用时返回可编辑的基础导图，并提示用户稍后重新增强，而不是整体返回 502。
- 将思维导图改为异步任务，允许重试、状态查询和失败恢复。

复验标准：

- 连续真实生成 10 次，成功率至少 95%。
- 每次均通过唯一根节点、无环、节点可达、引用有效等结构校验。
- 失败日志能够明确定位到 Provider、JSON、结构校验或超时类别。
- 完整 47 项真实 E2E 中 `mind map` 和 `artifacts` 均通过。

### ISSUE-02：前端真实登录态验收缺失

- **优先级：P0，阻断最终验收。**
- **验收证据：**阶段 4–6 报告将前端真实登录、Dashboard、路由刷新和退出登录标记为 N/A。
- **阻塞位置：**内置浏览器插件出现 `process` 全局重定义冲突。
- **问题性质：**目前确认的是验收工具链失败，不足以直接证明 `frontend/src` 产品代码存在缺陷；但也不能据此宣称产品 UI 已通过。
- **问题影响：**无法确认浏览器运行时鉴权恢复、账号隔离缓存、刷新路由、错误态、加载态和退出登录是否正确。

建议优化：

1. 在仓库内增加 Playwright E2E，不再依赖单一浏览器插件。
2. 使用两个真实测试账号覆盖登录、Dashboard、资料、学习室、思维导图、考试、计划、刷新和退出。
3. 验证账号 A 的 localStorage、当前学科和缓存不会泄露给账号 B。
4. 保留 screenshot、trace、video 和失败时的网络请求证据。

替代方案：

- 如果短期无法引入 Playwright，可使用 Chrome/Edge 按固定清单人工验收。
- 人工验收必须保留屏幕录制、关键截图和 HAR，且由第二人复核。

复验标准：

- Chrome 和 Edge 至少各完整执行 1 次。
- 核心 UI 流程全部通过。
- 刷新后会话和路由恢复正确。
- 退出登录后受保护页面不可继续访问。
- 两个账号的本地状态和服务端数据均隔离。

### ISSUE-03：作者定义类检索召回不稳定

- **优先级：P1。**
- **验收证据：**Golden Recall@5 为 18/20；Andrews 第 7 页和 Johnson 第 9 页未进入 Top 5。
- **附加异常：**Chandler 的 Golden 检查因为返回第 33 页而通过，但独立的 `retrieval Chandler page` 检查失败，说明专项检查和 Golden 检查的查询、topK 或断言口径可能不一致。
- **问题位置：**
  - `backend/app/services/retrieval_service.py:35–80`
  - `backend/app/services/retrieval_service.py:216–320`
  - `backend/app/services/lightrag_service.py` 中 rerank 当前关闭
- **当前算法：**定义类关键词扩展、精简查询、关键词候选、向量候选和基于排名的 RRF；最终按 `rrfScore` 排序后截取 topK。
- **问题原因：**RRF 主要使用候选排名，不利用作者名精确匹配、定义句式、标题块、同页关系或二阶段语义重排。同页上下文扩展发生在 topK 截断后，无法挽救没有进入候选前列的目标页。
- **问题影响：**回答可能引用综述页或相邻页面，而不是用户指定作者的原始定义页，影响引用可信度。

建议优化：

1. 将候选池扩大到最终 topK 的 4–10 倍，再执行二阶段重排。
2. 对 `作者名 + definition/define/定义` 精确匹配增加权重。
3. 将标题块、作者名块和同页正文聚合为页级候选。
4. 对相邻页建立滑动窗口，处理标题和定义分布在不同页的情况。
5. 引入轻量 cross-encoder 或 LLM rerank，但必须设置硬超时和降级。
6. 统一 Chandler 专项检查与 Golden Questions 的 API、topK、数据集和断言口径。

替代方案：

- 不增加模型时，使用 PostgreSQL FTS/BM25 + trigram 作者名匹配，并与向量分数归一化融合。
- 为讲义建立“作者—定义—页码”结构化索引，定义类查询优先查结构化索引。
- 将目标页面的标题、作者和定义作为 metadata 写入向量索引。

复验标准：

- 20 个 Golden Questions 的 Recall@5 至少达到 19/20。
- Andrews、Johnson 和 Chandler 三个作者定义用例必须全部命中目标页。
- 跨学科污染仍为 0。
- 引入 rerank 后检索 p95 不超过项目约定阈值。

### ISSUE-04：真实成本证据无效

- **优先级：P1。**
- **验收证据：**最终 run 报告显示 `0.0 CNY`，阶段 4–6 报告已确认这是本地 `.env` 历史零价覆盖造成的错误，应视为 N/A。
- **问题位置：**
  - `backend/app/config/settings.py:106–111`
  - `backend/app/services/observability_service.py:78–95`
  - `backend/scripts/e2e_acceptance.py` 的报告聚合
- **当前状态：**默认价格和正价格预检已经修复，但还没有新的完整 run 证明修复有效。
- **附加风险：**部分变量仍使用 `estimated_cost_usd` 命名，而报告币种为 CNY，容易产生语义混淆。
- **问题影响：**不能评估单次验收、单用户或各功能的成本，也不能验证预算门禁是否按真实币种生效。

建议优化：

1. 统一成本字段为 `amount`、`currency`、`pricingVersion`、`provider`、`model`、`estimated`。
2. 同时保存 input tokens、output tokens 和 Provider usage 原始值。
3. 报告显示原币种；需要换算时单独记录汇率来源和时间。
4. 抽样与 Provider 账单对账。

替代方案：

- Provider 不返回稳定 usage 时，使用本地 tokenizer 估算，并标记 `estimated=true`。
- 发布验收以 Provider 账单为最终成本依据，应用内估算仅用于预警。

复验标准：

- 在正价格预检下完成新的整轮真实 run。
- 所有模型调用均有 token 和成本记录。
- 报告总额与逐调用求和一致。
- 抽样对 Provider 账单误差处于项目约定范围内。

### ISSUE-05：六阶段成果尚未形成可追溯提交

- **优先级：P1。**
- **验收证据：**当前 `git diff` 涉及 59 个已跟踪文件，另有 generation service、migration、docs 等未跟踪文件；基线提交仍是改造前提交。
- **问题位置：**版本管理和交付流程。
- **问题影响：**容易误覆盖或丢失修改，无法准确回滚，也无法从新环境复现报告对应版本。

建议优化：

1. 冻结当前快照。
2. 按 API 收敛、generation 重构、可观测性/E2E、文档四个主题提交。
3. 每个提交前后执行对应测试门禁。
4. 完整真实验收通过后创建 annotated tag，并在报告中记录 tag、commit 和 run ID。

替代方案：

- 如果暂时不拆分，至少创建一个受控提交，附带完整变更清单和 acceptance run ID。

复验标准：

- 工作区 clean。
- 报告对应唯一 commit SHA/tag。
- 从新克隆环境可以重新运行本地门禁并定位对应真实报告。

### ISSUE-06：验收文档存在时序矛盾

- **优先级：P1。**
- **验收证据：**`ACCEPTANCE_PLAN.md` 和 `HANDOFF.md` 主体仍写“真实 E2E 未执行”，但 `HANDOFF.md` 末尾追加内容又说明阶段 4–6 已执行 42/47。
- **问题位置：**
  - `docs/acceptance/ACCEPTANCE_PLAN.md`
  - `HANDOFF.md`
  - `docs/acceptance/PHASE_4_6_ACCEPTANCE.md`
- **问题影响：**维护者可能得出相反结论，错误宣称“尚未验收”或“已经全部通过”。

建议优化：

1. 将 `ACCEPTANCE_PLAN.md` 明确标注为“阶段 1–3 历史报告”。
2. 将 `HANDOFF.md` 顶部改为当前综合结论，历史内容放入“历史记录”。
3. 以本报告作为统一验收索引。
4. 每个数字必须标记日期、commit 和 acceptanceRunId。

替代方案：

- 保留历史文档不改，但在 README 增加文档优先级：综合报告 > 阶段 4–6 > 阶段 1–3。

复验标准：

- 新维护者只读验收首页即可得到一致的当前结论、失败项、N/A 项、commit 和 run ID。

### ISSUE-07：前端主 chunk 超过 500 kB

- **优先级：P2。**
- **验收证据：**当前生产构建最大 chunk 为 509.37 kB，gzip 150.58 kB，Vite 持续告警。
- **问题位置：**`frontend/src/App.tsx` 已使用路由级 `lazy()`；实际大包更可能来自共享 vendor 或公共依赖，需通过 bundle analyzer 定位。
- **问题影响：**可能影响弱网和低性能设备的首次加载；目前没有真实 LCP/INP 数据证明影响程度。

建议优化：

1. 引入 bundle 可视化工具，确定最大 chunk 的依赖组成。
2. 使用 `manualChunks` 拆分 React/vendor、图表、编辑器、PDF 等重依赖。
3. 只在特定页面使用的库改为页面内动态导入。
4. 建立首次 JS、LCP 和 INP 性能预算。

替代方案：

- 如果真实 LCP 和网络传输已经满足目标，可以提高 `chunkSizeWarningLimit`，但必须有性能证据，不能仅隐藏警告。

复验标准：

- 不再出现 >500 kB 警告；或在书面豁免下，LCP/INP/首次 JS 传输均达到预算。

### ISSUE-08：LightRAG 高维向量索引能力受限

- **优先级：P2。**
- **验收证据：**历史真实结果显示当前 Embedding 为 4096 维，超过 PostgreSQL pgvector HNSW 2000 维限制；LightRAG 标记 failed，但关键词和向量主链路继续可用。
- **问题位置：**
  - `backend/app/services/lightrag_service.py`
  - 当前 Embedding 模型 `Qwen/Qwen3-VL-Embedding-8B`
- **当前保护：**LightRAG 有 180 秒硬超时，并且不再阻塞材料 ready。
- **问题影响：**图检索增强不可用，后台可能持续消耗资源，但不会阻塞核心资料处理。

建议优化：

- 为 LightRAG 单独使用 1024 或 1536 维 embedding。
- 采用可评估的降维方案，验证质量后再启用 HNSW。

替代方案：

- 使用支持高维 ANN 的独立向量库。
- 暂时关闭 LightRAG，只保留 keyword + pgvector，并让产品能力声明与实际一致。

复验标准：

- LightRAG 索引成功率、查询成功率和降级率可观测。
- LightRAG 失败仍不影响材料 ready。
- Golden 质量和延迟达到项目门槛。

### ISSUE-09：测试和静态规则维护债

- **优先级：P2。**
- **验收证据：**当前 pytest 有 3 条弃用警告；Ruff 全规则历史为 214 条；同步 `/materials/upload` 仍被测试依赖。
- **具体位置：**
  - Starlette TestClient/httpx2 迁移警告。
  - Supabase client `timeout`/`verify` 弃用参数。
  - Ruff 项目规则配置。
  - 材料同步接口测试层级。
- **问题影响：**短期不阻塞功能，但依赖升级后可能变为失败；规则噪声会掩盖新增问题。

建议优化：

1. 固定工具版本并制定升级窗口。
2. 建立正式 Ruff 配置，按规则类别逐步清零。
3. 升级 TestClient 和 Supabase client 初始化方式。
4. 将同步上传处理测试下沉到 service 层，再删除旧 HTTP 接口。

替代方案：

- 建立 warning/ruff baseline，只允许数量下降，不允许新增。

复验标准：

- pytest 0 warning。
- 目标 Ruff 规则集全绿。
- `/materials/upload` 删除，service 测试继续覆盖处理逻辑。

---

## 六、整改优先级和建议排期

| 优先级 | 建议周期 | 工作包 | 主要产出 |
| --- | --- | --- | --- |
| P0 | 1–2 天 | 思维导图诊断、重试和降级 | Provider 错误可分类；备用或确定性导图可用 |
| P0 | 1–2 天 | 前端独立 E2E | Playwright 或可审计的人工浏览器证据 |
| P1 | 2–4 天 | 检索候选扩展和二阶段重排 | Andrews/Johnson/Chandler 全过，Recall@5 ≥0.95 |
| P1 | 1 天 | 成本重跑 | 有效 token、价格版本和成本报告 |
| P1 | 1 天 | 文档统一、提交和 tag | clean commit/tag 与 run ID 对应 |
| P2 | 3–5 天 | 包体、LightRAG、warning 和 Ruff 债 | 长期性能与维护门禁 |

建议处理顺序：

1. 先修思维导图的诊断能力，否则无法确认 502 的真实原因。
2. 同时建立独立前端 E2E，解除工具插件单点依赖。
3. 修检索并统一 Chandler 专项检查与 Golden 口径。
4. 修复后先跑专项，再跑完整真实 E2E。
5. 用新 run 验证成本。
6. 最后冻结 commit/tag 并更新综合报告。

---

## 七、第二轮验收方案

### 7.1 本地门禁

必须全部通过后才能进入真实验收：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe -m py_compile scripts\e2e_acceptance.py

Set-Location ..\frontend
npm run lint
npm run build
```

同时检查：

- OpenAPI 仍为唯一 `/api/v1` 契约。
- migration 027 已应用且不重复重放历史迁移。
- `MOCK_EXTERNAL_APIS=false`。
- `CELERY_TASK_ALWAYS_EAGER=false`。
- `ENABLE_MINERU=true`。
- 模型和 Embedding 单价均为正数。

### 7.2 专项真实复验

先快速确认修复方向：

1. 思维导图连续真实生成 10 次。
2. Andrews、Johnson、Chandler 三类定义问题。
3. 成本和 token 记录。
4. 前端真实登录、刷新、退出和双账号本地状态隔离。

专项通过只说明修复方向正确，不能作为最终签署依据。

### 7.3 完整真实复验

专项通过后，必须重新运行完整 47 项真实 E2E：

- 不允许只重跑失败步骤后手工修改结论。
- 必须生成新的 `acceptanceRunId`。
- 必须重新生成 JSONL、CSV 和 Markdown 报告。
- 必须保留 Provider/模型/价格版本、数据集版本和 commit SHA。
- 必须再次执行双账号清理和隐私检查。

### 7.4 前端 UI 复验

至少覆盖：

- 注册或登录。
- Dashboard 数据加载。
- 当前学科选择和账号隔离。
- 资料上传、任务状态和资料列表。
- AI 学习室问答和引用。
- 思维导图生成与失败提示。
- 考试生成、作答和提交。
- 计划生成和今日任务。
- 页面刷新和深链接恢复。
- 退出登录和受保护路由。

### 7.5 故障注入复验

建议重新验证：

- Worker 重启。
- Redis 暂时不可用。
- MinerU 超时或失败。
- Chat/Embedding Provider 超时、429、5xx 和非法 JSON。
- LightRAG 超时。
- 重复任务投递和幂等恢复。
- 预算不足或价格配置错误。

---

## 八、最终验收门禁

| 最终门禁 | 当前状态 | 最终通过条件 |
| --- | --- | --- |
| 本地回归 | 已满足 | pytest、lint/build、Ruff/OpenAPI 持续全绿 |
| 思维导图 | 未满足 | 连续真实生成达到成功率和结构校验标准 |
| 前端真实流程 | 未满足 | 浏览器证据覆盖核心流程和双账号隔离 |
| 检索质量 | 未完全满足 | Andrews/Johnson/Chandler 全过，Recall@5 ≥0.95 |
| 成本 | 未满足 | 新 run 产出有效、可解释的真实成本 |
| 长期性能 | 未满足 | 明确 p50/p95 或性能预算，不再用单次均值代替 |
| 版本可追溯 | 未满足 | clean commit/tag 与验收 run 一一对应 |

### 最终签署建议

当前建议签署级别：

> **有条件通过 / 整改后复验**

只有在以下条件同时满足后，才能升级为“最终验收通过”：

1. ISSUE-01 和 ISSUE-02 两个 P0 问题关闭。
2. 检索关键用例和 Recall@5 达到门槛。
3. 产出有效成本证据。
4. 完整 47 项真实 E2E 重新执行并全部达到约定标准。
5. 前端真实浏览器验收通过。
6. 验收结果绑定 clean commit/tag。

---

## 附录 A：关键数字汇总

| 指标 | 结果 | 备注 |
| --- | ---: | --- |
| 真实 E2E | 42/47 | 通过率 89.36% |
| 失败检查 | 5 | 归并为检索、思维导图及汇总依赖 |
| Golden Recall@5 | 18/20 | 0.90 |
| 当前后端测试 | 171 passed | 3 warnings |
| OpenAPI | 62 paths / 75 operations | 契约收敛后 |
| HTTP 调用 | 129 | 最终真实 run |
| operation metrics | 21 | 最终真实 run |
| 模型调用 | 7 | 最终真实 run |
| 输入 token | 1,181 | 最终真实 run |
| 输出 token | 2,460 | 最终真实 run |
| 有效成本 | N/A | 原 0.0 CNY 无效 |
| 前端最大 chunk | 509.37 kB | gzip 150.58 kB |
| jscpd 重复行率 | 0.71% | 清理后 |

## 附录 B：结论口径

- **通过：**有直接、可复核的通过证据。
- **有条件通过：**主链路基本可用，但存在必须整改的失败或关键证据缺口。
- **未通过：**已有直接失败证据。
- **N/A / 未完成：**没有执行或因工具阻塞，不能推导为通过。
- **历史证据：**来自指定 acceptanceRunId，不代表本次重新调用了外部服务。
