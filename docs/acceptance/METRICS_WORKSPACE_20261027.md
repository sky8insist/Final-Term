# 学习记录、审计分页与覆盖率验收

日期：2026-10-27。承接第24项离线对照工具，补齐此前明确保留的指标界面、审计历史分页与预测覆盖率。

**补验结论：** 本页面已完成本地Edge/Chrome各11项真实浏览器与正常密码/JWT验收，并修复关闭详情丢失焦点。详细失败→修复→确认过程、报告/截图和未覆盖范围见 [真实浏览器验收](METRICS_BROWSER_20261027.md)。下方原SQL/API测试仍按其原身份覆盖方式记录，不与真实JWT混为一谈。

## 学习记录页面

- 全局 `/learning-metrics`，侧栏“学习记录”，无需选择科目。继承原蓝白 Operate 工作台，采用可横向键盘滚动的表格、原生展开区域和分组阅读导航，没有新视觉体系或模型生成界面。
- 窗口7/30/90天，默认30天；展示7天观察窗的已开始/成熟/观察中/按时/迟完成、覆盖率及缺失原因、按版本Brier/ECE/分桶、推荐投递/曝光/点击/采纳/完成、会话掌握度变化和学习者自信Brier。数值与后端定义一致，零分母/缺数据为“—”，不是0%；缺评估基线不显示默认.5。
- 推荐历史不受上方统计窗口影响。选择记录后可看原始理由、优先级、信号/分项/版本与后续行动，URL保留recommendationId，支持关闭详情和浏览器返回；显式查看后焦点移入详情标题。没有直接执行历史旧推荐导航。
- 三个指标请求独立处理失败，窗口切换清除旧结果；历史与行动追加分页去重，pending防重入。刷新/账号/记录切换时请求代次失效，旧响应或finally不会覆盖新读取；MainLayout已有账号key重挂载保护仍生效。读取不走Workspace fallback，不产生成绩、推荐曝光或重排。
- 页面明确区分任务完成和整体计划成功、闪卡操作和记住、推荐点击和实际确认采纳、观察中和成熟、原始点击总数和已曝光点击率；覆盖率启用范围与更早校准样本范围也有说明。

## 历史分页模块

| API | 行为 |
| --- | --- |
| GET /api/v1/recommendations/history | 默认20条，返回items/hasMore/nextCursor |
| GET /api/v1/recommendations/{id}/audit | 原snapshot/events结构保留，默认100条事件，增加nextCursor；前端每页30条 |

两者limit范围1–100，按created_at和id双降序读取limit+1，以最后已交付行生成游标。同时间UUID排序确保下一页完整；较新的并发插入不会插入旧页，刷新后读取。它不是整个历史的隔离级别快照，隐私删除/并发更新可能使后续页减少。

游标含版本、当前本人及列表/推荐范围、时刻和ID，长度最多1024；只接受带时区的日期/合法UUID，规范化后才进入PostgREST筛选。坏游标/跨账号或范围422，非本人详情404。游标是位置，不是授权凭证，每次查询仍带认证user_id。成功响应no-store。

## 覆盖率模块

057新增mastery_prediction_coverage与索引、私有采集触发器和prediction_coverage_metrics。按首次评分发布记录一行，不回填已发布旧评分；未来新发布的正式成绩可包含较早作答，按发布时刻入统计。adaptive仅对当前新评分记录，下一题不会顺带补造该attempt的旧行。

`GET /api/v1/recommendations/prediction-coverage?days=30`，范围1–90：

- releasedGrades：本窗口新记录的首次发布评分。
- knownOutcomes：正确性明确的评分，覆盖率分母。
- predictionSamples：正确性明确且作答保存了首次Mastery预测，分子。
- missingPrediction：正确性明确但缺预测，按noResponse/noSnapshot细分。
- unknownOutcomes：正确性未知，不进入覆盖率分母。
- coverageRate：predictionSamples/knownOutcomes；没有分母为null。

正式考试未graded不记录；重复发布去重。预测和缺失情况按首次发布固定，后续补作答不改写这条历史。只有057后新采集的发布记录，所以不能把这里的数量直接等同056已有calibration样本数。没有补造历史发布时间或宣称全历史覆盖率。

表本人RLS只读、service_role仅SELECT/DELETE，采集函数/指标RPC不对匿名或authenticated开放；纳入隐私导出，科目/账户删除级联。没有新增Worker、Beat或模型调用。

## 验证证据

- 新增 **21项后端**验证游标类型/范围/注入保护、时区规范化、lookahead、最后交付位置、接口边界/身份/空值。完整 **886 passed, 3 warnings**，Ruff F和quality gate通过。
- 新增 **8项前端Node**验证null/NaN/Infinity和观测零的区别、百分点/比率、缺assessment基线、追加顺序/去重、刷新后迟到响应/finally被拒绝。三组共 **33 passed**。
- 前端lint/build通过；最大chunk **255.61 kB**，新学习记录独立chunk **18.34 kB**。Node/esbuild首次沙箱spawn EPERM后按测试/构建权限重跑成功；完整pytest按已授权环境处理此前临时目录限制。
- 原阶段UI静态检查：新页面无剩余提示；MainLayout原退出按钮互斥hover配色经核对保留。当时未有浏览器证据；现已通过独立真实Edge/Chrome补验，关闭详情焦点回退已修复。多设备、其他内核和其他业务页面仍未覆盖。
- **真实本地PostgreSQL/Supabase/API**：同一时间5条推荐及5条事件按2条分三页，UUID顺序完整/无重复；首读取后新增较新记录不混入后续页；history游标不能用于详情/其他账号，坏游标422，另账号空历史/详情404，匿名401，no-store通过。
- 覆盖SQL：正式发布前零条且比例null；4条发布中3条正确性明确、1条有预测，比例1/3；缺作答/缺快照/未知各1。重复发布不新增，模拟未采集旧adaptive评分后，新题不会回填旧行。RLS/私有写权限、API当前统计与账号隔离通过。055/056真实SQL/API回归也通过。
- 脚本只允许本地DB/Supabase。fixture使用随机临时用户，提交供API跨连接读取后精确删除，并断言覆盖/推荐/事件级联；成绩与行动是合成测试，不是真人学习效果。API身份用依赖覆盖，不是真实JWT。未改真实用户数据、实际.env或用户指南，未重启既有服务。

## 复跑与部署

backend：

```powershell
.\.venv\Scripts\python.exe scripts/verify_metrics_workspace.py
.\.venv\Scripts\python.exe scripts/verify_product_quality.py
.\.venv\Scripts\python.exe scripts/verify_learning_outcomes.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装/刷新057用 `verify_metrics_workspace.py --apply`。其他环境按历史迁移后安装057，再部署API与前端；不需要新增Worker/Beat。前端：

```powershell
node --test tests/learningMetrics.test.mjs tests/recommendationExposure.test.mjs tests/versionedCache.test.mjs
npm run lint
npm run build
```

## 后续入口

可继续Security/Privacy专项及指标/审计保留策略。学习记录本地浏览器/JWT已由补验完成；整体计划成功率、独立测验补救、真实独立标签/模型采集、同人分组/长期效果、其他业务浏览器/生产JWT/多设备与P95仍待补。直接Auth管理员删除带数据测试账号的500也列入专项，测试SQL清理不代替产品删除流程。
