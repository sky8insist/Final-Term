# Observability / Quality Evaluation 产品审计首轮验收

日期：2026-10-27。承接 Workspace Cache，落实技术指南第 24 项的可追踪产品事件与首轮指标。

## 实现与口径

- 055 新增 recommendation_audits/product_events，RLS 本人只读、复合科目/Topic 归属、科目/账户级联、隐私导出。service_role 只读/插入/删除，显式撤销默认 UPDATE 权限；函数仅可信服务执行。没有后台补造历史数据，没有把埋点送入 Memory 或模型。
- `GET /api/v1/recommendations/next-actions?audit=true` 批量原子保存投递快照后返回 recommendationId；省略 audit 保持原有只读服务/评估调用。快照包含 rank/generatedAt、实际参与规则计算的 inputSignals、scoreComponents、priorityScore、reasons、原 href、算法版本和 trace。多表读取仍沿用现有推荐服务，快照表示计算所用输入，不承诺数据库多表读取是单一隔离级别快照。
- `POST /api/v1/recommendations/{id}/feedback` 只允许 impression/clicked，额外属性拒绝；服务端时钟、本人范围、7 天有效期和每投递每事件一次。首页卡片至少 50% 交叉且页面可见才上报曝光，Observer 不可用不伪造；请求推荐不等于看见，点击不等于采纳。网络失败可能漏报，刷新建议是新投递，不是跨所有访问合并为同一 Topic。
- Guided context 保存 recommendationId；服务端创建事务验证同人/科目/Topic/有效期，URL 改 Topic 后前端不继承关联。真正确认学习进入 active 才记采纳，完成后保存 canonical before/after；不是点击即学习成功。已关联的会话可在投递 7 天后完成，反馈/新建关联的 7 天门槛不抹除该历史。
- canonical 触发器记录 step.completed、mastery.changed、plan.replanned、task.completed、adaptive.stopped、grade.calibrated。原子事务回滚不留统计；同步骤 ID 重建不重复，任务反复切换完成只算一次，每次自适应 resume 周期可各有一次停止。Mastery 新行 before/delta 缺失，不假设初值；已有值更新保存真实前后差。已知版本从现有 lastEvidence/strategy/context 取，旧数据标 legacy-unversioned，不能据此补猜历史算法。
- 正式考试未发布的评分不写校准事件，graded 时原子补入一次；adaptive 沿用即时成绩规则。没有学习者信心或正确性未知时不纳入校准。
- `/api/v1/recommendations/{id}/audit` 返回快照和最近 100 条关联事件，带 hasMore；不是无限历史列表。所有推荐 API 成功响应 no-store，权威推荐不进入 Workspace fallback。

## 指标查询

`GET /api/v1/recommendations/quality-metrics?days=7`，1–90 天。数据库侧聚合全部匹配行，不依赖 PostgREST 默认返回行数。

| 字段 | 分母与限制 |
| --- | --- |
| recommendationCohorts | 按投递时间窗口和推荐 algorithmVersion 分组，观察到 asOf；不是按曝光日期另建 cohort |
| delivered / impressions / clicks | 不同投递 ID 的数量；曝光/点击为客户端报告，clicks 可含未成功上报曝光的投递 |
| exposedClicks / clickThroughRate | 已曝光且点击数 / 已曝光数 |
| accepted / acceptanceRate | 已曝光且存在 canonical session.accepted 的投递数 / 已曝光数；一个推荐多个会话仍只计一次 |
| completed / completionRate | 已曝光且存在 completed 的投递数 / 其中已采纳投递数；不是全部 Guided 会话完成率 |
| sessionMasteryGain | 窗口内完成会话的 before/after 都有 assessmentCount>0 才纳入；样本数与平均百分点差，不证明因果/长期保持 |
| learnerConfidenceCalibration | 已发布评分的自报 confidence 与 is_correct 的平均平方差（Brier），样本数独立返回；不是 Mastery 预测校准 |
| eventCounts | 窗口内各类新事件计数；不能冒充重排率、计划/到期复习完成率或补救成效率 |

零分母与无样本均为 null，计数为 0 或空集合；不显示为 0% 的效果结论。新迁移之前的事件没有回填，因此当前窗口可能只有部分覆盖。策略变化、已删除 Topic/科目/账号、漏报及未成熟 cohort 都会影响结果；正式实验仍需固定观测期限和一致样本定义。

## 验证结果

- 完整后端 **818 passed, 3 warnings**，新增 13 项覆盖审计冻结/原函数不变、持久化失败不返回 ID、缺数据不写事件、权限错误映射、禁止客户端伪造结果/时间、窗口与认证边界。
- Node **25 passed**，其中本轮 6 项验证交叉比例、后台页、重复通知、失败后再通知重试、卸载和无 Observer；另外 19 项为上一阶段缓存回归。首次沙箱 spawn EPERM 后按测试权限重跑。它们使用模拟 Observer，不替代真实浏览器。
- Ruff F、quality gate、前端 lint/build、diff 检查通过；最大 chunk **254.55 kB**。既有离线质量门禁继续通过，包括 24 条推荐与 18 条 grounding 规则样例；这些不是新增真实模型实验。
- 真实 PostgreSQL + Supabase/API：无曝光的投递、三次反馈去重、实际创建/确认 Guided、空统计、缺基线、404/401/422、错 Topic/过期关联、Mastery .2→.7 为 +50 点、合成完成结果、步骤/任务去重、两轮自适应停止、重排、正式评分发布后 Brier .64、私有 RPC/RLS/本人可读与跨用户不可读、角色 UPDATE 权限、事务回滚均通过。
- 验收脚本仅允许本地 DB/Supabase；提交随机临时用户供 API 跨连接读取，结束后按精确 ID 删除并验证两表级联。合成学习完成/停止/评分只在回滚事务中验证口径；没有执行模型生成或真实学习，没有真实用户业务写入。身份使用依赖覆盖，不是 JWT E2E。
- UI 静态检测的 4 条提示来自原 Dashboard 同一行不同嵌套元素的配色，代码核对无新增配色/布局问题；无可调用浏览器工具，没有声明真实渲染/键盘/多端曝光验收。

## 复跑和部署

backend 目录依次运行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_product_quality.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装或刷新函数/索引用 `scripts/verify_product_quality.py --apply`；脚本不删除既有表或业务用户。其他环境先按序安装历史迁移和 055，再部署 API/前端。前端目录运行 `node --test tests/recommendationExposure.test.mjs tests/versionedCache.test.mjs`、`npm run lint`、`npm run build`。无新增 Worker/Beat 配置，本轮未重启已有服务、未更改实际 .env 或用户指南。

## 下次续作

继续第 24 项：稳定 cohort 的 Guided/Plan/Due Review 完成率、Quiz remediation 成效率、真正的 Mastery calibration/分桶与算法版本比较；独立真实标注/模型的 reranker uplift、grounding/false-reject、plan relevance 实验。再补指标页面、审计分页、持续采集与保留/清理策略、规模/P95 和真实浏览器验收。第一轮审计链路完成不等于指南全部指标或线上质量已达标。
