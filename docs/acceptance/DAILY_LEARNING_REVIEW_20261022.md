# Dayend 学习复盘首轮验收 — 2026-10-22

本轮为指南第 21 节新增课程学习复盘服务。使用确定性 LangGraph closure → planning → critic，读取实际业务记录，不增加模型 Agent。原自由文本 Dayend 图与独立模型评审保留，原 N/A 结论不变。

## 数据与输出

- 上海时区当天完成任务、当天提交且当前已评分的测验计数、学习事件计数、未归档稳定 Topic 状态、明日任务和考试。没有把用户口述或 Memory 当成事实输入。
- Mastery delta 为当天最后历史值减去当天开始前最后历史值，输出百分点、前后值和 history evidenceId；基线缺失返回 null。当前学习状态另从 knowledge_mastery/coverage 复用 learner-state-v1，不将覆盖等同掌握。仅已评估低分或 at_risk 列为未解决问题。
- 建议优先进入薄弱 Topic 的 Guided Session；最多选择 3 个符合条件的未完成 system 任务移到明日。人工/锁定/已完成/跳过任务、归档 Topic、截止日期不允许的计划与唯一任务槽位冲突均不成为正常候选。
- critic 使用全科目活动计划共享日预算，检查来源、重复和分钟数。缺失容量不提出改期；已有超额明确提示。分钟数为任务预算，不代表实际学习时长。

## 持久化与确认

051 新表保存来源和报告快照、请求 ID、状态与版本，认证只读、服务角色执行 RPC，复合外键/RLS/隐私导出及科目删除级联。

读取/生成报告不需要确认。仅计划改期是明确确认的变更：确认前重新检查完整来源快照与版本，锁定共享日历，再调用既有日历改期函数复核容量、任务保护和计划范围。整批在同一事务中执行，任何一步失败全部回滚；成功锁定任务并记录 calendar_moved 与 daily_review_applied（reviewId）事件。请求与决定重放幂等，反向决定冲突。不修改 Mastery、coverage、Memory，不自动新增任务或考试目标。

API 均位于 `/api/v1/daily-reviews`：只读 `/preview?subject_id=…`、POST subjectId/requestId、GET /{id}、POST /{id}/decision（version/严格布尔 approve）。客户端不能提交报告或原始学习状态。新复盘仅支持当天，已存报告是历史快照。

## 验证

| 检查 | 结果 |
|---|---|
| 新增单测 | 23 passed |
| 完整后端 | 764 passed，3 项既有依赖弃用警告 |
| Ruff F / 离线 quality gate / diff 检查 | 通过 |
| 真实本地 PostgreSQL 回滚验收 | 通过 |
| 实际 Supabase 只读预览 API | 200 / 无权或缺失科目 404 / 匿名 401 |

单测覆盖百分点正负/零/缺失基线、未评估不伪造薄弱、Mastered 排除、共享/未知/超额预算、伪造与重复提案、同槽位去重/数量上限/确定性、RPC 错误、API 身份与输入拒绝、原报告重放。

SQL 固定数据验证 +12 个百分点与薄弱 Topic、跨科目 80 分钟占用和剩余容量、保护任务过滤、请求/确认幂等、过期快照与版本/归属拒绝、第一项已执行后第二项失败整批回滚、确认改期锁定/审计事件、拒绝与 Mastery 不变、RLS/私有 RPC/级联。所有临时用户、学习数据、计划和复盘回滚。实际 API 使用测试认证覆盖，只读既有数据，未改真实用户计划。

## 复跑与部署

在 backend 执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_daily_reviews.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次缺失 051 或刷新函数可加 `--apply`，脚本拒绝远端数据库。其他环境先装历史依赖和 051，再部署 API。本轮无新增 Worker/Beat 任务，无前端变更，未重启既有服务、修改实际 `.env` 或用户技术指南。

## 限制

这是服务端首轮，尚无新前端入口、日终自动调度、历史日期重建、任意任务生成或完整日程重排。原自由文本图尚未迁移与收敛非核心分支。没有真实模型/付费服务、真实 JWT/浏览器、多进程并发或长期学习效果验收，原 Dayend 独立模型质量评审仍 N/A。下一阶段 Worker / Async Task 的学习事件投递和恢复边界。
