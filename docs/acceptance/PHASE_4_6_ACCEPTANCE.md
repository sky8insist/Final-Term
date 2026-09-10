# 阶段 4–6 可观测性与真实验收报告

执行日期：2026-08-24（Asia/Shanghai）

## 结论

- 阶段 4 已实现：HTTP、Celery、Worker 恢复任务和模型调用统一传播 `requestId`、`traceId`、`acceptanceRunId`。
- 阶段 4 已实现：材料、检索、考试、复习计划、MinerU 和模型调用输出阶段耗时与状态指标。
- 阶段 4 已实现：验收脚本输出 JSONL、CSV、Markdown，并按 `acceptanceRunId` 聚合。
- 阶段 5 已实现：真实模式硬门槛、真实 Supabase 双账号、真实 PDF、真实 MinerU/Embedding/Chat、异步考试/计划、Golden Questions、隔离、导出和清理。
- 阶段 6 已执行后端真实链路；最终 run 为 `acceptance-20260824T021739-934fed33`，42/47 项通过。
- 前端服务、TypeScript lint 和生产 build 通过；内置浏览器插件初始化失败，因此前端可视化真实登录态为 N/A，不能宣称通过。

## 最终真实结果

| 项目 | 结果 |
| --- | --- |
| Mock / Celery / MinerU 硬门槛 | PASS |
| 真实 Supabase 认证 | PASS |
| 真实 `Lecture 2.pdf` 上传与 ready | PASS |
| MinerU / Embedding / Chat | PASS（真实调用） |
| 双用户学科、资料、历史隔离 | PASS |
| Golden Questions Recall@5 | 18/20，0.90 |
| AI 学习室角色切换与冻结快照 | PASS |
| 闪卡 | PASS |
| 思维导图 | FAIL，连续真实调用返回 502 |
| 异步考试、作答、评分 | PASS |
| 考试 PDF 导出 | PASS |
| 异步复习计划 | PASS，3 个任务 |
| 隐私导出与两个测试账号清理 | PASS |
| Worker 重启恢复 | PASS（真实恢复任务） |
| LightRAG 硬超时降级 | PASS；180 秒后材料保持 ready，LightRAG 标记 failed |
| 前端真实登录态浏览器验收 | N/A；浏览器插件初始化冲突 |

最终报告：

- `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.jsonl`
- `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.csv`
- `backend/data/acceptance/reports/acceptance-20260824T021739-934fed33.md`

## 阶段耗时

最终 run 的已落库样本：

- 检索 complete 平均 658ms；其中 vector 平均 577ms、keyword 平均 15ms。
- 考试生成 32.186s；生成阶段两次记录平均 15.518s。
- 复习计划生成 45.249s；模型 guidance 45.185s。
- 最终 run 共记录 129 个 HTTP 调用、21 个 operation metrics、7 个模型调用。

这些是本次 run 的样本，不是长期 p50/p95。

## 成本说明

SiliconFlow 官方公开价已配置为：

- `deepseek-ai/DeepSeek-V4-Flash`：输入 1 CNY/M tokens，输出 2 CNY/M tokens。
- `Qwen/Qwen3-VL-Embedding-8B`：文本输入 0.7 CNY/M tokens。

最终 run 执行时本地 `.env` 的历史零价覆盖了代码默认值，因此原始报告中的 `0.0 CNY` 无效，应视为 **N/A**。运行后已修正真实 `.env`，并增加正价格预检，后续真实验收若价格为零会直接失败，不再产出错误的零成本。

## 未通过与后续修复

1. Andrews 第 7 页和 Johnson 第 9 页仍未进入 top 5；Recall@5 已达 0.90，但这两条需继续优化块级作者/定义关联。
2. 思维导图连续真实调用返回 502；需要保存 Provider 错误分类和模型原始响应的非敏感摘要后再定位。
3. 前端可视化验收受内置浏览器插件的 `process` 全局重定义冲突阻塞；修复插件后必须补跑真实登录、Dashboard、路由刷新和退出登录。
4. 原始最终报告保留成本 `0.0` 作为当时配置错误的证据，不应对外引用为真实成本。
