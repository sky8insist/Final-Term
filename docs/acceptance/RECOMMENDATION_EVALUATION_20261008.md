# P2 Recommendation Evaluation 验收

日期：2026-10-08。依据技术指南第 12 项；本次完成第一轮技术实现。

## 实现范围

- 数据集：`backend/evals/recommendation_cases.json`，`recommendation-cases-v1`，24 条人工指定策略预期的合成快照。七类输入为课程、Topic、Mastery、覆盖、考试、考试映射、待办；时间固定，不访问数据库/外部模型。
- 分组：cold_start 5、mastery 2、retention 4、exam 3、scope 6、time 1、determinism 3。每条明确可接受 Top-1 ID（空列表表示应暂不推荐），可指定动作类型、首选关键理由、禁选 ID 和 limit。标签表达规则要求，不是推荐器自己生成的答案。
- `recommendation_eval_service.py` 实际调用生产 `build_recommendations`，独立审计理由。审计直接读取快照中的掌握值、assessmentCount、next_review_at、风险元数据、考试日期/状态/权重映射/科目；检查导航 Topic/考试目标，不调用评分或状态投影来验证它们自身。
- 采用已知理由模板的明确匹配规则。新增文案需同步审计器；伪造/未知理由失败。关键理由遗漏单独失败，避免只删除难以验证的理由就获得高 faithfulness。缺少全部理由、重复行动/理由、范围/目标错误与 limit 超限同样失败。
- 反转每类输入顺序再运行并比较完整响应，检查推荐与待办的确定性。此检查不模拟数据库行变化或并发事务。
- `scripts/evaluate_recommendations.py` 支持 `--cases`、`--output`，输出逐条结果与失败原因，有任何策略/审计失败即退出 1。已有 `scripts/run_quality_eval.py` 接入推荐门禁；数据版本错误、无案例、重复 ID、无时区、无效 limit、非法标签/理由码均拒绝。

## 推荐修复

生产算法从 next-action-v1 更新到 **next-action-v2**：

1. 考试映射在权重归一化前核验当前 Topic/考试和同科目关系；归档 Topic、未知关联及跨科目映射不影响加权或考试理由。
2. 闪卡回忆失败即使没有到期时间，也显示“闪卡回忆失败，需要重新评估”；继续保留客观证据要求。
3. 今日待办按 subjectId/id 排序再截断 10 条，避免读取顺序改变首页任务集合。

保持现有 API 字段与前端兼容；没有数据库迁移、前端改动、实际环境配置改动或服务重启。

## 结果与分母

完整报告：`RECOMMENDATION_EVAL_20261008.json`。

| 指标 | 结果 | 定义 |
|---|---|---|
| Top-1 Hit | 22/22 = 1.0 | 有预期首选的案例中，实际首选 ID 在人工可接受集合中 |
| Abstention Accuracy | 2/2 = 1.0 | 预期暂不推荐的案例实际无 actions |
| Reason Faithfulness | 43/43 = 1.0 | 所有返回理由中，可被源快照支持的模板声明比例 |
| Snapshot Scope Consistency | 24/24 = 1.0 | 输出 Topic/课程/考试关联无越界且不含禁选项的案例比例 |
| Determinism | 24/24 = 1.0 | 固定时间下输入反序不改变完整输出的案例比例 |

首选、暂不推荐和理由分母分别统计；没有对应案例/声明时返回 null，避免空集被记为 100%。范围指标是对已归属快照的结构一致性检查，不能证明数据库授权安全。理由指标核验当前元数据声明，不验证上游评分准确性、风险校准或学习效果。

## 验证

- 新增 43 项测试：24 条案例及 19 项审计/门禁反例和标签校验。反例包括错误排序、伪造掌握/到期/误解/回忆风险、错误考试天数/链接、跨科目考试、删去关键风险理由、空理由、越界与重复推荐、不稳定待办。
- 推荐专项 **50 passed, 1 warning**（含既有 7 项）；完整后端 **370 passed, 3 warnings**。警告为既有 FastAPI/HTTPX、Supabase 参数弃用警告。
- Ruff F、统一离线 quality gate 与 git diff --check 通过。
- `scripts/verify_recommendations.py` 仅允许 localhost 的 PostgreSQL/Supabase，数据库连接为只读事务。实际 TestClient 请求使用真实 Supabase 客户端；当前课程 API 200，1 条推荐、1 条理由与直接 SQL 快照一致；匿名 401、limit=0 返回 422、随机其他用户查询该课程返回 404。未写数据库，日志仅输出计数。
- 联调认证采用测试依赖覆盖；这次未执行真实 JWT、浏览器流程或其他课程样本质量评估。如果课程无推荐理由，脚本明确输出该项 N/A。

复跑（仓库根目录 PowerShell）：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/evaluate_recommendations.py --output ../docs/acceptance/RECOMMENDATION_EVAL_20261008.json
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
.\.venv\Scripts\python.exe scripts/verify_recommendations.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
```

## 仍待验收

这是合成规则回归，尚未建立代表性真实学习快照的独立标注/留出集，也未测量推荐采纳率、会话完成率、学习增益或长期记忆收益。不能据此宣称推荐效果达到 100%。未来应由独立标注者定义可接受动作，维护数据版本、历史基线、分组表现与真实实验指标。真实 JWT/浏览器、持续 Worker 链路和前阶段质量验收限制继续有效。

后续按指南推进 P3 Notes / Artifacts；此次已同步更新 HANDOFF.md 与优化进度表。
