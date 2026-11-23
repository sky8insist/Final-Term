# 学习完成率与前瞻 Mastery 校准验收

日期：2026-10-27。接上轮 055 产品审计，继续指南第 24 项的稳定分母和学习质量指标。本轮仅改后端，未新增界面、模型调用或后台定时任务。

## 完成率模块

056 新增 learning_metric_cohorts，按 kind/source_id/revision 唯一保存原始承诺。开始与截止时间固定，截止为开始后 7 天。记录首次完成，即使后来删除源任务或重排，也不重写已建立的分母；科目/账户隐私删除仍级联清理。新表 service_role 仅 SELECT/DELETE，可信触发器负责创建和完成，不开放客户端埋点写结果。

`GET /api/v1/recommendations/learning-outcomes?days=30`，days 为 1–90。cohorts 按类型和算法版本分组，选 starts_at 位于查询窗口且已开始的记录。返回 total、mature、pending、late、completedWithinHorizon、completionRate。只有 deadline 已到的 mature 进入分母，完成也必须不晚于 deadline；未成熟样本即使已经完成仍等待完整窗口，零分母为 null。小于等于 7 天的查询常没有成熟样本，不能解释为 0% 的完成效果。

| kind | 开始与成功定义 | 覆盖边界 |
| --- | --- | --- |
| guided_session | 首次 canonical active 到 completed | 取消/未完成仍保留分母；只创建了 planned 不纳入 |
| plan_task | 新任务原定日期上海零点与创建时间的较晚者开始，首次 completed | 每条任务，不是整个计划成功率；改期不改原始窗口，重生成是新承诺 |
| due_flashcard | 每个新调度版本从到期时间与创建时间较晚者开始，匹配原版本和内容的真实评价完成 | 提前评价也算；again 仅表示完成操作，不能推断已记住；未来安排尚不入查询，旧安排无回填 |
| quiz_remediation | 有版本 Guided 会话首次 quiz<.8，后续更大序号 quiz>=.8 | 会话最多一个分母；重复/重建步骤去重；不包括独立测验，不以阅读补救笔记代替成功 |

步骤重建时已存在 055 step.completed 的完成不重新解释为新失败；旧无版本 Guided 会话不回填补救 cohort。删除卡片/任务后承诺保留为未完成是本指标明确选择，不代表用户仍需要执行已删除内容。该口径用于固定承诺的描述统计，不能冒充当前活动任务完成率或策略的因果效果。

## 前瞻校准模块

- exam_responses 新增 mastery_prediction，BEFORE INSERT 只读本人/同科目/同知识键的 canonical Mastery。有 assessment 证据才保存 score/confidence/assessmentCount、算法版本、知识键、原状态时间和 capturedAt；缺失不使用默认值，客户端所传该列被替换。
- UPDATE 保留原预测，包括历史空快照。修改答案、重答、后续 Mastery 改变和评分均不能替换预测；旧作答不回填。快照是首次保存答案时的状态，不保证是题目首次显示前的状态，也不是题目难度模型预测。
- mastery_prediction_samples 在正式考试 graded 或 adaptive 允许即时发布后保存首次预测与正确性，不需要 learnerConfidence。没有预测/没有 assessment/正确性未知均不入样本，旧样本不反写重算。
- masteryCalibration 按预测来源 algorithmVersion 分组，返回 sampleCount、BrierScore、10 个固定分桶的数量/均分/实际正确率，以及 ECE（各桶绝对偏差按样本数加权）。0–.1、.1–.2 等为左闭右开，最后 .9–1 包含 1。没有样本返回空集合，不伪造 0 分。
- 这里把既有 Mastery score 与实际后续题目正确性进行经验校准诊断。score 尚不是校准过的概率；不同版本/难度/人群/时间的混杂未控制，不能把 Brier 排序或版本差异解释为算法 uplift。校准查询窗口按成绩 released_at，不是首次作答日期；仅覆盖本轮新增且有证据的作答，未计算全体题目的预测覆盖率。

## 实测证据

- 新增 **10 项**后端边界/接口回归，完整后端 **828 passed, 3 warnings**；Ruff F、既有 quality gate、diff 检查通过。无前端代码改动，未重复运行前端构建或宣称新增浏览器验收。
- `scripts/verify_learning_outcomes.py --apply` 在真实本地 PostgreSQL 安装 056；验证固定窗口、未成熟 null、迟完成不计成功、源任务删除后分母保留、步骤删除重建不重复、提前复习与新安排尚未成熟。
- 合成 .2/错误、.8/正确两条在 mastery-v2 组得到 Brier=.04、ECE=.2；另 .8/错误在独立 fixture 版本得到 Brier=.64。首次答案后把 Mastery 改成 .99、伪造 prediction、重答都不改原预测；无 assessment 的 .9 不纳入。正式评分发布前无样本，graded 后只发布一次，adaptive 即时发布另行验证。不需要自报信心。
- 另建 **2,001** 条成熟的 scale-fixture cohort，其中 1,000 条窗口内完成，真实 SQL 和 Supabase API 都返回完整总量，未受默认 1,000 行上限影响。它是聚合正确性检查，不是 P95 或生产规模压测。
- 实际 Supabase API 验证 200/no-store、匿名401、非法窗口422、另一个账号空结果；RLS 隔离及私有 RPC/service_role 更新权限检查通过。认证用依赖覆盖，未验证真实 JWT。
- 055 的真实 SQL/API 验收同步复跑通过。全部数据均属于随机临时用户；时间平移、成绩和完成是合成 fixture，先提交供 API 跨连接读取再按精确用户 ID 清理，并断言 cohort/sample 级联。未写真实用户、未调用模型或付费服务、未改变真实计划或学习状态。合成 7 天时间不等于真实持续观察 7 天。

## 复跑与部署

backend 目录：

```powershell
.\.venv\Scripts\python.exe scripts/verify_learning_outcomes.py
.\.venv\Scripts\python.exe scripts/verify_product_quality.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装/刷新本轮函数用 `verify_learning_outcomes.py --apply`；只允许本地数据库和 Supabase。其他环境按序安装历史迁移（含 055）和 056 后部署后端。不需要新增 Worker/Beat。新表已加入隐私导出，通过科目/账户删除级联；不回填历史。未重启已有服务、未更改实际 .env 或用户技术指南。

## 后续入口

继续第 24 项的独立质量实验/结果比较：reranker uplift、grounding/false-reject、plan relevance 的独立标注与模型评估。整体计划成功率、所有独立测验的补救成效率、预测覆盖率/置信区间/同人对照、指标 UI/审计分页、保留/清理与 P95、真实长期样本仍待补。原推荐及 grounding 离线门禁继续保留，未把它们改称新真实模型实验。
