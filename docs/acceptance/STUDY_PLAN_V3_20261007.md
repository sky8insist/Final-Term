# Study Plan v3 第一轮验收（2026-10-07）

- 支持考试目标（日期、Topic 范围/权重、大纲关联快照）、手动目标日期、Asia/Shanghai 排程、三种显式模式和逐日可用分钟。0 分钟表示当天不新增任务，最长一年。
- CRAM 缩短单次活动并优先高需复习分数，STANDARD 安排基础学习与间隔复习，COMPREHENSIVE 加入已掌握知识点的全面巩固并增加单次时长。非全面模式排除尚未到期的 Mastered，At Risk 提高优先级。
- 仅权威活动 Topic 进入任务；考试模式范围外 Topic 不排程，归档知识点不重新引入。综合模拟是课程级任务，无虚构 Topic。任务原因、范围权重、配置和算法版本保存。
- 排程先扣除受保护任务容量；已完成、手动编辑、锁定任务保留。超额/超出日期范围明确提示，不覆盖用户安排。锁定可单独解除，不把任务永久转为手动来源。
- 原子 RPC 同一事务替换未保护的自动任务，校验计划版本与所有者；失败保留旧计划。新计划并发创建通过学科锁和版本检查拒绝重复。
- 评估/覆盖/课程结构/考试目标与范围/大纲/资料 ready/任务状态变更持久化重排信号、版本和原因。Celery Beat 每 300 秒取最多 20 个待重排或有未完成过期自动任务的计划，确定性重排，无自动模型调用。关闭 autoReplan 的计划不进入候选；UI 支持即时重排与记录查看。
- 普通生成仍复用异步生成任务；LLM 只增强任务方法/完成标准，不改变日期或预算。增强写入排除手动/锁定/已完成任务，父计划写回校验版本。Dayend 时间调整与 sprint 入口保留现有目标配置。
- 修复真实 API 验收发现的冷启动信心字段缺失。

验证：计划 v3 与原排程专项最初 20 passed，冷启动回归随后补齐；最终全量 **287 passed, 3 warnings**，Ruff F、前端 lint/build 通过，最大 chunk 250.07 kB。036 本地已安装；真实 PostgreSQL 验证原子替换、三类任务保护、失败回滚、旧版本拒绝、变更/逾期候选、调整事件与 RLS，通过且测试数据全回滚。真实本地 Supabase + TestClient 的会话列表、计划 overview、三种模式 preview 均通过，跨用户列表/预览均 404；使用认证依赖覆盖，不替代真实 JWT/浏览器 E2E。

限制：自动调度代码与候选事务已验证，尚未运行持续 Beat→Worker→真实用户状态变更 E2E。服务需重启加载代码，另启动 Beat；既有 v2 计划需生成一次 v3 才开启自动重排。考试当天/过去日期不自动生成新计划，需更新目标；无范围考试及范围全归档拒绝排程。跨科目共享时间预算、日历同步、自动大纲解析、任务手动排序、用户日级时区配置待后续模块。最短自动任务 15–45 分钟，碎片容量不足时提示未覆盖，不假装完成。学习建议和模式参数尚未做推荐质量/学习效果评测。

UI 检查：新增流程沿用既有 slate/blue 界面。静态 impeccable 检查 Guided 未报问题；考试/计划有 6 条颜色告警，涉及条件样式和嵌套白色输入等，尚未通过浏览器计算样式确认。当前无可调用浏览器工具，截图、键盘交互和实际对比度验收为 N/A。

运行：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m celery -A app.worker.celery_app:celery_app worker --pool=solo --loglevel=info
# 在另一终端运行；同一环境仅启用一个 Beat。
.\.venv\Scripts\python.exe -m celery -A app.worker.celery_app:celery_app beat --loglevel=info
.\.venv\Scripts\python.exe scripts/verify_learning_sessions.py
.\.venv\Scripts\python.exe scripts/verify_study_plan_v3.py --api
```

迁移依赖：026、029–037；仅应用缺失迁移，不重放所有历史 SQL。本地发现缺少 026，本次已补安装；037 限制任务凭据和学习事件的直接写入，互动表仍完全禁止 authenticated 直读，避免评价答案暴露。
