# 卡片级间隔复习验收（2026-10-08）

## 交付范围

- 038 新增规范化 flashcards、flashcard_review_state、flashcard_review_logs；旧卡组回填不改原 JSON/更新时间。卡片 ID 在卡组内稳定，旧无 ID 卡使用 legacy-N。
- Again / Hard / Good / Easy 独立调度；difficulty、stability、last_review、next_review、review_count、lapse_count、内容版本与提交版本持久化。
- `GET /api/v1/flashcards/queue` 支持本人全部科目汇总、科目/卡组筛选及未来卡片；同一 SQL 快照计算 counts 和候选，最多 200 条，hasMore 用多读一条判断。逾期为曾复习且早于北京时间今日的到期卡片；到期数包含未首次复习的新卡。
- 首页分科目到期入口、侧栏 `/flashcards`、先回忆再揭示答案、四档评价、当前安排、最近 50 条复习历史和空/失败状态。Guided 共用复习组件并从服务器恢复进度。
- RPC 原子提交卡片、Mastery、mastery_history、learning_events 与复习收据。携带请求 UUID/版本的重试返回原收据；不同评价复用编号或旧版本返回 409；网络失败保留待确认编号，只允许重试相同评价。旧客户端兼容，但未传 requestId 不保证跨重试幂等。
- 编辑卡面/答案/Topic 或恢复移除卡片会重置状态并增加版本，旧历史保留；归档 Topic / 移除卡片不进入活动队列，旧评价不能完成新内容。
- 自评不增加 assessmentCount/评估置信度。曾掌握 Topic 的 Again 保留回忆风险、清零客观评估正确连续次数，需要三个连续正确客观评估才解除；其他闪卡评价不能解除。已有 Plan v3 的 Mastery 变更触发器可标记重排。
- 新表仅 owner SELECT，服务 RPC 不授予 authenticated；导出纳入三表，科目删除级联。

## 验证证据

- `cd backend; .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`：303 passed，3 个既有依赖弃用警告。
- `python -m ruff check app tests scripts --select F` 通过；前端 `npm run lint`、`npm run build` 通过，最大 chunk 250.65 kB。
- 本地 `scripts/verify_flashcards.py --apply --api` 安装 038；后续 `--api` 验证全部通过。实际测试了卡 A Again 与卡 B Easy 的不同到期、另一张卡状态不变、收据重放不增加 Mastery/events、旧卡/掌握版本回滚、内容编辑只重置对应卡/保留历史、移除/归档排除、owner 只读 RLS、跨用户隔离与服务 RPC 授权。全部临时验收行事务回滚。
- 实际 Supabase + TestClient 的汇总/科目到期/未来队列 200，跨用户科目访问 404；此处使用认证依赖覆盖。
- 最初沙箱无法连接本地 PostgreSQL、阻止 esbuild 子进程；经授权运行成功。直接 pytest 根目录收集遇到既有缓存临时目录权限问题，最终明确收集 tests 并关闭缓存，完整回归通过。

## 保留限制

- `card-scheduler-v1` 为有界启发式算法，Again 首次 10 分钟、Good 首次 1 天、Easy 首次 4 天；不是 FSRS，也未声称已完成长期记忆实验或个体参数学习。
- 缺少 ID 的历史卡按序号标识；重新排序旧无 ID 卡可能改变对应关系，内容差异会重置状态。新生成卡有 ID。
- 历史 Topic 级闪卡评价不能可靠还原每张卡，未伪造回填；旧卡首次进入独立队列时视为未复习。
- 未执行真实 JWT / 浏览器端流程、AI 学习质量、持续 Worker/Beat 自动重排 E2E；当前业务日界线固定 Asia/Shanghai。
- 当前模块完成第一轮实现与技术验收，指南其余 P2/P3 仍按进度表继续。
