# 当前项目验收报告

**验收日期：**2026-09-13（Asia/Shanghai）
**结论：**有条件通过（本地技术交付）；**不满足生产级最终验收**。

本报告是当前状态索引。历史真实外部服务证据保留其原始日期；本轮未重放的项目
明确标为“历史证据”或“未完成”，不从本地自动化结果推断通过。

## 本轮本地门禁

| 门禁 | 结果 | 可复核证据 |
| --- | --- | --- |
| 后端完整回归 | 通过 | `209 passed, 3 warnings`，22.02s |
| 后端静态未定义符号检查 | 通过 | `ruff check app tests scripts --select F` |
| OpenAPI 契约 | 通过 | 66 paths；`/api/v1/subjects`、`/api/v3/runs/stream` 存在；Workbench 路由不存在 |
| 前端类型检查 | 通过 | `npm run lint` |
| 前端生产构建 | 通过 | `npm run build`；手动 vendor 分包后最大 JS chunk 246.83 kB，gzip 78.64 kB，无 >500 kB 警告 |
| 本地 Supabase | 通过 | 数据库、Auth、Kong、Storage、Realtime 等容器均 healthy |
| PostgreSQL Dayend 持久化 | 通过（本地） | `028` 表存在；跨进程 checkpoint resume、JSONB 业务投影恢复及 PostgreSQL 启动器已验证 |
| 工作区可追溯性 | 未通过 | 工作区仍有未提交的代码、测试、迁移与文档变更 |

本轮真实完整 E2E：`acceptance-20260913T205814-live`，**43/46 通过**。真实
资料上传、MinerU/向量化、认证与隔离、Chat、Artifacts、考试/评分、计划、隐私导出和
清理均通过；报告保存在本地 `.run/`，不提交。

三条后端 warning 均为依赖弃用警告（Starlette/httpx 与 Supabase client 的
`timeout`、`verify` 参数），本轮未造成测试失败。

## Dayend V3 验收

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 多智能体运行时与真实结构化调用 | 通过（历史真实证据） | 七个 Agent、Mixed、Critic revision 与 SQLite HITL 已有真实调用记录 |
| V3 权限隔离与 SSE 语义 | 通过（历史真实证据） | owner 读取为 200，其他账户读取/resume 为 404；中断不会误发 `run_completed` |
| PostgreSQL 持久化和恢复 | 通过（本地） | 迁移 028、Windows Selector 兼容、跨进程恢复已复验 |
| A/B/C 运行批次 | 通过（运行时） | 300/300 成功；不代表人工质量结论 |
| A/B/C 人工质量与货币成本 | N/A / 未完成 | 无法取得两位独立评审 JSONL；不得由自动评分、协调者评分或推断替代 |
| Activity Drawer 与 HITL 浏览器 UI | 未完成 | 当前没有可用的浏览器控制会话，未取得真实确认/resume 渲染证据 |

## 全项目未完成或未达到门槛

| 优先级 | 项目 | 当前状态 / 完成条件 |
| --- | --- | --- |
| P0 | 前端真实浏览器验收 | 未完成：需验证登录、刷新/深链接、账户隔离、资料流程、考试/计划和 Dayend HITL 确认/恢复 |
| P1 | A/B/C 独立质量评估 | N/A：需两位独立评审返回基于 `review_id` 的 JSONL，才能合并并发布质量指标；本交付已明确豁免，不阻断技术交付但阻断质量声明 |
| P1 | 成本证据 | 未完成：历史 `0.0 CNY` 无效；需要新的真实 provider 用量、正价格版本及可解释成本报告 |
| P1 | 完整真实 E2E 复验 | 部分通过：2026-09-13 真实 run 为 43/46；三项检索检查失败，不能标为全绿 |
| P1 | 思维导图真实调用 | 已完成：2026-09-13 真实 E2E 中 mind map 与 flashcards 均生成成功 |
| P1 | 检索质量 | 未达到门槛：本轮 Golden Recall@5 仍为 18/20（0.90），目标为至少 19/20；Andrews/Johnson 未命中目标页，Chandler 直查检查失败 |
| P1 | 版本可追溯性 | 未完成：需要将当前修改按主题提交、再次运行门禁并将验收证据绑定唯一 commit/tag |
| P2 | 前端包体 | 已完成：将 React、Supabase、Markdown 和流程图库拆分为独立 vendor chunk；最大 chunk 246.83 kB，无 >500 kB 构建警告 |
| P2 | LightRAG 图索引 | 未完成：历史 4096 维 embedding 与 pgvector HNSW 维度限制不兼容；关键词和向量主链可用，但图索引仍不可用 |
| P2 | 长期性能 | 未完成：缺少 p50/p95、LCP/INP 与性能预算证据 |
| P2 | 弃用告警与旧同步入口 | 未完成：需处理 3 条 pytest 弃用告警，并在 service 层覆盖后删除 `/api/v1/materials/upload` 同步兼容入口 |
| P2 | 音频、SMTP 与故障注入 | 未完成：本轮音频为 N/A（未配置验收音频）；仍缺少真实邮件投递及 Redis/Worker/MinerU/模型/LightRAG 故障注入复验 |

## 交付边界

可以声明：本地后端、前端构建、API 约束、Dayend PostgreSQL 持久化恢复和已记录的
多智能体运行时证据通过，适合技术演示和后续迭代。

不得声明：完整真实 E2E、浏览器 UI、A/B/C 人工质量、真实成本、性能门槛或生产级
最终验收通过。

## 建议收尾顺序

1. 在可用浏览器环境完成真实 UI 与 Dayend HITL 验收。
2. 修复检索门槛后，完整重跑真实 E2E 并采集成本。
3. 拆分前端包体，处理弃用告警和同步上传兼容入口。
4. 运行全部门禁，提交干净 commit 并创建验收 tag。
5. 若未来获得独立评审 JSONL，再补发 A/B/C 人工质量报告；在此之前维持 N/A。
