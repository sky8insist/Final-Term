# Worker 学习事件验收 — 2026-10-22

本轮在完成 Dayend 界面/历史/自动调度后，继续指南第 22 节的学习事件闭环。不增加 Agent，不调用模型。

## 事件与任务

053 增加 learning_domain_events（schema v1、类型、来源表/ID/修订、发生时间、消费回执）与 learning_projection_versions，并复用 052 的持久任务队列。六类事件由真实业务表变化或漏做补扫产生：资料 ready、考试 graded、掌握记录实际变化、卡片复习日志、考试目标/映射变化、任务漏做。原始业务写入、事件、outbox 同事务；业务回滚时三者一起回滚。来源事件去重，不将 payload 当作知识或学习评估事实。

Worker 只接收任务 ID，SKIP LOCKED 领取、2 分钟租约与 claim token 防止旧 Worker 发布；消费回执、版本推进、按需 dirty 标记和任务成功确认同事务。重复消息不会重复改变已消费事件。Signals/Recommendations 仍按 canonical 数据读取计算，投影版本为后续 Workspace 精准失效准备，尚未替换所有缓存。

重排沿用 Study Plan v3 和每 5 分钟 Beat，保留自动重排设置、受保护任务、考试范围及跨科目容量。30 秒安静窗口配合 replan_dirty_since，使同次 dirty 在 2 分钟后可执行，不因持续事件无限延期；实际执行频率/批大小仍依赖既有 Beat。消费本身不直接重建完整计划。

任务最多 5 次退避失败后 dead；本人可查询最近 50 项任务，并最多手动重试 3 轮。非 dead 不重试，日终过期或关闭不重试。复盘页有当天失败报告的重试入口。只保存异常类别。新表认证只读、RPC 服务角色专用，复合归属外键/RLS/隐私导出与科目/账户级联。

## 验证结果

| 检查 | 结果 |
|---|---|
| 本模块新增单测 | 10 passed |
| 本次两个模块新增 | 21 passed |
| 完整后端 | 785 passed，3 项既有依赖弃用警告 |
| Ruff F / quality gate / diff | 通过 |
| 前端 lint/build | 通过，最大 chunk 251.02 kB |
| SQL 回滚验收 | 六类事件、原子 outbox、源事务回滚、漏做去重、消费回执/epoch 三次不重复、防抖/最长等待、有限手动重试、归属/RLS/私有 RPC/级联通过 |
| 实际 Supabase 任务状态只读 API | 200 / 无权或缺失科目 404 / 匿名 401，测试认证覆盖 |

052 自动调度和 051 改期脚本在新触发器存在时也重新通过。前端构建遇 esbuild EPERM 后按已授权构建命令重跑通过。UI 静态检查范围与说明见 Dayend 自动化验收，不新增视觉方向。

## 真实隔离 Worker 验证

`verify_learning_worker_live.py` 使用实际本地 Redis、独立命名队列、solo Celery Worker 和真实 Supabase RPC。新建临时用户/科目与测试记录，各向队列发送同一事件任务、同一自动报告任务 3 次：

- 事件结果 succeeded / skipped / skipped；projection version 最终为 1。
- 报告结果 succeeded / skipped / skipped；数据库只有一份 pending 报告，没有计划任务新增或自动确认。
- 退出时清理临时用户及级联数据、6 个 task results 和独立命名队列。现有业务队列未被该 Worker 监听。

这是真实传输/执行/RPC 验证，不是 eager 模拟或仅 mock。没有真实用户写入、模型或付费调用。它不证明持续 Beat、跨午夜、多个分布式 Worker、真实 JWT/浏览器和长期效果；原 Dayend 独立模型质量评审仍 N/A。

## 复跑与部署

backend 目录：

```powershell
.\.venv\Scripts\python.exe scripts/verify_learning_events.py --api
.\.venv\Scripts\python.exe scripts/verify_daily_review_automation.py --api
.\.venv\Scripts\python.exe scripts/verify_daily_reviews.py --api
.\.venv\Scripts\python.exe scripts/verify_learning_worker_live.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

前三个 SQL 脚本的临时数据均回滚；真实 Worker 脚本需要提交可见的临时用户，结束按精确随机 ID 清理。所有脚本拒绝远端依赖。仅本地初装/刷新对应迁移用 `--apply`。

部署顺序为历史依赖 → 052 → 053 → API/前端/Worker 代码，重启 Worker/Beat 加载每分钟 sweep_learning_jobs。本次未重启既有服务、未改实际 `.env` 或用户指南，也未替真实用户开启自动生成。下一阶段 Workspace Cache。

## 剩余范围

原 ingestion 尚未整体迁移到租约/outbox/checkpoint；全部模块取消栅栏、事件保留/清理策略、缓存版本消费、持续 Beat/跨日/分布式并发、真实浏览器和产品效果仍待补。不要把本轮事件和日终任务的恢复保证外推到所有旧任务。
