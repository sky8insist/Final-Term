# 项目交接文档

## 2026-10-27 — 材料摄取恢复、持久补投与发布保护（当前入口）

- 承接上一轮优先级，完成三个模块：**任务持久补投/原子领取**、**解析与向量检查点**、**canonical发布栅栏和协作IO互斥**。新增并本地安装 `060_material_ingestion_jobs.sql`；运维见 `docs/MATERIAL_INGESTION_JOBS.md`，验收见 `docs/acceptance/MATERIAL_INGESTION_JOBS_20261027.md`，报告/哈希位于 `docs/acceptance/material_ingestion_jobs_20261027/`。进度表和验收索引同步，保留外部服务/长期运行未完成范围。
- **模块一：投递/租约。** Storage上传后，私有register_material_upload事务登记原件manifest和任务，processing_tasks自身作为持久outbox。broker失败不再将任务置failed，而是queued/dispatch_pending/attempts=0，每分钟Beat补扫最多50条。Worker用数据库领取、2分钟租约/30秒心跳、新token与有界attempts；崩溃租约到期可重领，重复/旧令牌不能执行或续租。旧recover对材料只补投，不再重置running/attempts或偷活跃租约；其他生成任务不宣称已迁移。手动重试沿用046归属、状态和原件检查。
- **模块二：检查点。** parsed保存结构/安全扫描及ContentBlock校验后的内容，embedded保存父子块和向量；版本绑定原件hash/模型/chunk/解析配置/mock开关，改变不复用。单份最多20MiB。真实本地TXT+确定性假向量验收中，注入发布失败后两份检查点保留，重试parse=1/embed=1，避免重复付费阶段。成功、原件manifest删除或任务/科目/账户删除时移除检查点，私有表纳入本人隐私导出。模型返回与检查点提交之间中断仍可能重复调用，不声称计费exactly-once。
- **模块三：发布/取消。** 块/父子分块/向量/图状态/material.ready/task.succeeded/检查点清理在同一SQL发布事务核验当前租约和token，含scope/数量/维度校验与安全事件。真实SQL故障注入证明向量等全部回滚；成功只发1条material.indexed。取消原子撤销token，晚到发布、保存检查点或失败写回都不能覆盖。图失败继续关键词/向量fallback，章节和上传Notes在核心成功后可选执行；warning保留，trace/预算上下文绑定本人并恢复调用方上下文，MinerU进度metadata不被后处理覆盖。
- 异步/旧同步上传、摄取、产品隐私清理/账号删除、科目删除及附件清理共用owner级事务advisory锁，跨IO保持、嵌套复用、非阻塞。竞争API返回409，Worker busy且不领取/增加attempts，附件清理跳过；取消仍可即时撤销令牌。同owner不同材料也串行，是保守吞吐取舍。锁只约束新代码合作路径；不保证直接管理员/手工SQL/旧Worker，亦不保证现有LightRAG超时后台线程的所有迟到写入都已隔离，外部图/Storage不与SQL原子提交。
- **验证：新增8项回归，完整后端922 passed，3个既有弃用警告；最终相关模块85项通过，Ruff F/离线quality gate/diff通过。** 真实本地DB/Storage/Redis/独立solo Worker 10项通过，success=true/cleanup=true。解析实际TXT，向量明确为3维替身，图明确故障注入，不调用付费模型/MinerU/ASR/真实LightRAG。两真实线程验证活跃IO期间隐私删除409、Worker busy、清理不触碰真实对象；单元锁为显式替身，不冒充生产锁验收。前端未变，无浏览器/普通JWT/生产验收。
- 首轮10项业务检查通过但finally重复Storage清理ReadTimeout，未写完整报告；initial-report.json从捕获输出重建并保留success=false/cleanup=false，不造运行计数。已核验精确2个临时Auth身份并清理，脚本改为先提交测试DDL清理、启动即落盘owner清单、清理失败仍写报告并清DB。最终确认清理自己的2个账号/2个文件/3个结果/独立队列；首轮中断前3个结果按既有TTL留存，不冒充已精确清除；本验收命名空间的遗留空队列绑定亦精确清理，不动现有业务队列/结果。
- 复跑：backend下 `.\.venv\Scripts\python.exe scripts/verify_material_ingestion_jobs.py`（仅首次本地装060加--apply）；`.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_ingestion_full`；`scripts/run_quality_eval.py`。**部署必须暂停投递并停止/排空旧材料Worker，安装至060后同时部署API/Worker，再重启Beat并恢复投递，不能混用旧无租约代码**。本轮未改实际.env或技术指南、未重启既有业务服务；059自动清理仍默认关闭。
- **下一阶段保留摄取剩余边界：Storage上传至登记前的孤儿补偿、图超时后台写入与跨服务清理、持续Beat/多主机/长任务/压力。** 原始二进制打包、服务日志/备份/SQLite保留、完整安全矩阵仍待补；剩余产品指标/其他页面浏览器/真实模型及长期质量继续按进度表，不把本轮核心恢复机制当全项目完成。

## 2026-10-27 — 数据保留与清理可靠性（历史阶段）

- 承接隐私阶段，完成两个模块：**关系数据保留/预览/去重保护**与**附件租约/退避/恢复**。新增并本地安装 `059_data_retention.sql`，运维文档 `docs/DATA_RETENTION.md`，验收 `docs/acceptance/DATA_RETENTION_20261027.md`，报告/哈希 `docs/acceptance/data_retention_20261027/`；进度表和验收索引同步。只用新建临时账号，不对真实用户执行清理。
- **模块一：保留策略。** 审计/产品事件默认180天，cohort deadline/预测样本/覆盖记录365天，已消费领域事件180天，配置最短120天，覆盖现有最多90天指标及7天成熟窗口。新私有RPC每类默认200/最多1000条，支持dry-run与精确owner范围，事务/行锁/SKIP LOCKED分批处理。领域事件只有已消费且无相关未成功projection任务才清理，未消费/排队/运行/死信继续保留；未清权威成绩、Mastery、计划或canonical转录正文。
- 删除正文时同事务记录最小SHA256去重凭据，保留owner/subject/类别/时间，六类BEFORE INSERT按原来源键阻止旧数据重放，不能靠生成新UUID复活已清事件/样本/outbox。旧已完成低分测验步骤恢复另查指纹，避免清完step.completed后误生成补救cohort。凭据不是匿名数据：本人隐私导出包含它，058隐私清理及科目/账号级联均删除它；直接authenticated读取/写入和公开清理RPC均不允许。凭据与已完成任务回执仍保留至明确删除，长期规模是待办。
- **模块二：附件可靠性。** 使用既有expires_at（现有默认90天，含音频原件/派生片段/MinerU附件）；null/未来期限不清理，不回填历史日期。ready/failed且无在途摄取/转录才可领取5分钟租约，token/哈希/期限在外部删除前及确认时核验。Storage失败保留manifest、只存异常类别并退避，首次120秒/封顶24小时；删除成功但DB确认丢失时租约到期重领，重复删除缺失对象安全。配置桶与本人路径限制，异常路径不触碰Storage。
- **自动清理默认关闭。** 新 `DATA_RETENTION_ENABLED=false`；原cleanup_expired_assets调度改为每小时且也受此开关控制，所以默认会暂停旧的每日附件删除。已补.env.example，**未修改实际.env、未为真实用户开启、未重启既有Worker/Beat**。私有运维脚本 `run_data_retention.py` 默认预览；明确 `--execute` 才执行，可加 `--user-id` 限定owner，手动执行不依赖调度开关。
- **验证：新增15项回归，完整后端914 passed，3个既有弃用警告；Ruff F、离线quality gate、diff通过。** 真实本地SQL/Storage/Redis/隔离solo Celery共10项通过、success=true/cleanup=true。两条实际DB连接领取互斥；故障注入确认清理和凭据原子回滚；旧六类来源重放不复活；真实Storage先删文件再模拟确认丢失，隔离Worker三次投递分别移除1/1/0，未来和在途文件仍能下载。其余失败/旧token/续期/不安全路径有回归。没有模型、ASR、LightRAG、浏览器或普通用户JWT验收；本轮是服务角色运维入口。
- 首轮报告保留：9项均通过但脚本错误预期10项，因此initial-report.json的success=false；补齐第10项旧步骤恢复检查并稳定夹具选择后最终10/10。临时SQL触发器回滚无残留；最终清理生成的2个用户、4个Storage对象、本人Redis键、3个任务结果和唯一队列，不消费既有业务队列。新增索引已本地安装，尚未测全库规模/P95。
- 复跑：backend下 `.\.venv\Scripts\python.exe scripts/verify_data_retention.py`（首次安装加 `--apply`）；`.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_retention_full`；`scripts/run_quality_eval.py`。部署先历史迁移至059，再部署API/Worker，按运维文档显式启用并重启Worker/Beat。前端未变，不重复构建/浏览器；现有真实用户策略不变更。
- **下一阶段优先摄取与任务可靠性：通用checkpoint/outbox/claim与上传/Worker发布栅栏**。本轮执行前核验并不能消除与并发上传/重试的跨服务时间窗口；孤儿Storage/真实LightRAG、原始二进制打包导出、持续Beat/多主机/压力、模型/安全/操作及服务日志/备份/SQLite副本保留策略仍待补。整体计划成功率、独立测验补救、其他页面浏览器与真实质量按进度表继续，不宣称全指南完成。

## 2026-10-27 — 账号删除与隐私完整性（历史阶段）

- 按上轮优先级完成三个后端模块：**Auth删除500修复、关系JSON完整导出、事务清理/失败恢复与旧JWT失效**。新增并本地安装 `058_privacy_integrity.sql`；验收见 `docs/acceptance/PRIVACY_INTEGRITY_20261027.md`，机器报告及源码哈希位于 `docs/acceptance/privacy_integrity_20261027/`。进度表和验收索引同步，隐私整体仍标为部分完成。
- **模块一：500根因与修复。** 上轮本地Auth日志为42501，级联删除触发 `mark_study_plan_changed` 时Auth数据库角色不能更新study_plans。该触发器及Memory删除失效快照触发器改为固定search_path的SECURITY DEFINER并撤销公开调用，不扩大Auth角色业务表权限。加入完整考试夹具后再现23503：旧RESTRICT外键的检查早于兄弟级联；普通NO ACTION复验仍失败，最终五条旧约束改为NO ACTION DEFERRABLE INITIALLY DEFERRED，在提交时核验。实际Auth管理员删除含Topic/Memory/考试关联的临时账号成功，单独删除仍被引用的题目继续受约束保护。不能把Auth管理员删除当完整隐私入口：旧Dayend文本ID和Storage不自动级联。
- **模块二：导出。** 旧逐表一页读取且异常填空会静默丢数据，改用仅service_role可调的STABLE `export_privacy_bundle`：一致语句快照聚合public本人user_id表，兼容旧text字段，并补profiles、考试章节/关联/题目版本。实际导出79表、1,005条事件，两个正常登录账号数据隔离；失败503不返回部分结果，响应no-store。新增子表无user_id仍须人工维护父链规则。当前是关系数据/文件manifest JSON，**不含原始二进制文件、Auth秘密、日志或备份**，大JSON内存/超时/P95仍待验收。
- **模块三：删除/恢复。** 索引和Storage清单分页读到空页、文件每批100；failed/indexing索引也纳入，缺失维度时明确失败并保留关系数据。外部清理全部成功后调用私有 `delete_privacy_learning_data`，考试依赖有序删除、科目级联、全局/旧Dayend/安全审计等清理与缓存代次撤销处于单事务。SQL故障注入已确认科目/考试整批回滚，临时触发器整体回滚无残留。外部删除本身不可回滚，失败仍保留manifest以便重试；不宣称跨服务原子事务。
- 实际产品DELETE /privacy/data清除测试学习/审计/Dayend及Storage音频和转录占位文件，文件下载明确返回不存在，身份/profile保留且再次清理成功。重填夹具后DELETE /privacy/account正常删除Auth，旧JWT访问隐私/科目均401，再次密码登录失败，另账号数据不变；另一个带数据账号也正常删除。保护请求新增Auth在线get_user核验（明确拒绝401、不可用503），避免只校验签名导致已删除身份继续使用旧JWT；每次保护请求增加一次Auth调用，尚未测P95。
- **验证：新增13项回归，完整后端899 passed，3个既有弃用警告；最终真实本地SQL/Auth/HTTP/Storage10项通过，报告success=true/cleanup=true**。Ruff F、离线quality gate、diff检查通过。无TestClient/身份覆盖、无模型调用、无真实用户数据。前端未变，未重跑前端构建或浏览器；上一轮Edge/Chrome22项属于当时版本证据，不能当新增认证逻辑后的浏览器复验。
- 失败记录保留：首次脚本遇到外键和Windows临时目录清理权限中断，无完整报告；已核验精确3个临时ID并清理。中间轮 `second-report.json` checks为空/cleanup=true，实际Auth500失败，不是通过证据；最终报告另存，不篡改中间轮。测试最终只清理本轮生成的精确账号/路径/Redis键。正常Auth/Storage服务日志和备份不承诺清除。
- 复跑：backend下 `.\.venv\Scripts\python.exe scripts/verify_privacy_integrity.py`（本地初装加 `--apply`）；`.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_privacy_full`；`scripts/run_quality_eval.py`。Windows目录/子进程限制按工具权限执行。**部署需先安装历史迁移至058再部署API**，无新依赖/Worker调度；未改实际.env、用户技术指南或重启既有服务。
- **下一阶段：数据保留与运行可靠性**，优先音频/审计/指标/事件的期限与清理；并保留上传/Worker与删除互斥和发布栅栏、孤儿文件/真实LightRAG清理、原始文件打包导出、完整跨用户安全矩阵/浏览器/生产及规模验收。整体计划成功率、独立测验补救、其他页面真实浏览器和模型长期质量继续按进度表推进，未被本轮替代。

## 2026-10-27 — 进度/验收文档整理与真实浏览器补验（历史阶段）

- 已完成本轮明确要求：**整理进度表及验收记录，执行学习记录真实浏览器验收，修复问题并更新交接**。进度表改为当前结论/分层验证/模块矩阵/后续优先级，去除反复叠加的“最新”“下一阶段”；旧全文原样归档到 `docs/history/OPTIMIZATION_PROGRESS_HISTORY_20261027.md`，未删历史证据。新增 `docs/acceptance/README.md`，区分合成/身份覆盖API/真实JWT浏览器/长期效果。
- **真实浏览器已补验，范围限定学习记录与相邻认证流程。** 当前内置Browser插件没有可调用执行工具，按技能读取和工具发现后改用独立本机浏览器：Edge **156.0.4314.42** 与Chrome **156.0.8078.47**，Playwright Python **1.64.1**，Windows无头真实渲染，1365×900/1024×768。正常本地Supabase密码登录及后端HS256 JWT验证，无TestClient、身份覆盖或登录存储注入。两款浏览器各 **11/11 passed**，合计 **22项**，均pageErrorCount=0。
- 覆盖保护页重定向/登录、30天默认和60%覆盖率夹具、慢旧窗口响应不覆盖90天新窗口、推荐20→23/行动30→60→65分页、Enter聚焦详情/Space展开、reload保持选中URL、关闭详情焦点恢复、覆盖率503时其他部分仍可读与重试恢复、两档桌面无document横溢、同浏览器退出/登录空账号隔离、另账号真实404，以及正常auth/token/Bearer流量。503与延迟是明确故障注入，正常读取均走真实本地API/DB；数据为合成临时夹具，不是学习效果证明。
- **首轮发现并修复**：关闭详情后按钮随面板隐藏，键盘焦点丢失。LearningMetrics现在维护已挂载历史按钮及上次选中ID，关闭/返回列表时恢复对应“查看”；行不在当前页或无访问权时聚焦历史标题。初始失败和确认结果均留档，不把单元模拟当浏览器焦点证明。双浏览器同一确认轮均通过，截图已实际查看；未扩大到其他业务页面或移动设备。
- 新脚本 `backend/scripts/verify_metrics_browser.py` 只允许本机DB/Supabase/Redis，使用新建临时账号、新浏览器profile和自有随机端口服务，阻止页面外部资源请求。添加可选 `backend/requirements-browser.txt`；不改生产依赖、实际.env或用户技术指南，不重启现有业务服务，不调用模型/付费服务。脚本不保存password/token/storage_state/HAR，最后清理精确生成账号及学习级联数据/本人Redis快照和自有服务进程；确认轮均清理成功，最终临时账号为0。
- **清理发现需保留**：首轮直接Auth管理员删除带数据夹具账号返回数据库500，自动报告在清理处中断；已核验精确临时ID后用本地SQL删除并确认数据为0。首轮记录注明从捕获输出重建且运行时计数未记录，未伪造完整通过。确认轮改用验证过的精确测试ID SQL清理。该结果不能当产品“删除账户”流程通过或已查明根因；产品流程先清学习数据，仍需Security/Privacy专项验收。正常Auth服务日志未承诺清除。
- 证据：`docs/acceptance/METRICS_BROWSER_20261027.md`、`metrics_browser_20261027/edge/report.json`、`chrome/report.json`、截图和 `evidence.json`（源码/最终报告/截图的文件SHA256）。原 `METRICS_WORKSPACE_20261027.md` 已增加补验结论，保留旧SQL/API身份覆盖事实，去掉“当前没有浏览器验收”的过期结论；多设备/其他页面待办仍保留。
- 验证：本轮前端三组Node **33 passed**、lint/build、Ruff F、文档链接/证据哈希/diff检查通过；最大chunk **255.61 kB**，学习记录页 **18.69 kB**。最近完整后端基线仍 **886 passed, 3 warnings**（上轮；本轮无后端业务变更，未重复跑完整套件）。Node/esbuild/真实浏览器按已有命令权限执行。浏览器可运行不表示原有所有页面已验收，不宣称生产JWT、跨内核/跨设备、真实模型、长期效果或P95完成。
- 复跑：backend下安装可选browser依赖后，`.\.venv\Scripts\python.exe scripts/verify_metrics_browser.py --browser edge --output-dir ../docs/acceptance/metrics_browser_20261027/edge`，Chrome将参数改为chrome；前端Node/lint/build照原命令。依赖历史迁移至057及本地认证配置、前端node_modules、本机Edge/Chrome。详见新浏览器验收记录。**下一轮优先Security/Privacy：直接Auth删除500与正常产品删除路径、导出/清理完整性和审计数据保留策略**；整体计划成功率、独立测验补救、其他页面浏览器、真实模型与长期质量按进度表续作。

## 2026-10-27 — 学习记录界面、审计分页与预测覆盖率（历史阶段）

- 承接第 24 项待办，完成三个模块：**学习指标页面、推荐/行动历史分页、预测覆盖率**。新增并本地安装 **057_prediction_coverage.sql**，包含首次评分发布的覆盖记录、私有采集触发器/聚合 RPC，以及推荐/事件的复合翻页索引。前序 055/056 API、统计和隐私行为保持兼容。
- **模块一：界面。** 新增全局 `/learning-metrics`，侧栏“学习记录”，无需选择科目，汇总本人全部科目。沿用蓝白工作台，以表格/分组明细呈现 7/30/90 天的安排完成率、观察中/成熟/迟完成数量、首次预测覆盖率、按版本 Brier/ECE/分桶、推荐投递/点击/采纳/完成、会话 Mastery 变化和自信校准。明确计划任务不等于整个计划成功、未成熟不纳分母、again 只表示完成复习；无分母显示“—”，无基线不显示默认 .5，显示样本数与口径。
- 指标读取独立处理失败，成功部分仍显示；窗口改变不混用旧结果，刷新/换账号/切换推荐会使迟到请求和旧 finally 失效。历史/行动追加按 ID 去重，重复点击领取用 pending 保护。浏览器 URL 保存选中 recommendationId，支持返回恢复/关闭详情；显式查看后焦点进入详情标题，表格可键盘横向滚动、原生 details 展开信号/版本/分桶，刷新不调用模型或改期。新页面绕过 Workspace 缓存，不新增 fallback。
- **模块二：分页。** `GET /recommendations/history?limit=20&cursor=…` 按 created_at/id 双降序；`GET /recommendations/{id}/audit?limit=100&cursor=…` 原结构保留并增加 nextCursor，前端行动每页 30 条。页大小 1–100，读取 limit+1 判断 hasMore，游标取最后已交付行；同时间用 UUID 继续，翻页时新增的较新记录留待刷新，不重复之前页面。游标绑定本人及 history/具体推荐范围、验证时区/UUID/版本/长度后规范化，非法或跨范围 422；每次查询仍强制 user_id，游标不是授权凭证。非本人详情 404。
- 推荐详情显示生成时的科目/建议/理由、优先分数、输入信号/分项/规则版本与后续确认/步骤/完成时间线，可继续加载更早行动。历史不受指标窗口筛选，不直接执行可能过期的旧导航。缺少上报不解释为没有学习；点击率只用已曝光且点击的记录，点击总数可能包含曝光漏报，页面解释分母。
- **模块三：覆盖率。** `mastery_prediction_coverage` 在首次正式 graded 或 adaptive 即时评分发布时保存 known_outcome/has_prediction 与 available/no_response/no_snapshot。未知正确性单列，不入分母；coverage=有首次预测且正确性明确 / 正确性明确。正式未发布不统计，重复发布不计第二次，未知或缺预测不冒充零准确率；没有新活动不回填旧成绩，新增 adaptive 成绩不会顺带补造该 attempt 的旧评分。记录冻结后不因后来补答案而改写。`GET /recommendations/prediction-coverage?days=30` 返回 SQL 全量聚合和定义、no-store，无样本 null；它只覆盖 057 后的发布，056 校准样本可能更多，页面明确说明。
- 新覆盖表本人 RLS 只读，service_role 仅读/删除，采集/指标 RPC 私有，已纳入隐私导出和科目/账户级联。读取指标/历史本身不产生推荐曝光或学习成绩，不新增 Worker/Beat、后台模型调用或历史回填。
- 验证：新增 **21 项后端 + 8 项前端 Node 回归**；完整后端 **886 passed, 3 warnings**，三组 Node **33 passed**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **255.61 kB**，指标页独立 chunk **18.34 kB**。Node/esbuild 首次被沙箱 spawn EPERM 阻止后按命令权限重跑；完整 pytest 因前序临时目录访问限制按既有测试权限运行。UI 检查新页面已无提示，剩主框架原退出按钮互斥 hover 配色提示，经代码核对保留。没有可调用浏览器工具，未宣称浏览器/键盘/真实 JWT 验收。
- **真实 PostgreSQL + Supabase/API**：同时间 5 条推荐及 5 条事件分三页完整/无重复、第一页后并发新增较新记录不混入后页、history/详情/账户游标错用 422、匿名401/异主404/空历史、参数边界/no-store 通过。SQL 验证正式发布前覆盖为 null、发布4条中3条正确性明确/1条有预测，覆盖 1/3，缺作答/缺快照/未知各1，重复发布和旧 adaptive 不补造、RLS/私有写权限通过。055/056 的真实 SQL/API 回归通过；临时随机用户精确清理并核验新旧审计表级联。合成作答/成绩只验证统计，身份为依赖覆盖，无真实用户写入或模型/付费调用。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/verify_metrics_workspace.py`（本地首次安装/刷新 057 用 `--apply`）、`verify_product_quality.py`、`verify_learning_outcomes.py`、完整 pytest/Ruff F/quality gate；frontend 下 `node --test tests/learningMetrics.test.mjs tests/recommendationExposure.test.mjs tests/versionedCache.test.mjs`、lint/build。其他环境先安装历史迁移及 057 后部署 API/前端；本轮未重启既有服务、未改实际 .env 或用户指南。验收 `docs/acceptance/METRICS_WORKSPACE_20261027.md`，进度表已更新。
- **下一轮可推进 Security / Privacy 专项与指标/审计数据保留策略**；整体计划成功率、独立测验补救、真实独立标签/模型质量、分组置信区间/长期效果、浏览器/JWT/多端与 P95 仍列待办，不将本轮界面或合成统计视为这些验收完成。通用资料摄取恢复、完整导航重组等其他模块剩余范围见进度表。

## 2026-10-27 — 离线质量对照、输入绑定与门禁（历史阶段）

- 续接第 24 项剩余的独立质量实验基础设施，新增 `paired_quality_service.py`、`compare_quality_runs.py`。外部 manifest 标签与 baseline/candidate 输出分开，逐 case ID/kind/输入 SHA256 和整份规范标签 SHA256 绑定；要求每边样本完整且唯一，不允许静默剔除缺失样本。严格类型/相关度 0–3、日期/分钟范围、重复排名/JSON 键、NaN/Infinity、标签冲突、未知字段与过大文件拒绝。run/version 必须区分，输出不能覆盖输入/门禁文件。
- **模块一：评分与比较。** 重排支持 graded nDCG、MRR、Recall、完整输出禁用来源检查；证据/回答守卫支持 false-reject、false-accept、受支持/不支持回答接受率和已标维度准确率；计划用外部 Topic 相关度/范围/剩余容量评估相关性、覆盖、越界、超时长和相同 Topic/日期/方法重复率。不把生产 priorityScore 当真值，也不使用被测模型给自己的输出打分。空计划精度/约束比例 null、覆盖 0，未知 guard 标签不当负例。
- 各指标报告双方可用数/全体均值、共享有效配对数/均值、candidate−baseline 差值、按好坏方向换算的 improvement。默认固定种子、2,000 次配对 case percentile bootstrap 的 95% 差值区间，少于两对为 null；默认 case 独立，小样本/关联文档/同一学习者/多重比较未校正，不能当因果结论。报告保留版本、标签来源声明、规范输入/输出哈希、配置与逐例数值，不附原始正文；外部 ID/来源文字仍需调用方匿名化。
- **模块二：门禁与复跑。** 显式 JSON 配置绝对最小/最大值、平均改善及改善区间下界、最低样本数（默认 2，仅保护下限）。绝对门禁检查全部 candidate 可用样本，避免 baseline 空值掩盖 candidate 错误；改善检查配对样本。无样本/无区间不能通过，错误指标/空配置/冲突阈值拒绝。CLI 退出 **0=比较成功（无门禁为 not_requested）/1=门禁失败仍保存报告/2=输入配置无效不写新报告**，报告存门禁配置和哈希；不是发布批准。使用说明 `docs/QUALITY_EXPERIMENTS.md`。
- 新增 **24 条 synthetic-regression**（3 重排/18 既有 grounding 规则样例/3 计划），实际执行当前 LexicalReranker、evidence-v2/claim-citation-v1、prioritize/build_schedule；对照明确是输入 RRF 顺序、仅非空引用的弱负对照和未过滤计划负对照，**不是旧生产版本**。执行函数只消费输入，评分使用分开标签；但标签仍为仓库作者合成/既有规则回归，**不是独立人工盲标，也不是语义模型评估**。既有 quality gate 接入这组合成契约门禁。
- 保留词法歧义退步例：3 条重排 nDCG **.7584→.8770**，均差 **+.1186**，95% 区间约 **[-.3691,+.3691]**，跨 0；不能判定真实 uplift。固定回答守卫拒绝/计划相关性改善均只对合成负对照成立。常规回归门禁 passed；显式要求 nDCG 改善区间下界≥0 的门禁 **failed（CLI 退出1）**，结果留档，不移除反例或放宽为“效果通过”。原始 artifacts/两份门禁报告在 `docs/acceptance/paired_quality_20261027/`。
- 验证：新增 **37 项**后端回归，完整 **865 passed, 3 warnings**；Ruff F、含新 24 条的 quality gate、diff 检查通过。覆盖手算 nDCG/MRR/区间、方向反转、样本/标签/输入错配、禁用来源在 top-k 外、空值/非配对错误不漏门禁、CLI退出码/覆盖保护/错误 JSON。pytest 临时目录首次被沙箱 WinError5 阻止，按测试权限重跑；完整测试也在已授权环境通过。本轮无前端代码、迁移或真实 DB/模型调用，不新增浏览器/JWT/模型效果声明。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/run_quality_experiment_fixture.py --output-dir ../docs/acceptance/paired_quality_20261027`，再按使用说明运行 `scripts/compare_quality_runs.py`；完整 pytest/Ruff F/quality gate。无需新依赖、迁移、Worker 或服务重启；未改实际 .env、用户指南或真实学习数据。验收 `docs/acceptance/PAIRED_QUALITY_20261027.md`，进度表已同步。
- **下一轮可继续第 24 项的指标界面、审计历史分页和预测覆盖率**。独立人工真实标签、真实 semantic reranker/生成/计划采集、分组重采样/同人对照/置信功效、长期学习效果仍是明确未验收项；本轮已提供导入与比较工具，不把工具完成等同真实模型提升。整体计划成功率、独立测验补救、数据保留清理/P95 和 Security/Privacy 后续范围仍保留。

## 2026-10-27 — 学习完成率 cohort 与前瞻 Mastery 校准（历史阶段）

- 续接第 24 项未完成的指标，不提前跳到 Security。新增并本地安装 **056_learning_outcome_cohorts.sql**：learning_metric_cohorts 按来源/修订保存稳定分母，mastery_prediction_samples 保存已发布结果与首次答题时的预测。两表本人 RLS 只读，service_role 仅可读/删除，插入与完成更新由私有触发器执行；纳入隐私导出、科目/账户级联，未回填旧任务/旧闪卡安排/旧作答。原 055 审计和推荐接口保持兼容。
- **模块一：完成率。** Guided 首次确认、每个新计划任务首次安排、每次闪卡调度版本、一个有版本 Guided 会话内首次低于 .8 的测验分别创建 cohort。统一 7 天观察窗，默认查询最近 30 天（允许 1–90）；分组返回 total/mature/pending/late/completedWithinHorizon，只有完整观察窗的 mature 进入分母，无成熟样本比例 null。任务或源记录被重排/删除不抹去已承诺分母；重新生成的任务是新承诺，隐私删除仍移除本人数据。完成时间保存首次实际完成，超过期限的完成只计 late。
- 计划字段是 **Plan Task Completion**，不是整个计划成功率。任务从首次原定日期上海时间零点与创建时间的较晚者开始计窗，后续人工改期不重写原 cohort。闪卡从原到期时间与新调度创建时间的较晚者开始计窗，提前评价可完成旧安排；again 也算完成复习操作，不证明记住。内容版本变化不把新内容评价算作旧内容成功。尚未进入 starts_at 的将来安排暂不进入查询；现有但从未再调度的旧闪卡不补造分母。
- Quiz Remediation 仅统计有版本 Guided 的首次失败测验后，序号更大的实际测验达到 .8；同一步重建、重复完成或多次失败不重复创建分母。既有 055 step.completed 事件已存在的步骤不当成新失败，旧无版本会话不做补救 cohort 回填；不是所有独立测验的补救成效率，也不把插入 remediation 文本步骤当成功。
- **模块二：前瞻校准。** exam_responses.mastery_prediction 在首次 INSERT 中由服务端选择本人/同科目/同知识键的已有 assessment 证据，记录 score、confidence、来源算法版本、证据数、原 Mastery 更新时间与采集时刻；没有证据即空，不用默认 .5。任何后续保存/重答均保留首次快照，客户端即使传该列也不能覆盖。评分或后续 Mastery 变化不能倒填预测，旧答案没有快照不回填。
- 正式考试只在 graded 后发布预测样本，adaptive 沿原即时发布规则；不需要自报 learnerConfidence，正确性未知不纳入。按预测来源算法版本返回样本数、Brier、10 个固定区间的均值/正确率和加权 ECE。它衡量当时 Mastery score 与下一题正确性的经验偏差，**score 不是已经验证的概率**，不同版本的人群差异不能据此当因果 uplift。新指标窗口按成绩发布时刻选择样本，不能冒充首次作答日 cohort。
- 新增只读 `GET /recommendations/learning-outcomes?days=30`，SQL 一次聚合，认证账户决定范围，no-store；不写状态、不调模型、不重排任务，不依赖 Worker/Beat。新增 **10 项**后端接口/边界回归，完整 **828 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。本轮没有前端代码变更，沿用上一阶段前端验证记录，没有重复宣称新增 UI 验收。
- **真实本地 PostgreSQL + Supabase/API** 验证通过：未成熟 null/到期后分母、迟完成排除、删任务仍有分母、步骤重建去重、提前复习与未成熟新安排、首次预测 .2/.8 冻结、伪造/重答不覆盖、评分前 .99 更新不泄漏、无 assessment 证据排除、正式/adaptive 发布、Brier .04/.64、ECE .2、版本分组、**2,001** 条成熟 cohort 全量返回与 1,000 次成功、RLS/只读权限、匿名401/参数422/跨用户空结果。055 的真实 SQL/API 回归也通过。验收合成时间/成绩只用于临时 fixture；API 依赖覆盖身份，不是 JWT E2E，不能证明真实 7 天效果。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/verify_learning_outcomes.py`（本地初装/刷新 056 用 `--apply`）、`scripts/verify_product_quality.py`、完整 pytest/Ruff F/quality gate。脚本仅允许本地 DB/Supabase，随机临时用户供跨连接 API 读取，结束精确删除且验证 cohort/sample 级联；没有真实用户写入或模型调用。其他环境按序安装历史迁移和 056 后部署后端；本轮未重启既有服务、未改实际 .env 或用户指南。
- 验收：`docs/acceptance/LEARNING_OUTCOMES_20261027.md`；进度表已同步。**下轮继续第 24 项剩余的独立质量评估实验/结果比较（reranker uplift、grounding/false-reject、plan relevance）**；整体计划完成率、独立测验补救、指标 UI/审计分页、置信区间/同人对照、保留清理/规模 P95 和真实长期样本仍待补。没有把本地合成 Brier 或 7 天时间平移当线上学习效果，也没有宣称整个第 24 项完成。

## 2026-10-27 — Observability / Quality Evaluation 产品审计首轮（历史阶段）

- 已承接缓存阶段后的指南第 24 项，新增并本地安装 **055_product_quality_audit.sql**。`recommendation_audits` 保存每次投递的排名、生成时间、输入信号、分项分数、理由、原始导航与 recommendation/studySignal/learnerState 版本、请求 trace；返回独立 recommendationId，刷新建议形成新的投递。`product_events` 保存 v1 来源表/ID/修订、算法版本与服务端时间，服务角色只准读/插入/删除，显式撤销 Supabase 默认 UPDATE 授权；客户端仅本人只读，不能更新或伪造学习结果。两表纳入隐私导出，随科目/账户删除级联，无历史回填。
- 原 `GET /recommendations/next-actions` 保持只读；前端首页显式使用 `?audit=true` 才保存投递，保存失败不返回虚构 tracking ID。新增 `POST /recommendations/{id}/feedback` 仅接收 impression/clicked，服务端验证本人记录及 7 天窗口，唯一约束去重，客户端不能提交分数/结果/时间。推荐接口统一 no-store。`GET /recommendations/{id}/audit` 返回原始快照与最近 100 条关联事件、hasMore，帮助核对版本/信号/分数/理由/采纳/结果。
- 首页通过 IntersectionObserver 记录卡片至少一半进入视口且 document 可见的曝光；后台页、未进入视口、缺 Observer 均不计数。失败可在后续可见性通知重试，退出页面断开监听；点击上报采用有界 keepalive 请求，不阻止导航。曝光和点击是**客户端报告、尽力采集**，不是已验证的人类注意力；请求推荐本身不算曝光，点击本身不算采纳。沿用原工作台样式。
- 推荐 ID 随 Guided URL 和创建请求进入 context；创建事务核验本人/科目/Topic/时限，错 Topic 或过期拒绝，切换 Topic 不继承旧关联。Guided 真正进入 active 才记 session.accepted，completed 才记结果；学习步骤完成、Mastery 前后值、计划重排、任务首次完成、自适应每轮停止、已发布评分的信心校准均由 canonical 表触发器与业务同事务保存。步骤在现有 RPC 删除/重建时按稳定 ID 去重，任务反复完成仅计一次，每次 resume 可产生新停止；不接受浏览器自行宣称学习完成。
- 新增 `GET /recommendations/quality-metrics?days=7`，窗口 1–90 天，SQL 聚合不受 PostgREST 行数默认上限截断。按投递时间 cohort 与推荐版本返回 delivered/impressions/clicks/exposedClicks/accepted/completed；CTR、采纳率只用已曝光记录，完成率分母为其中实际采纳记录，零分母为 null。另返回事件计数、完成会话且前后均有 assessment 证据的平均 Mastery 百分点变化、样本数和 learner-confidence Brier；不把默认 .5 当基线，不把自报信心校准解释为 Mastery calibration，也不把前后变化解释为推荐的因果效果。正式考试成绩只在 graded 后进入校准事件；adaptive 可按原成绩发布规则即时记录。
- 验证：新增 **13 项后端 + 6 项前端 Node 回归**，完整后端 **818 passed, 3 warnings**，前端两组 Node **25 passed**；Ruff F、既有 quality gate、lint/build、diff 检查通过，最大 chunk **254.55 kB**。Node 首次被沙箱 spawn EPERM 阻止，按测试权限重跑通过。UI 静态检测 4 条来自既有同一行嵌套元素配色，逐项代码核对，本轮没有改配色/布局；没有可调用浏览器工具，未宣称浏览器、真实 JWT 或真人曝光验收。
- **真实本地 PostgreSQL + Supabase/API**验证：保存快照不生成曝光，反馈重复三次只一条，实际创建/确认 Guided 才采纳，空统计/缺基线、跨用户 404/匿名 401、无效客户端结果 422、错 Topic/过期关联拒绝、Mastery .2→.7 = +50 点、完成/步骤/任务去重、两轮停止、重排、Brier .64、正式成绩发布门槛、RLS/私有 RPC/角色更新权限与事务回滚通过。API 使用依赖覆盖身份；SQL 完成结果为合成 fixture，只验证统计口径。临时用户精确清理并核验审计/事件级联，无真实用户写入、无模型/付费调用，未改实际 .env 或用户指南、未重启既有服务。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/verify_product_quality.py`；本地首次安装或刷新本轮函数/索引用 `--apply`。其他环境按历史迁移后安装 055，再部署 API/前端；现有流程不需新增 Worker/Beat。验收 `docs/acceptance/PRODUCT_QUALITY_AUDIT_20261027.md`，进度表已更新。
- **下一轮仍留在 Observability / Quality Evaluation**：补稳定 cohort 的 Guided/Plan/Due Review 完成率与 Quiz remediation 成效率、真正的 Mastery 预测校准/分桶及版本对比，接入独立模型/真实标注的 reranker uplift、grounding/false-reject 与 plan relevance 实验。还缺指标界面、历史审计分页、跨端浏览器、持续采集、保留/清理策略和规模/P95 验收；本轮不把事件计数冒充这些完整指标，也不提前宣称第 24 项全部完成。

## 2026-10-27 — Workspace Cache 版本与失效（历史阶段）

- 接上轮未完成的 Workspace Cache，新增并本地安装 **054_workspace_cache_versions.sql**：workspace_cache_versions 按本人/科目或全局/资源记录 revision 与版本。学习领域事件插入及课程/聊天/计划任务/覆盖/闪卡/导图/考试等 canonical 变化在原事务内推进对应资源版本，**不等待 Worker 消费**；Mastery/评分影响 Dashboard/Plan/推荐，资料入库影响 Mind Map，同科目变化不失效其他科目或无关聊天。projectionVersion 作为诊断元数据返回，实际有效性以同步资源版本为准。
- 新增 `GET /workspace/cache/{resource}/version?subjectId=…`；全局 dashboard/subjects/workspace 禁止指定科目，chat/mind-map/exams/plan/recommendations 必须验证本人科目。认证用户只读版本表，RPC 仅 service_role 执行，新表纳入隐私导出。版本包含 schema/rule、资源、用户、科目与 revision；学习类资源另带上海时区分钟桶，覆盖没有 DB 写入的日期/到期边界。该桶有意限制 fallback 有效窗口，不改变 Redis 原存储 TTL。
- Redis 改为 workspace:v2 + 用户/资源/科目/版本键与 schemaVersion=2 envelope。PUT 必须带主读取开始前取得的 expectedVersion，版本已变化返回 409；GET 在 Redis 读取前后均检查当前版本，拒绝旧 schema、旧版本、损坏/错科目 envelope。版本无法验证不返回缓存；接口成功响应加 Cache-Control:no-store。v1 快照不迁移、不再加载，旧键按原 TTL 淘汰。
- 前端 cached helper 在主读取前后校验版本，途中变化最多重取一次，持续变化返回冲突；不把旧结果绑定到新版本。临时主请求故障仅接受服务端已验证且再次复核的 v2 fallback；401/403/404/409/422 不回退。版本或 Redis 写入故障不把成功的主请求变成失败，但不保存无法验证的快照。缓存操作前后核对账户；退出/换号时旧响应不返回，Outlet 按账号重新挂载。
- 缓存提示按账号/资源/科目管理，无关请求成功不再清除当前页面的 fallback 提示。主框架对支持的当前页面在可见时每 15 秒、重新获焦与恢复可见时检查 dataVersion；记录变化或 fallback 分钟版本过期显示刷新提示。明确区分“已校验缓存”“无法复核”“记录变化/过期”，用户点击刷新才重载，不自动丢弃答题和表单。权威 Learner State/推荐/导图实时投影仍沿原路径绕过缓存，不新增它们的 fallback。
- 清空学习数据后原子撤销全部旧版本，并为仍存在的全局/科目生成新 revision，再按精确用户 UUID 批量清理 v1/v2 Redis 键；Redis 故障只延后物理清理到 TTL，旧代次仍被数据库拒绝。清空学习数据后允许保留不含学习内容的全局失效元数据，避免版本归零恢复旧快照；删除账户后随 auth.users 级联清理。删除某科目后旧缓存首先被归属检查拒绝，不依赖 Redis 删除成功。
- 验证：新增 **20 项后端**与 **19 项 Node 前端缓存回归**，完整后端 **805 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **254.38 kB**。Node 测试首次因沙箱 spawn EPERM 被阻止，按批准的测试命令重跑通过。静态 UI 检测仅布局原退出按钮的互斥 hover 配色提示，新增横幅已代码核对；没有可调用浏览器工具，未声明浏览器/真实键盘验收。
- **真实 PostgreSQL + Redis + Supabase/API + 第二 DB 连接**验收通过：评分与 Mastery 提交在事务内立即改变版本，旧 GET miss/旧 PUT 409，合成缓存 .2 不会在变化后回退，重新读取并保存 .9 后可用；无关资源/科目/账号保持有效，资料 ready 失效导图、错科目/匿名/全局 scope 拒绝、no-store、RLS/私有 RPC 通过。还验证了正常缓存清除及 Redis 故障时旧科目代次不复活。用精确随机 ID 创建的临时用户/数据及 Redis 键均已清理，未写真实用户快照、未调用模型或付费服务；认证为测试覆盖，不等于真实 JWT。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/verify_workspace_versions.py`（本地首次安装/刷新用 `--apply`）、完整 pytest/Ruff F/quality gate；frontend 下 `node --test tests/versionedCache.test.mjs`、`npm run lint`、`npm run build`。真实验收脚本只允许本地 DB/Supabase/Redis，需提交可跨连接读取的临时用户并在结束精确清理。其他环境先安装历史依赖及 054，再部署 API/前端；现有版本触发器生效不需新增 Beat/Worker。本次未改实际 `.env` 或用户技术指南、未重启既有服务。
- 验收：`docs/acceptance/WORKSPACE_CACHE_20261027.md`；进度表已同步。不是 WebSocket 自动同步，不承诺 15 秒内服务/网络一定可用；已有页面的跨端变化通过提示/显式刷新处理。Redis 多版本键仍按 TTL 保留，整体容量/淘汰策略、性能/P95、真正多端浏览器与离线恢复、通用 Workspace 所有页面自动刷新仍待补。**下一阶段按指南推进 Observability / Quality Evaluation：产品事件、推荐曝光/采纳、学习前后变化与算法版本审计。**

## 2026-10-22 — Worker / Async Task 学习事件闭环（历史阶段）

- 已按本次要求先完成下方 Dayend 界面、历史、主入口收敛与可选自动调度，再推进 Worker；两个模块分别留存验收记录。当前版本完整后端 **785 passed, 3 warnings**（本次共新增 21 项：Dayend 自动化 11、学习事件 10）；Ruff F、quality gate、前端 lint/build、diff 检查通过，最终最大 chunk **251.02 kB**。前端构建曾被沙箱 EPERM 阻止，按已授权构建规则重跑成功。
- 新增并本地安装 **053_learning_domain_events.sql**：learning_domain_events 定义 v1 schema、类型/来源表/来源 ID/修订/发生时间/消费回执，learning_projection_versions 保存本人科目的失效版本。六类事件 material.indexed / exam.completed / mastery.changed / flashcard.reviewed / exam.updated / task.missed 由真实表触发器或漏做补扫产生；事件和 outbox 与业务写入同事务，源事务回滚不留下消息。漏做来源日期去重，资料/评分只在进入成功状态时产生，掌握度无实质改变不产生事件；无历史数据批量回填。
- 复用 052 持久队列与 ID 消息，30 秒延后领取吸收事件突发；领取使用租约/令牌，消费在同一事务中写事件回执、推进 projection version、按需标记计划 dirty 并确认任务。成功任务重放不重复变更，旧令牌不能发布。Signals/Recommendations 仍从 canonical 数据按需计算，不把事件 payload 当作成绩或 Mastery；版本供下一阶段精准缓存失效使用，尚未接入通用 Workspace 缓存。
- 重算继续调用原确定性 Study Plan v3 + 每 5 分钟 Beat，保留 autoReplan、考试范围、共享容量及锁定/人工/已完成任务约束。增加 replan_dirty_since：等待 30 秒安静窗口，但同次 dirty 最长延迟 2 分钟，连续事件不会无限延后；实际执行仍受 Beat 频率和每批 20 个计划上限约束。消费事件不直接重新生成完整计划，避免每条事件重排一次；旧同步信号标记兼容保留，不重复提升已 dirty 的计划版本。
- 失败任务最多 5 次退避后进入 dead；新增本人同科目任务状态查询 `GET /learning-jobs?subject_id=…` 和 `POST /learning-jobs/{id}/retry`。手动重试最多 3 轮，仅 dead 可重置；过期/关闭的日终任务不能重试。复盘页面加入当天自动报告失败后的重试按钮。错误只保存异常类别，不把堆栈/密钥写入状态；原 ingestion/conversion 任务不自动迁移到新队列。
- 真实 PostgreSQL 回滚验收覆盖六类事件/原子 outbox、源事务回滚、漏做去重三次、同事件消费三次最终 epoch/回执不重复、重算窗口/最长等待、有限手动重试/归属、私有 RPC/RLS/级联；实际 Supabase 只读任务 API 200/404/401 通过，身份为测试覆盖。052 和 051 的真实 SQL/API 回归也通过。新表随隐私导出、科目和账户删除清理。
- **已执行真实本地 Redis + 隔离 solo Celery Worker + 实际 Supabase RPC**：临时独立队列各投递同一学习事件、同一日终任务 3 次，结果均为 succeeded/skipped/skipped；projection version 仅 1，日终只生成 1 份 pending 报告、未新增/改期计划任务。测试使用新建临时用户，结束后已级联清理该用户/数据、6 个结果及唯一测试队列；未消费现有业务队列，未调用模型/付费服务。它是有界真实 Worker 验收，不是持续 Beat、跨午夜、分布式多 Worker 或真实 JWT/浏览器验收；原独立 Dayend 模型评审继续 N/A。
- 复跑：backend 下 `.\.venv\Scripts\python.exe scripts/verify_learning_events.py --api`、`scripts/verify_daily_review_automation.py --api`、`scripts/verify_daily_reviews.py --api`（均用同一 venv Python）；真实隔离链路 `.\.venv\Scripts\python.exe scripts/verify_learning_worker_live.py`。`--apply` 只用于本地初装/刷新对应迁移。部署需按顺序安装 052/053，再部署前后端、重启 Worker/Beat 加载 sweep_learning_jobs；本次未重启既有业务 Worker/Beat、未修改实际 `.env` 或用户技术指南，也未为真实用户启用自动复盘。
- 验收：`docs/acceptance/LEARNING_EVENTS_WORKER_20261022.md`；上个模块见 `DAILY_REVIEW_AUTOMATION_20261022.md`。剩余范围明确保留：通用 ingestion checkpoint/outbox/claim 与全部取消栅栏、事件保留/清理策略、分布式并发和持续 Beat/跨日运行、真实浏览器及长期质量；不把第一轮代码当成全指南完成。**下一阶段为 Workspace Cache：使用 canonical 状态版本/事件版本做精准失效、隔离跨科目/跨端旧快照。**

## 2026-10-22 — Dayend 待办补齐：界面、历史与自动调度（历史阶段）

- 补齐上一阶段产品待办：新增 `/daily-review` 学习复盘页，侧栏主入口替代原“夜间整理”抽屉；原 v3 后端保留兼容和独立评审，但工作台新入口只进入课程复盘，无情绪/自由事务分支。显示今日完成、掌握度百分点变化/缺失基线、薄弱 Topic、明日任务/考试/共享预算、保存和明确确认/拒绝。历史报告支持 30 条游标分页（时间+ID），可通过 reviewId 恢复；历史改期不允许确认，页面不重建过去状态。
- 新增并本地安装 **052_daily_review_automation.sql**：本人科目独立的可选日终设置，默认关闭/22:00 上海时间，版本 CAS 保存；每分钟 Beat 扫描设定时段后的科目，每科每天最多一个持久任务。开启只生成报告、不自动决定改期；未更改真实用户设置。禁用会撤销未完成任务及令牌；发布与当前开关、租约、来源快照核验和任务成功确认在同一事务。
- 持久队列 learning_job_outbox 支持 SKIP LOCKED 领取、2 分钟租约/令牌栅栏、限 5 次退避、dead 与过期日终任务终止；broker 投递失败保留队列供下次补扫。报告按 job.id 幂等落库，重复消息不生成第二份。跨日失败明确 day_expired，不补造昨日快照。自动设置/最新任务状态接入页面；表随隐私导出和科目删除级联。
- 新 API：日终 schedule GET/PUT、历史 GET（before/before_id）；前端绕过缓存、科目切换重置、迟到读取忽略、请求 UUID 网络重试复用。沿用蓝白工作台、原生表单和焦点样式。UI 静态检查的单行条件/hover 合并提示已核对；无可调用浏览器工具，不宣称浏览器 E2E。
- 验证：新增 **11 项**回归，完整后端 **775 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build 通过（最大 chunk **250.93 kB**）。真实 SQL 回滚验证开关/CAS、日任务去重三次、单次领取/租约恢复/旧令牌拒绝、原子报告+ack、禁用发布栅栏、退避/死信/跨日、RLS/级联；真实 Supabase 历史/设置只读 API 200/404/401 通过（测试身份覆盖），临时行回滚。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_daily_review_automation.py --api`，本地首次装 052 用 `--apply`。部署 052/API/前端后重启 Worker 和 Beat 加载新增扫队列任务；本次未启动既有业务 Worker、未修改实际 `.env`、用户指南或真实用户计划。原 Dayend 独立模型评审继续 N/A，自动调度依赖部署后持续 Worker/Beat，不等于本轮已运行整夜。
- 验收：`docs/acceptance/DAILY_REVIEW_AUTOMATION_20261022.md`。本模块界面、历史回顾、工作台入口收敛和自动生成代码已补齐；通用历史状态重建/更丰富重排属于后续扩展，真实浏览器/长期效果保留验收边界。**按本次要求继续 Worker / Async Task 的学习事件 schema、原子投递、幂等消费、退避/死信和重算防抖。**

## 2026-10-22 — 续作：Dayend 学习复盘与计划改期（历史阶段）

- 完成面向课程复习的首轮 Dayend 增量：新增确定性 LangGraph `closure → planning → critic`，仅消费服务端 canonical 学习数据；不增加 Agent，不调用模型，也不把自由文本或长期 Memory 当成学习状态。原 `/api/v3` 自由文本 Dayend 及独立评审保留，既有评审 N/A 结论不变；新的学习复盘使用 `/api/v1/daily-reviews`，尚未替换原入口或新增前端页面。
- 新增并本地安装 **051_daily_learning_reviews.sql**：保存本人同科目的不可变来源快照、报告、requestId、确认状态与版本；认证用户只读，读取/保存/决定 RPC 仅 service_role 执行。subject 复合外键与 RLS 限制归属，表已纳入隐私导出，科目/账户删除级联。每次新复盘仅针对上海时区当天；旧报告可按 ID 读取，不支持历史日期重建。
- closure 读取当天完成任务、当天提交且现已评分的测验数、学习事件计数，以及稳定 Topic 的 canonical 状态。Mastery Changes 使用当天最后一条 mastery_history 与当天开始前最后一条记录计算，带 evidenceId，单位是百分点；没有历史基线则 deltaPoints=null，不假设初值。Unresolved Problems 仅报告 at_risk 或已有评估且 Mastery<0.6，未评估不会被默认 50% 标为薄弱。
- planner 读取当前科目明日任务、明日考试和全科目活动计划的共享日容量；建议优先进入薄弱 Topic 的 Guided Session。仅从本人同科目未归档 Topic 的未完成、未锁定、system 来源旧任务中提出最多 3 项移到明日的建议，排除考试日期不允许、目标日期已有相同任务及同批唯一槽位冲突；不新增任务、改考试目标或延长截止日期。没有明日容量时仅提供阅读建议，不猜测可用时间。
- critic 检查任务来源、重复、分钟数与跨科目预算，明确未知预算/既有超额，预算分钟不等于实测学习时长。读取与保存报告不需要人工审批；只有任务改期建议标记 requiresConfirmation，用户可明确 approve/reject。按请求 ID 重放读取原报告，异科目复用冲突；SQL 保存前重新核验来源快照。
- 确认时锁定复盘与共享日历，核验版本和完整来源快照；学习状态、任务、计划、容量或考试变化后拒绝旧建议。调用既有 move_calendar_task 复核保护/容量/范围并锁定任务，整批原子回滚；追加 daily_review_applied 事件关联 reviewId。决定重放幂等、反向决定冲突；不写 Mastery、Memory 或 covered。报告是生成时快照，确认后不会将历史报告改写为新学习状态。
- API：`GET /daily-reviews/preview?subject_id=…` 只读预览；`POST /daily-reviews` 接受 subjectId/requestId 并保存；`GET /daily-reviews/{id}` 读取；`POST /daily-reviews/{id}/decision` 接受 version 与严格布尔 approve。客户端不能提供原始状态/报告/任务列表。没有 UI、日终自动调度、LLM 复盘、时段安排或新任务生成。
- 验证：新增 **23 项**回归，完整后端 **764 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。真实本地 SQL 回滚验收覆盖 +12 个百分点及薄弱 Topic、共享容量/受保护任务、请求重放、旧快照/跨用户/版本拒绝、部分执行失败整批回滚、确认改期/锁定/事件与幂等、拒绝、不写 Mastery、RLS/私有 RPC/删除级联；全部临时行回滚。实际 Supabase 只读预览 API 200/无权或缺失 404/匿名 401 通过，身份为测试覆盖，未改真实用户计划。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_daily_reviews.py --api`；`--apply` 仅本地首次安装 051 或刷新函数。其他环境按历史依赖（含 023/029/036/044）安装 051 再部署 API，无新增 Worker/Beat 任务。本次未重启服务、未改实际 `.env`、用户技术指南或前端；未调用模型/付费服务、真实 JWT/浏览器或多进程并发，原独立 Dayend 模型质量评审继续 N/A。
- 验收：`docs/acceptance/DAILY_LEARNING_REVIEW_20261022.md`，进度表已同步。后续保留前端接入、原自由文本入口迁移与非核心分支收敛、真实学习效果/并发/浏览器验收、历史复盘和更丰富重排；不宣称指南 Dayend 全部完成。**下一阶段继续 Worker / Async Task：学习事件驱动、幂等投递与已有任务恢复边界，优先补既有机制而不新增 Agent。**

## 2026-10-22 — 续作：Memory / Learner Profile 边界（历史阶段）

- 完成 Memory/State 首轮边界：新增 memory-boundary-v1，允许明确的稳定偏好、习惯、反复困难和长期目标；以保守中英文词法规则拦截掌握度、正确率、考试结果/日期/临时目标、信心、到期复习、相对日期和百分比等状态文本；未识别文本拒绝。普通请求和旧提案审批均重新检查，数据库触发器提供第二层约束。这不是完整语义分类或概率校准，改写、混合语言及误拒需后续真实评测。
- 新增并本地安装 **050_memory_boundaries.sql**：memory_entries/memory_write_requests 增加 memory_kind 与服务端 provenance，记录规则版本、类别、user/learning_event 来源及事件/科目；验证来源事件属于本人同科目。历史记录标为 legacy，保持可查看/删除，但不注入新快照；用户重新保存合法偏好可重新分类，同文不会被 legacy 去重短路。没有自动删除或迁移真实历史记忆。
- 同文去重索引由全用户/target 改为用户/target/科目范围；替换/移除/语义候选和冲突比较限同一范围，按 ID 编辑保留原范围，不静默移动科目。容量仍按用户/target 汇总，容量淘汰只考虑本次范围。自动互动提案即使置信度高也强制 pending；后台提示仅提议稳定信息。既有去重/容量淘汰与审批尚非整体原子事务，完整 CAS/幂等发布保留待办。
- 冻结快照改走私有 `freeze_teaching_memory`：会话锁与唯一约束避免重复创建，严格绑定科目，只组合全局与当前科目的已分类合法记忆；保存来源 manifest、规则版本及白名单 preferredRole/responseStyle。已有合规会话冻结，新会话读取更新；关闭记忆即使已有快照也返回空上下文，旧版本快照被抑制。删除记忆使本人的快照失效，下一次按剩余记忆重建；这是隐私删除优先于冻结。RAG 使用冻结篇幅偏好，事实依据仍来自资料，显式教学角色规则保持原优先级。
- 长期画像不再返回/接受 examDate，Assistant 不再用全局画像日期生成当前科目计划；DB 拒绝新增/修改非空画像考试日期，旧值原样保留但不消费。考试继续使用同科目 Exam Event/计划或本次明确请求。preferredRole 限现有受支持角色，不增加新角色/Agent。
- 新增只读 `GET /learner-profile/study-behavior?subject_id=…`：按本人科目聚合最近 30 天 Guided Session 数、完成/取消数及已完成会话的预算分钟，附来源/时间/窗口。预算分钟不是测量学习时长；不推断习惯、不复制成绩/Mastery，不写长期记忆。当前为 API，尚未新增行为摘要或 provenance 管理界面。
- 验证：新增 **38 项**回归，完整后端 **741 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。真实本地 SQL 回滚验收涵盖 Python/SQL 分类一致、状态拒绝、归属/来源事件/范围/provenance、跨科目同文、冻结/新会话/禁用/旧快照、画像考试日期、行为聚合、RLS/私有 RPC；**删除 Study Plan 保留稳定偏好、删除 Memory 保留 Mastery 并失效快照**通过。全部临时行回滚。实际 Supabase 只读 API 200/缺失 404/匿名 401 通过，认证为测试覆盖。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_memory_boundaries.py --api`；`--apply` 仅本地首次安装 050 或刷新本轮函数。部署顺序：历史迁移依赖 → 050 → API/Worker 代码，后台提案需重启 Worker 才加载新提示；本次未重启既有服务。新增字段随原隐私表导出/删除，无新表。未改实际 `.env`、用户技术指南或前端，本轮不重跑无变化的前端构建。
- 验收：`docs/acceptance/MEMORY_BOUNDARIES_20261022.md`；进度表已更新。未调用模型/Embedding/付费服务、真实用户记忆写入、真实 JWT/浏览器或持续 Worker。本轮不证明语义去重和长期个性化效果；多来源完整历史、行为面板、记忆写入整体事务和参数化偏好编辑继续待补。**下一阶段为 Dayend / LangGraph：结合 canonical Learner State 的学习复盘快照与重排建议边界，保留既有独立评审 N/A，不横向增加 Agent。**

## 2026-10-22 — 续作：Mind Map Topic 绑定与学习状态（历史阶段）

- 完成 Mind Map 首轮 Topic 权威增量：人工选择本人同科目的未归档课程知识点；移除按名称包含关系匹配掌握度，模型/历史产物的 mastery 不再作为界面学习状态。关联不自动创建 Topic、写 covered 或提高 Mastery。
- 新增并在本地安装 **049_mind_map_topics.sql**：mind_map_topic_links 保存完整节点 JSON 快照、稳定 knowledge_point_id 与关联版本，复合外键限制本人同科目；认证用户只读，RPC 仅 service_role 可执行。保存锁定导图并校验 artifactVersion/bindingVersion，提升导图版本；解绑保留关联版本。节点内容变化或 Topic 归档使该关联失效，未变化节点不受影响；改名仍按不可变 knowledge_key 读取记录。新表已纳入隐私导出，随导图/科目/账户级联删除。
- 新增 `GET /artifacts/{id}/learning`、`PUT /artifacts/{id}/nodes/{nodeId}/topic`。读取 canonical 五状态、Mastery/数据置信度/自报信心、上次/下次复习、误解风险、未归档到期卡片和待考考试/权重。无作答时掌握度/数据置信度为 null，未关联/失效时不沿用旧掌握度；跨用户/非导图 404、旧版本 409、无效节点/Topic 422。
- 界面增加关联/解绑、Covered/Mastered/风险配色、到期/误解提示、学习记录、Guided Session 和真实考试 Study Plan 入口。考试计划仍包含完整考试范围，非任意单节点计划。生成时重要度与真实考试关系分开显示。原 Turn Into 保留，节点转换仅继承该节点当前有效 Topic，不再继承整图 artifact_topics；版本不一致时拒绝转换，来源引用核验/原子发布沿用原路径。
- 状态绕过 workspace 缓存，打开页面、保存关联、窗口获得焦点和手动刷新时重读；内容/状态版本冲突最多重取一次。科目切换重置工作区，迟到响应不覆盖当前请求；刷新失败关闭旧详情并保留重试。没有 WebSocket 推送或持续轮询。
- 验证：新增 **21 项**回归，完整后端 **703 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **256.38 kB**。真实本地 SQL 回滚验收覆盖归属/同科目/节点、双版本 CAS、无学习状态写入、不可变 key、改名/归档、due/考试、逐节点失效/重绑/解绑、RLS/私有 RPC/级联；全部临时行回滚。真实 Supabase 只读 API 200、缺失 404、匿名 401 通过，身份为测试覆盖，未改真实用户关联。
- UI 静态检查两个提示已核对：loading 蓝色进度条与白底灰字、节点蓝底/白底互斥分支被合并识别，不是实际灰字蓝底。无可调用浏览器工具，真实浏览器/JWT/键盘/布局/模型和持续 Worker 未验收。本次未重启服务、未改实际 `.env` 或用户技术指南。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_mind_map_topics.py --api`；`--apply` 仅本地首次安装 049 或刷新函数。其他环境按历史依赖安装 049 后部署 API/前端，无新增 Worker/Beat 调度。详见 `docs/acceptance/MIND_MAP_TOPICS_20261022.md`，进度表已同步。
- **下一阶段继续 Memory / Learner Profile 的 Memory/State 边界、偏好与 provenance。** Mind Map 的权威 prerequisite 边、新材料 graph diff、任意节点独立计划、自动有证据的 Topic 提案和真实 UI 验收仍待补，不声明指南全部完成。

## 2026-10-22 — 续作：Evidence / RAG QA（历史阶段）

- 完成证据与回答核验首轮：evidence-v2 对问题分项计算词法覆盖、记录引用数/资料来源数；coverage 现在表示问题分项覆盖，不再是文本长度比例。外部来源不能提高课程证据充分性，缺失子问题不因其他部分命中而视为完整充分，非有限/无效检索分数不会崩溃或直接证明语义支持。清理中英文通用语法词，避免仅凭 is/一种等词误判支持。
- 增加可选 borderline judge：`ENABLE_EVIDENCE_JUDGE=false` 默认关闭，只修改 `.env.example`，实际 `.env` 未动。开启后仅处理第一阶段 borderline 情况，使用既有预算/LLM 通道与 20 秒超时，要求返回现有引用 ID 和逐字原文片段；空证据/明显部分缺失不调用判断模型。判断失败或引文无法复核则不升级证据。它是带原文核验的模型判断，不是已校准 NLI，跨语言/同义表达质量尚未评测。
- 新增 claim-citation-v1：生成提示要求每个事实句使用 `[n]` 引用编号；模型回答返回后、写历史之前逐句检查编号、引用覆盖、词法支持、明显数值不在来源中及否定反转。不存在/越界/超长编号、显式未知引用格式或未批准 URL 直接失败；缺失引用、无关引用、部分句子无支持也失败。普通非事实追问可不带引用，但不会因此置 grounded=true。
- 未通过的原回答不会返回或存入聊天历史，改用既有不足依据答复并清空输出 citations；generation.grounded 根据已通过核验且包含事实句判断，不再只看 rawContext/引用是否非空。grounding 报告包括规则版本、claimCount、citationCoverage、词法 groundingScore、使用的真实引用 ID 和失败原因，与 evidenceAssessment 一并保存 assistant_metadata。现有审核失败与资料不足共用同一提示文案，审计原因可区分。
- 外部 fallback 使用单独的外部引用列表和空课程 rawContext，不带入课程冻结记忆；由服务端添加“课程资料依据 / 外部补充知识”分节，课程不足时不把部分课程资料混成完整课程答案。只有通过核验且实际输出补充内容才置 externalUsed，另返回 groundingScope。课程资料足够时仍不请求外部搜索。
- 新增 18 条 labelled-rule-regression（8 个证据案例、10 个回答案例）并接入统一 quality gate：充分、部分、完全无答案、诱导编造、跨学科、伪造编号、数值/否定修改、无引用及无关引用等边界。离线标签下不足拒答、充分接受、错误回答拦截均为 1.0；这些不是线上拒答率或模型事实准确率。
- 验证：新增 **46 项**回归，完整后端 **682 passed, 3 warnings**；Ruff F、quality gate、diff 检查通过。原 RAG/外部搜索测试改为符合事实句编号的新输出契约，并保留历史记录、主资料优先和外部 fallback 的原验收目的。真实本地 PostgreSQL 回滚验证拒答/空 citations/审计 JSON 的存储及聊天 RLS，临时数据全回滚；未真实调用模型/NLI/外部搜索或写实际用户聊天。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_grounding.py --db --output ../docs/acceptance/GROUNDING_EVAL_20261022.json`、完整 pytest、Ruff F 和 quality gate。无新增表/迁移，审计持久化依赖已安装的 026 metadata；部署需加载新 API 代码和生成提示。本次未重启服务、未改前端页面或用户技术指南，未声明浏览器/真实 JWT/模型质量验收通过。
- 验收：`docs/acceptance/EVIDENCE_GROUNDING_20261022.md`；离线报告 `GROUNDING_EVAL_20261022.json`；进度表已同步。**下一阶段建议补齐 P3 Mind Map：稳定 Topic 权威绑定、状态联动和相关学习工具入口。** 语义蕴含/数学推导、文件名和所有形式的来源主张验证、真实无答案评测/过度拒答率、模型校准、真实检索与生成链路继续保留待办；当前 groundingScore 只是规则支持比例，不是事实正确概率。

## 2026-10-22 — 续作：P3 解析结构与置信度（历史阶段）

- 完成 MinerU / Parse 的首轮结构增量：新增 document_structure_service，在所有新摄取内容块持久化前统一补充 `metadata.documentStructure`（document-structure-v1），保留已解析块的原文、source_hash 和阅读顺序。标注包含标题路径、标题父节点来源、层级来源、图表说明及公式上下文引用；不自动创建 Topic，不推断掌握度。
- 标题层级统一用于章节提案与 Chunk：优先已有 headingLevel / text_level / MinerU 元数据和 Word 样式，再对已识别的 heading 使用编号规则推断，未知默认一级并计数；不把普通正文自动升级为标题。修复 MinerU 无效、布尔或小数层级导致异常/误判的问题。
- 图/表/chart 内的 MinerU caption 字段保留为 provider_field 标注；另行提取的 Figure/Fig./图/Table/表编号说明，只有同页（或双方均无页码）、紧邻且目标唯一时建立双向来源引用。两侧均可能匹配、无匹配或跨页不猜测，标记 ambiguous/unmatched。公式只关联紧邻同页的普通段落，排除标题与图表说明，明确标为 adjacent_candidate，不能视为语义验证结论。
- 修复 Word 原生 fallback 丢失 Heading 样式、先读完全部段落再读表格的问题；按段落/表格交错顺序输出并保留样式。为兼容旧引用，原生 DOCX 的 source_hash 仍按旧 paragraph-then-table 身份规则计算，sequence_index 则使用正确阅读顺序；测试核验旧段落 hash 未变。
- 修复 MinerU 和本地原生文本未报告置信度却保存 1.0 的问题：新解析保存 null；有效上游数值保留，布尔、字符串、越界、非有限数值视为未知。视觉/音频共用数值规范化；缺失视觉分数不伪造 0。MinerU 原始 JSON 的 NaN/Infinity 常量转为 null，避免非有限数值落入 JSONB。保留上游有效分数不代表已做置信度校准。
- 新增 document_structure operation 计数：标题/默认层级、内嵌/邻接 caption、歧义/未匹配、公式上下文、未知/上报/低分置信度。指标不包含原文、标题或文件名；可用时沿用既有 operation_metrics 持久化，记录失败不阻断资料处理。没有新增数据库表或迁移。
- 结构 Chunk 版本更新为 **structure-v2**：保留同页说明与对象的父上下文，child metadata 带结构标注；公式邻段不再跨页强制挤入同一父块。原文 child 内容和 canonical 引用不增加推测文本；关联可能使父块超过目标 parent_size，最终上下文仍受既有展开预算约束。baseline 保持独立块切分，不自动升级旧索引。
- 验证：新增 **38 项**回归，完整后端 **636 passed, 3 warnings**；Ruff F、quality gate 和 diff 检查通过。8 条既有词法 Chunk 对照未回退（baseline 完整证据 Hit@5 0.875、structure 1.0），不代替真实向量检索/解析质量评测。真实本地 PostgreSQL 回滚验证结构元数据/structure-v2 持久化、caption 父块保留、null 置信度、canonical 来源及用户隔离，所有 fixture 回滚。本轮仅改后端，未改前端页面，未声称新增浏览器验收。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_document_structure.py`、完整 pytest、Ruff F、quality gate。依赖既有 040/042 等历史迁移，无新迁移需安装。部署后需加载新 API/Worker 代码；本次未重启既有服务、未重建历史资料、未改实际 `.env` 或用户技术指南，也没有调用真实 MinerU/视觉/ASR/付费模型。
- 验收：`docs/acceptance/DOCUMENT_STRUCTURE_20261022.md`；进度表已同步。已有标题/邻接规则只是首轮，不替代版面理解或真实语义关联；指南要求的 30 页复杂课件人工抽样仍未完成。**下一阶段按指南继续 Evidence / RAG QA：问题覆盖、claim/citation 核验和证据边界回归**，保留解析质量/校准、跨栏 caption、通用 syllabus/自动转录分题、历史来源重建和持续 Worker/浏览器待办。

## 2026-10-22 — 续作：P3 上传后自动 Notes（历史阶段）

- 完成 Materials 第三阶段：主异步上传接口增加可选 `notesMode`，默认关闭；可选 summary / standard / comprehensive / exam_focus。资料页上传前说明范围为最多前 30 个内容块，入库后生成 10 节目标的笔记，复用统一转换现有长度/来源约束；不是整份长资料的完整摘要。旧同步 `/materials/upload` 未扩展自动笔记选项。
- 新增并本地安装 **048_upload_notes.sql**：materials 保存自动笔记模式、稳定请求 UUID、入队确认、准备尝试次数、错误及下次准备时间。新上传随资料插入一起保存申请；同用途成功去重的现有文件可补登记自动笔记，同模式复用原请求，模式冲突返回 409。省略 notesMode 不会取消已有申请，其他模式和额外笔记继续使用手动转换入口。
- 主资料 Worker 只在用户选中自动 Notes 时尝试接入转换，失败不改变资料成功状态。新增每分钟 `sweep_upload_notes`：每轮最多 20 份 ready 资料；准备申请使用 1 分钟数据库领取窗口、最多 3 次自动尝试，错误后可手动重置。笔记生成本身仍使用已有转换 claim / 3 次预算 / 取消语义与每分钟 conversion outbox，不新增材料摄取 outbox。
- 自动笔记始终使用保存的 request UUID 和固定资料/模式/count 参数调用既有 conversion.enqueue。learning_conversions 插入触发器在同一事务内确认对应上传申请，覆盖“入队后 Python 尚未确认即退出”的窗口。生成失败重试沿用原 conversion；取消或删除后不自动复活，删除结果/转换也不会重新登记申请。已有转换的草稿校验、来源复核、Notes/历史/任务结果原子发布及幂等保持不变。
- `material_processing_summary` 批量返回独立笔记状态、模式、错误、范围警告、结果链接、重试条件；资料页补齐准备/排队/生成/成功/失败/取消/删除状态、打开笔记和转换任务入口。笔记失败与资料失败分开显示，生成期间继续轮询。新增 `POST /materials/{id}/notes/retry?subject_id=…`，先检查本人同科目，再沿用已有转换重试预算或重置尚未入队的申请。
- 没有新增隐私表，自动申请字段随 materials 导出/删除；048 的新 RPC 仅 service_role 可执行。没有自动接受章节 Topic、写 topic_coverage 或提高 Mastery。用户未选择自动笔记时不触发新的 Notes 转换或模型调用。
- 验证：新增 **31 项**回归，完整后端 **598 passed, 3 warnings**；Ruff F、离线 quality gate、前端 lint/build、UI 静态检测与 diff 检查通过，最大 chunk **255.79 kB**。真实本地 PostgreSQL 回滚验收覆盖默认关闭/配置约束/归属/同模式去重、准备领取与限次/重置、入队事务内确认、转换去重/Notes 与版本原子发布、结果删除不再生成、无覆盖写入及私有 RPC/RLS。全部临时资料和生成草稿回滚。
- 实际本地 Supabase 汇总只读 API 200、跨科目 404、匿名 401 通过，身份为测试覆盖；笔记发布验收使用固定草稿，没有付费模型、真实用户文件上传或持续运行 broker/Worker。当前没有可调用浏览器工具，真实浏览器/JWT/模型质量及持续 Beat 链路未验收。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_upload_notes.py --api`；`--apply` 仅本地首次安装 048 或刷新本轮函数。其他环境按历史依赖先装 048，再部署 API/前端并重启 Worker 与 Beat（需加载新增补扫计划）；本次未重启既有服务、未改实际 `.env` 或用户技术指南。
- 验收：`docs/acceptance/UPLOAD_NOTES_20261022.md`，进度表已同步。Materials 的用途/失败恢复、章节/Topic 确认、可选自动 Notes 首轮增量已接通；**下一阶段按指南继续 MinerU / Parse：标题层级、图表 caption 和公式上下文关联及解析置信度。** 全资料分批 Notes、可编辑章节深度/边界、通用 syllabus 语义解析、材料完整 checkpoint/outbox/claim 与取消恢复仍待补；音频工具、真实 ASR/浏览器/JWT/持续任务链路继续保留，不进入 P4。

## 2026-10-22 — 续作：P3 Materials 章节与 Topic 提案（历史阶段）

- 已接上轮进度完成 Materials 第二阶段：依据已有 heading 内容块和层级元数据进行逻辑章节划分，保留前言、原始阅读顺序、标题路径、起始页码及各节 block IDs。每个标题生成待确认 Topic；无标题的正文不猜测知识点。只建立章节视图，不改写原文、不拆出新文件，也不重建已有 chunk/检索索引。
- 新增并在本地安装 **047_material_topic_proposals.sql**：material_outlines 保存完整 canonical 内容快照和章节；material_topic_proposals 保存待确认/接受/拒绝状态、版本与稳定 Topic ID。复合外键限制本人同科目同资料来源，认证用户只读，私有 RPC 仅 service_role 可执行。新表已纳入隐私导出，随资料/科目/账户级联清理；已接受的课程知识点不因删除单份资料而被删除。
- `GET/POST /materials/{id}/outline?subject_id=…` 读取/生成章节，`POST /materials/topic-proposals/{id}/decision` 接受或拒绝。服务显式按 500 块分页，避免 PostgREST 默认 1000 条截断；上限 2000 块、60 节、4 MB 来源快照，超限明确拒绝。SQL 验证完整来源快照和全部块的有序分区，不只验证标题。
- 同一来源快照重复生成复用既有批次，保留已接受/拒绝状态；恢复到旧来源快照也沿用对应批次。正文、标题、顺序、页码及结构元数据变化，或资料不再 ready 时，旧批次标记 stale，拒绝继续确认。确认事务锁定资料、提案及已存在来源块，检查版本和当前来源；同一决定重放返回原结果，反向决定冲突。
- 用户可修正提案的知识点名称。接受时复用同名章节 Unit，再通过原 resolve_course_topic/别名机制建立或复用稳定 Topic；新 Topic 保存标题来源引用并归入章节，已有 Topic 的名称/分组/其他用户元数据保持原值，归档 Topic 不会被重新激活。拒绝不写课程知识点。没有写 topic_coverage 或提升 Mastery。
- 主异步资料 Worker 入库成功后尝试生成章节提案；此可选步骤失败只记录通用 outlineWarning，不把可检索资料改为失败，资料页支持手动生成/重新检查。旧资料和旧同步上传通过手动入口补齐。尚未验证真实持续 Worker 调度；没有增加自动模型调用。
- 资料页增加“查看章节提案”展开区域：标题路径、原文标题、页码、块数、编辑名称、接受/拒绝及课程结构入口。来源变化时禁用旧提案确认；有加载/错误/无标题/操作反馈，沿用蓝白工作台风格。UI 静态检查零提示；当前没有可调用浏览器工具，真实键盘、手机布局和浏览器 E2E 未验收。
- 验证：新增 **25 项**回归，完整后端 **567 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build 通过，最大 chunk **255.64 kB**。真实本地 PostgreSQL 回滚验收覆盖完整分区、伪造快照拒绝、CAS/重放/拒绝保留、别名/章节复用、正文失效与快照恢复、归档拒绝、无覆盖写入、RLS/私有 RPC 和删除级联；所有测试数据回滚。实际 Supabase 只读 outline API、跨科目 404、匿名 401 通过，身份为测试依赖覆盖。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_material_outline.py --api`；`--apply` 仅限本地首次安装 047 或刷新本模块函数。其他环境先安装历史依赖（含 029/042/045），再安装 047，部署 API/前端并重启 Worker。本次未重启既有服务、未修改实际 `.env` 或用户技术指南。
- 验收详见 `docs/acceptance/MATERIAL_OUTLINE_20261022.md`，进度表已同步。**下一阶段继续 Materials：上传后自动生成 Notes，复用统一转换的幂等任务与发布机制。** 通用 syllabus 语义解析、从正文提炼 Topic、手动调整章节边界/深度、章节检索绑定、完整阶段 checkpoint/outbox/claim 与取消恢复仍待补；FFmpeg/ffprobe、真实 ASR/模型/JWT/浏览器/持续 Worker 验收继续保留。

## 2026-10-19 — 续作：P3 Materials 用途与失败恢复（历史阶段）

- 完成 Materials 的第一阶段增量：上传可选择课程资料 `learning`、课程大纲 `syllabus`、参考资料 `reference`，同步和异步上传均校验并保存 `materialPurpose`。旧资料默认课程资料；用途目前用于分类，不自动创建考试、Topic 或 Notes。大纲上传后可从资料页进入既有日历考试候选流程。
- 本地已安装 **046_material_purpose_recovery.sql**：用途约束、按资料查询最新 ingestion 任务的索引、私有处理汇总/重试/投递失败 RPC。汇总按本人和科目查询，每份资料只取最新 ingestion 任务，不受通用任务列表最近 100 条限制；原文件可用性根据资产记录与保留期限判断，不代表远端对象已实际下载成功。没有新增隐私表，资料用途随原 materials 导出/删除。
- 资料页显示用途、处理进度、自动重试次数，以及读取原文件/消息投递/parsing/embedding/indexing 的失败阶段。失败且原文件记录有效时显示“重试处理”；无源文件或过期则提示重新上传。原文件上传失败、无任务的历史失败记录显示重新上传。跨科目切换重置页面并丢弃迟到的加载结果；补齐键盘上传入口、窄屏布局和长文件名换行。
- 手动重试通过事务锁定任务和资料，仅接受 failed ingestion；检查归属、原文件期限、资料状态和其他活动任务。重试重新开启一轮原有有上限的自动尝试，保留 previousAttempts、manualRetryCount、MinerU batch 和 failedStage，避免自动重试耗尽后永远无法手动恢复。重复提交返回冲突；新上传的相同文件已入库时，旧失败资料重试受唯一索引保护并整笔回滚。课堂音频重试入口同步适配该语义。
- broker 投递异常不再直接留下 queued 记录：事务标记 dispatch_failed 和 failedStage=queued，文件仍保留供手动重试；已运行任务不被丢失确认消息改回失败。Worker 的原文件查询和下载纳入统一异常处理，耗尽尝试后同步标记任务和资料 failed，并记录实际失败阶段；异常返回时已取消的任务不覆盖成失败。这里只补失败恢复，**未实现 material outbox、租约 claim 或所有取消竞争的原子栅栏**。
- 同文件去重提前到新增任务/日配额检查之前，重复上传不消耗新配额；不同用途的已存在文件返回明确冲突，保留原分类。新文件的 Storage 路径加入 material ID，避免失败后重新上传撞到遗留对象；失败文件不参与旧的成功去重条件，仍受上传配额约束。上传持久化仍跨 DB/Storage，并未声明完整分布式事务。
- 验证：新增 **21 项**回归，完整后端 **542 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build 通过，最大 chunk **255.23 kB**。Materials 静态 UI 检测零提示；Lectures 原有一条互斥配色提示保留并已代码核对。当前无可调用浏览器工具，未执行真实文件选择、键盘和手机布局 E2E。
- 真实本地 PostgreSQL 回滚验收通过：用途默认/非法值、汇总隔离、无源文件/过期拒绝、耗尽后手动重试、重复重试冲突、投递失败/运行任务保护、唯一哈希冲突回滚、RLS 和私有 RPC 权限；全部临时行回滚。真实本地 Supabase 只读 materials/processing API、跨用户科目 404、匿名 401 通过；认证为测试依赖覆盖，未调用真实模型、上传用户文件或持续运行 broker/Worker。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_ingestion.py --api`；首次本地安装缺失 046 可加 `--apply`。其他环境先安装 046，再部署前后端并重启 Worker；本次未重启既有服务、未修改实际 `.env` 或用户技术指南。
- 验收：`docs/acceptance/MATERIAL_RECOVERY_20261019.md`；进度表已同步。**下一阶段继续 Materials：章节拆分与有来源证据的 Topic proposals / Accept / Reject，再接上传后 Notes。** 通用 syllabus 语义解析、阶段断点续跑、可靠 material outbox/claim 和取消恢复仍待实现；FFmpeg/ffprobe 与真实 ASR/浏览器/JWT/持续任务验收继续保留，不进入 P4。

## 2026-10-19 — 续作：P3 Live Lecture / 课堂录音（历史阶段）

- 完成录制后处理的第一轮代码：`/lectures` 页面/API，浏览器开始/暂停/继续/停止录音、停止后回听/下载与账户/科目隔离的 IndexedDB 草稿，上传已有音频或将已有音频资料加入课堂。退出页面停止麦克风，权限请求晚到也会释放音轨；原音频上传成功且课堂保存完成后才清理本地草稿。录制中刷新/关闭仍可能丢失未完成录音，页面提醒先停止并下载；未声明实时字幕已实现。
- 本地已安装 045：lectures、lecture_topic_links、私有 attach/align/transcript RPC。课堂按本人音频 material 去重，Topic 对齐按课堂版本 CAS；来源块/课堂/Topic 复合外键限制本人同科目。转录原文或时间变更、Topic 归档后，旧关联不再作为当前映射返回。支持解除关联，不修改原文、不自动写覆盖或 Mastery。新表纳入隐私导出，随资料/课程/账户级联清理。
- 复用既有音频摄取、分段缓存、转录和知识库索引；课堂显示处理任务、分段进度与失败重试。分段转录按 50 条分页（API 上限 100），支持定位 50 条之后的具体片段；私有原音频通过既有短时签名 URL 回听、刷新链接及按时间跳转。Topic 当前为人工确认，未新增自动分题/自动 Topic 映射或按 Topic 重建检索索引。
- 浏览器 WebM 新增 MIME 规范化与 EBML 文件头校验；无 format.duration 时回退扫描音频包时间，拒绝非有限/无效时长。WebM 无论长短均先转为 WAV 再交给既有转录服务。真实 FFmpeg 转码本机尚未验收，控制流使用模拟二进制响应验证。
- 修复相同句子跨音频分段的 source_hash 冲突，新的块标识加入绝对时间/分段信息；ASR 时间检查有限值、顺序和物理音频分段边界，末尾 0.5 秒内舍入误差对齐到物理末尾，其余越界拒绝。没有逐句时间时标记 segment_window；未提供识别置信度保存 null，不再伪造 100%。旧时间/置信度标注提示回听核对，没有自动重建历史音频或其引用。
- 统一转换支持 material 来源可选 blockIds（1–30、唯一且必须属于所选资料）；课堂选中一段转成 Notes/Flashcards/MindMap/Quiz，仅使用该段 canonical 原文/时间引用，继承当前有效且未归档的人工 Topic。历史记录可返回具体课堂片段；无 blockIds 的旧参数指纹及浏览器待确认请求键保持兼容，原有 14 类组合保持。不是新增 lecture 专用来源类型，也未接实时课堂 Tutor。
- 验证：新增 **29 项**回归，完整后端 **521 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **254.95 kB**。UI 静态检测一条互斥条件配色提示，经代码核对；没有可调用浏览器工具，真实麦克风、IndexedDB、播放/键盘流程未做浏览器 E2E。
- 真实本地 PostgreSQL 回滚验收通过：仅限音频/归属/重复挂接、Topic CAS/归档/解除/原文变化、无 Mastery 变化、121 段分页与片段定位、复合外键及只读 RLS/私有 RPC；临时记录全回滚。真实 Supabase 只读课堂/音频列表/能力及转换历史查询 200、匿名 401、跨用户科目 404 通过；身份为 TestClient 覆盖，没有实际用户音频写入或付费 ASR 调用。
- **运行前置未满足：当前 API 环境未找到 FFmpeg 与 ffprobe。** 能力 API 会报告音频处理不可用，前端禁用新音频上传处理但保留录音下载和已有课堂查看。配置两个可执行程序到 API/Worker PATH 并重启后，仍须真实 ASR/解码与持续 Worker/存储链路验收；能力探测仅代表 API 进程，分布式部署需统一依赖。既有上传任务的消息投递/取消恢复限制保留，未宣称新增摄取 outbox 或恰好一次转录。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_lectures.py --api`；`--apply` 仅本地安装缺失 045 或刷新本模块 RPC。其他环境需先有历史依赖（含 020/029/040/042/043），再装 045、配置音频工具/真实 ASR 并重启后端/Worker。本次未重启服务、未改实际 .env 或用户指南，未下载外部二进制。
- 验收：`docs/acceptance/LIVE_LECTURE_20261019.md`；进度已更新 `docs/OPTIMIZATION_PROGRESS.md`。下一建议为 **Materials / Ingestion**：用途、阶段恢复、章节/Topic 提案及上传后 Notes；音频依赖/真实 ASR、实时流式字幕、自动转录分题、浏览器/JWT 和持续任务链路继续保留待办，不进入指南暂缓的 P4 功能。

## 2026-10-19 — 续作：P3 Calendar（历史阶段）

- 按用户选择完成“月历＋当天任务”第一轮：全局 `/calendar` 页面与 API，42 格周一开头月历、今天/月份切换、全部科目/当前科目筛选；聚合活动考试、活动计划任务、到期闪卡。跳转学习、考试目标计划或闪卡前切换到对象所属科目；日期与逾期判断统一 Asia/Shanghai。
- 新增并安装本地 044：calendar_availability 保存个人逐日总分钟与版本，calendar_exam_proposals 保存资料证据、考试候选及确认关联。认证用户只读本人记录，变更 RPC 仅 service_role 可执行；个人日预算纳入隐私导出和清空学习数据，候选沿课程/资料外键级联。
- 可用时间在全部科目间共享，保存采用版本 CAS，并标记相关活动计划待重排。Study Plan v3 预览/生成扣除其他活动计划的日占用，保留本计划受保护任务；不将较大的个人总预算误当作提高单科每日预算。原用户时间偏好独立保存，后续重排重新读取共享容量。
- save_study_plan_v3 增加按用户事务锁和保存后总量复核，超过已设置日容量则整笔计划/任务写入回滚。旧实现改为内部 save_study_plan_before_calendar，撤销 service_role 直接执行权限，避免绕过容量复核。未设置日预算的日期继续沿用原计划默认值，不承诺跨科目总量；手动编辑/受保护任务可导致超额，日历显示冲突并保留任务。
- 尚未开始、未锁定的 system 任务可通过日历改期到今天至计划目标日之间；目标日必须先设置个人容量。RPC 校验计划版本、所有科目的日占用，事务内改期、锁定及写调整记录，后续自动重排保留日期。完成、手工和锁定任务不可用该入口移动；过期目标提示重新制定计划。改期不会冒充学习完成或提升 Mastery。
- 从现有资料中心上传并解析好的大纲提取考试候选：保守规则识别明确年份的考试行（含指南示例 Final Exam: 2026-12-20 / Chapter 1-6），保留后续块原文/页码；最多前 500 个内容块、20 个候选。用户可更正名称/日期并手动选择稳定 Topic；确认时重新核验证据，同事务创建考试/范围及候选关联，重复确认返回同一考试。确认后可直接进入带 examEventId 的计划页面。没有自动猜年份、章节映射或完整大纲语义解析。
- 冲突包括跨科目已排分钟超出总预算，以及跨科目同日多场考试（即使当前科目筛选也提示）。闪卡以北京时间到期日期汇总，今天包含逾期卡；归档 Topic/卡片排除，无 Topic 历史卡与原队列保持一致。仅提供日粒度信息，尚无考试起止时间/时段冲突、定时学习预约或外部日历同步。
- 验证：新增 **32 项** Calendar 回归，完整后端 **492 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **253.83 kB**。静态 UI 检测有两条同一条件表达式的灰字/蓝底提示，代码核对为互斥配色分支；没有浏览器工具，未声明渲染/交互 E2E 通过。
- 真实本地 PostgreSQL 事务验收通过：预算 CAS/边界、跨科目容量与计划失败回滚、个人/筛选汇总、归档与无 Topic 闪卡、同日多考、保护任务/改期/锁定、候选确认重放/归属/证据变化、只读 RLS 和私有 RPC；临时行全回滚。实际 Supabase 只读日历 API 200、跨用户科目 404、匿名 401 通过，认证为 TestClient 覆盖；未调用付费模型或写入实际用户考试。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_calendar.py --api`；`--apply` 严格限本地安装缺失 044 或刷新本模块函数/索引。其他环境先具备历史依赖（含 029/032/036/038/042），安装 044 后再重启后端/Worker；继续运行既有 Beat 才会自动处理待重排计划。本次未重启服务、未修改实际 .env 或用户技术指南。
- 详情：`docs/acceptance/CALENDAR_20261019.md`；进度已更新 `docs/OPTIMIZATION_PROGRESS.md`。下一阶段按指南 P3 顺序为 **Live Lecture**，先核对转录与摄取链路；Materials 的用途/章节 Topic 提案/上传后 Notes、通用大纲解析、定时预约、跨时区/浏览器与持续 Beat 全链路保留待办。

## 2026-10-09 — 续作：P3 Unified Turn Into（历史阶段）

- 完成统一转换第一轮：`/conversions` API、共享 TurnInto 组件、“转换学习方式”页面 `/convert`。资料→Notes/Flashcards/MindMap/Quiz，已保存 Notes→Flashcards/MindMap/Quiz/Tutor，导图节点→Flashcards/Quiz/Tutor，错题→Tutor/Notes/Flashcards，共 14 个支持组合；非法组合/客户端伪造上下文返回 422。资料中心文件、Notes、导图详情均接入统一入口。
- 本地已安装 043：learning_conversions 持久化来源内容/课程证据快照、来源版本/节点、参数指纹、任务与生成结果。来源/结果复合外键绑定本人同科目，支持按来源或结果双向查记录；页面可打开原来源及具体结果，Notes/导图/测验/闪卡跳转按对象 ID 定位。隐私导出包含转换记录，课程/账户删除沿外键级联。
- 用户请求 UUID+参数指纹幂等，重放先返回原任务；同编号换参数返回 409。入队与 processing_tasks 同事务；原始课程引用核验后只生成内存草稿，私有 RPC 原子发布产物、Topic/来源/历史或测验全套记录，并完成任务。取消、过期 claim、来源变更、错误结果均不能留下部分输出。一次任务最多 3 次执行，running 超过 20 分钟可重领，旧执行者由 claim token 隔离。
- 新增 Worker `process_conversion` 和 Beat 每 60 秒投递 queued/过期 running 的 outbox 补扫。Broker 投递失败保留已落库任务，待 Beat 恢复；任务取消/重试走统一行锁 RPC。来源或结果删除会清理转换关联，并取消仍在执行的任务。保证同任务最多一次结果发布；故障重领可能再次调用模型，不承诺模型调用/计费恰好一次。
- 错题上下文读取本人、同科目的原考试题目版本、实际学生答案/评分、正确答案/解析、错误类型、knowledgeKey/Topic 与课程证据；正式考试需 attempt=graded，不能借转换提前泄露答案。Tutor 由服务端 conversionId 载入冻结上下文，支持既有教学角色，强制 course_only，并在使用前重新核验课程来源。转换与讲解不提升 Mastery。
- 前端保留账户隔离的待确认请求，网络错误/刷新可继续原请求；任务历史持久化并轮询，支持取消/限次重试。Notes 未保存时阻止转换；原内容和草稿保留。资料最多用前 30 个内容块并明确提示；本轮 Quiz 固定为 1–20 道单选、每题 5 分、30 分钟的 adaptive practice。打开原来源显示其当前版本，转换使用的历史版本保留于任务快照。
- 验证：新增 **46 项**后端回归，完整后端 **460 passed, 3 warnings**；Ruff F、quality gate、前端 lint/build、diff 检查通过，最大 chunk **253.00 kB**。共享转换/新页面/Notes/Tutor/导图详情机械检测无提示。真实本地 PostgreSQL 回滚验收覆盖幂等/重复执行、取消/旧 token、过期重领、重试上限、原子产物/Notes/Quiz、来源变更、来源删除取消、来源/结果归属和只读 RLS；临时数据全回滚。
- 实际 Supabase 只读转换列表/capabilities 200、跨用户科目 404、匿名 401 通过；认证为测试依赖覆盖。Worker 编排/生成器/Tutor 上下文为自动回归和 SQL 验收，持续 Redis/Celery/Beat、真实模型、真实 JWT/浏览器全链路尚未执行。旧 `/notes/{id}/convert` 同步接口标为 deprecated 并保留兼容，仍无新统一接口的事务幂等语义；新 UI 全部走 `/conversions`。
- 复跑：`cd backend` 后 `.\.venv\Scripts\python.exe scripts/verify_conversions.py --api`；`--apply` 只允许本地安装缺失 043/刷新该文件的 RPC（不是通用升级器）。其他环境须先安装 029/038/040/042 及其历史依赖，再安装 043、重启后端/Worker 并启动 Beat。本次未重启运行服务、未改实际 .env 或用户指南。
- 验收详情：`docs/acceptance/UNIFIED_TURN_INTO_20261009.md`；进度已更新 `docs/OPTIMIZATION_PROGRESS.md`。下一阶段按指南 P3 顺序为 **Calendar**。QuizResult→Tutor/Flashcards/StudyPlan、通用导图节点 Topic 权威、其他对象统一版本、全资料分批转换、旧接口最终移除与持续事件 E2E 保留待办。

## 2026-10-09 — 续作：P3 Notes / Artifacts（历史阶段）

- 完成 Notes 第一轮实现：独立 `/notes` API 与“学习笔记”页面，支持 summary / standard / comprehensive / exam_focus、课程资料/范围筛选、可选稳定 Topic 绑定、章节标题/正文/引用编辑、JSON/Markdown 导出。通用 artifact_type 增加 notes，原 outline/闪卡/导图行为继续保留。
- 新增并安装本地 042：artifact_versions、note_sources、Notes 版本触发器、canonical 来源 RPC 与私有 save_note。保存通过行锁与 expected version 完成 CAS，在一个事务内更新笔记、Topic/来源关联及历史；失败回滚，旧版本冲突返回 409。恢复历史生成新版本，不覆盖历史。普通认证用户只能读取 Notes/来源/历史，不能直写 Notes 或改其 Topic 关联。
- 每节必须引用本人、同科目、ready 资料的真实 content block；正文来源快照含文件名、页码/时间/坐标。服务与 SQL 两侧校验引用，保存时移除不再使用的来源关联。模型生成结构/引用错误最多修复两次；这是可追溯结构约束，不等于已证明每个观点都被证据蕴含。
- 局部 AI 改写核验已保存版本、章节、Unicode 字符偏移及选中文本；引用限定为该章节来源，模型返回后再次检查版本。只返回预览，用户应用到草稿并保存后才落库。前端处理版本冲突/重新读取、按账户隔离的 sessionStorage 草稿、旧版本草稿复制、未保存切换提示与刷新提醒。
- Notes 可转换为 Flashcards / Quiz / MindMap：复用已有生成器，只使用该笔记的 canonical 课程来源；传入笔记内容供重点提示，仍要求原始资料为依据。记录 sourceArtifactId/sourceArtifactVersion；测验强制 course_only。通用跨工具对象、事务外键式双向追踪、异步任务/幂等仍属于下一阶段，未声明全部 Turn Into 完成。
- 验证：新增 **44 项**后端回归，完整后端 **414 passed, 3 warnings**；Ruff F、统一 quality gate、前端 lint/build、git diff --check 通过，最大构建 chunk **251.83 kB**。Notes UI 机械检测最终无提示；当前没有可调用浏览器工具，真实 UI/JWT E2E 与真实模型笔记质量 N/A。
- 真实本地 PostgreSQL 验收覆盖 canonical 页码/原文、Topic/来源原子关联、不可变历史、stale CAS/错误输入回滚、恢复为新版本、跨用户与只读 RLS，所有临时行回滚。实际 Supabase 私有来源 RPC 与 Notes 列表 API 200、匿名 401、跨用户科目 404 通过；认证为测试依赖覆盖，未生成实际用户笔记或调用付费模型。
- 复跑：`cd backend` 后运行 `.\.venv\Scripts\python.exe scripts/verify_notes.py --api`；`--apply` 仅限本地安装缺失 042 或刷新该迁移中的 save_note。其他环境需先具备 029/040 并安装 042，再重启后端；此次未重启服务、未改实际 .env 或用户技术指南。隐私导出纳入 artifact_versions/note_sources，课程/账户删除沿现有外键级联。
- 独立验收：`docs/acceptance/NOTES_ARTIFACTS_20261009.md`；进度已更新 `docs/OPTIMIZATION_PROGRESS.md`。下一阶段按指南 P3 顺序推进 **Unified Turn Into**；Mind Map 的 Topic 权威、其他产物通用版本/并发保护、上传后自动 Notes、Guided 持久化 Notes、浏览器与模型质量继续保留待办。

## 2026-10-08 — 续作：P2 Recommendation Evaluation

- 完成第一轮推荐评测：新增 `backend/evals/recommendation_cases.json`，24 条人工指定预期的合成快照，固定时间，覆盖冷启动/覆盖不等于掌握、薄弱点、掌握后暂不推荐、到期复习、高信心错误、闪卡回忆风险、考试范围/权重、归档/过期/跨科目映射、上海日期边界与确定性排序。
- 独立理由审计直接核对源快照，不调用推荐评分器或 learner-state 投影验证自身；核验掌握度、到期时间、评估计数、风险标记、考试状态/日期/范围/科目与导航目标。未知/伪造理由、缺失理由、遗漏案例要求的关键理由、重复/越界推荐均使门禁失败；无理由分母时 faithfulness 为 null，不记为 100%。
- 生产规则版本更新为 `next-action-v2`：考试映射先排除跨科目、归档/未知 Topic 再归一化权重；推荐理由明确显示闪卡回忆失败；todayTasks 稳定排序后取前 10 条。API 字段与前端兼容，无新迁移、无实际 .env 修改或服务重启。
- 离线结果：Top-1 Hit **22/22**，暂不推荐判断 **2/2**，Reason Faithfulness **43/43**；24 条快照范围一致性和反向输入确定性全部通过。这是合成规则回归，不能替代真实用户推荐质量、数据库授权或学习效果指标。详细结果 `docs/acceptance/RECOMMENDATION_EVAL_20261008.json`。
- 推荐专项 **50 passed**，完整后端 **370 passed, 3 warnings**；Ruff F、统一离线 quality gate 与 git diff --check 通过。新测试含错误排序、伪造掌握/到期/风险/考试日期、跨科目考试链接、缺失风险理由、泄露/重复推荐与不稳定待办等反例，确认门禁能失败。
- 真实本地 Supabase / TestClient 只读联调：推荐 API 200，当前课程 1 条推荐 / 1 条理由源快照审计通过；匿名 401、非法 limit 422、跨用户科目 404。认证为测试依赖覆盖，未写数据库；真实 JWT/浏览器 E2E 与其他课程样本仍待验收。
- 复跑：`cd backend` 后执行 `.\.venv\Scripts\python.exe scripts/evaluate_recommendations.py`、`scripts/run_quality_eval.py`、`scripts/verify_recommendations.py`（均用同一 Python）；独立验收 `docs/acceptance/RECOMMENDATION_EVALUATION_20261008.md`。每次修改推荐规则/理由同步更新标签、审计模板与算法版本，并检查逐条失败原因。
- 下一阶段按指南推进 **P3 Notes / Artifacts**。P2 推荐已完成第一轮技术实现，真实数据标注、用户采纳率、学习增益与长期实验继续保留待办；此前模块的质量/E2E 限制仍有效。

## 2026-10-08 — 续作：P2 Chunk / Parent-child

- 完成首轮结构化切分：保留原 800/120 baseline；新 `structure-v1` 优先标题/段落/句子边界，识别 DOCX/MinerU 标题层级；过长句子才退回固定窗口。表格按完整行与重复表头切分，超长单行/不透明 HTML 表格保持原子片段并标记 oversized；公式与相邻解释保留在同一个父组。
- 新增并安装本地 040/041：parent_chunks / parent_chunk_blocks / parent_chunk_id、复合归属与成员外键、owner 只读 RLS、私有父上下文 RPC、子片段全文索引与关键词查询。结构化资料三路检索以 child 为证据单位，关键词/向量/Graph 共享 chunk ID；引用同时保留原 content block 与页码/时间/坐标。
- 新摄取默认 structure，可用 CHUNK_STRATEGY=baseline 保留原算法；只向 children 生成 embedding/图谱索引。父子 bundle 单事务替换、失败回滚、清除旧尾部 chunks，阻止重试遗留旧记录；历史现有资料默认 baseline，未执行全量重建或外部付费索引调用。
- adaptive 获取 canonical 父组成员，逐块执行原 material/type/page/time/confidence 范围并限制上下文预算，命中子片段始终保留原文/位置；旧 baseline 资料可通过同样的有来源信息页内成员补充。父级内容不覆盖 child 的 chunkText，RAG 把补充块作为独立引用保存到历史并纳入证据判断。未知父关系/读取失败保留 child 并返回 warning。
- 完整后端 **327 passed, 3 warnings**；Ruff F、git diff --check 通过。真实 PostgreSQL 原子替换/错误回滚、父级多页读取、child 关键词、归属/RLS、基线切换验收通过，所有临时记录回滚。实际 Supabase 父上下文 RPC、关键词 baseline/adaptive API 及跨用户 404 通过，模型/向量/Graph 路径显式禁用。
- 新增 8 条 chunk quality fixture 与离线对照：完整证据 Hit@5 **0.875 → 1.0**，完整证据 MRR **0.71875 → 0.84375**；这是共享词法比较器下的边界回归结果，不代表真实 Recall@5 / 模型质量 / P95 已达标。报告 `docs/acceptance/CHUNK_COMPARISON_20261008.json`；独立验收 `docs/acceptance/PARENT_CHILD_CHUNKS_20261008.md`。
- 验证命令：`cd backend; .\.venv\Scripts\python.exe scripts/verify_parent_child_chunks.py --api`（`--apply` 仅安装本地缺失迁移）；`scripts/evaluate_chunk_strategies.py` 运行离线用例。生产/其他环境须先安装 040/041，再重启后端和 Worker；此次未重启服务、未改实际 .env，也未改用户技术指南。
- 本阶段未改前端；下一阶段为 P2 Recommendation Evaluation。真实双索引 Recall@5 对照、学习质量、长表格/超长句参数校准与持续 Worker 端到端验收继续保留待办。


## 2026-10-08 — 续作：P2 Retrieval / Reranker（当前入口）

- 完成第一轮管线实现：统一候选 K（默认 20）、definition/problem/comparison/general 分类与动态 K（3/6/8/5，显式 topK 优先），保留定义/关键词改写，新增来源多样性选择与 `strategy=baseline` 的无 rerank 对照。
- 新增 Reranker 接口：none、开发 lexical、可配置 HTTP `/rerank` 服务；响应必须是完整索引排列及有限 [0,1] 得分，只接受分数，不接收服务返回的文本/ID。超时/畸形响应回退原 RRF 候选并记录 warnings；默认 none，未静默启用外部模型。HTTP 使用独立配置/密钥、关闭代理继承/重定向，接入预算检查与调用日志，价格参数需按服务配置。
- 修复三路筛选不一致与未筛选图谱原文进入回答上下文的问题：Graph 仅用 marker 定位本人、同科目、ready 资料的真实数据库 chunk；核验失败舍弃候选。所有来源统一 material/type/page/time/confidence 过滤，仅最终选中证据构造 rawContext；类型/信心/时段限定查询不会扩入被排除的页内内容。
- 新增并安装本地 039：关键词检索同时核验内容块与资料的 user/subject，防止历史松散外键下伪造 owned block 引用他人资料。向量 SQL 增加同样的资料归属 join；Graph 已双侧核验。
- `evaluate_live_retrieval.py --compare` 可用同一标注集比较 baseline/adaptive，报告 Recall@5、MRR、Citation Precision/Hit Rate、Isolation Rate、Latency P95，并保存每条结果及实际 reranker/fallback。支持 `EXAMAI_EVAL_TOKEN`，不用把令牌写入命令行。
- 验证：完整后端 **318 passed, 3 warnings**；Ruff F、git diff --check 通过。真实 PostgreSQL owner/subject/material/伪造关联/RLS 隔离验收通过，测试行全回滚；实际 Supabase 关键词 baseline/adaptive API 200、跨用户 404。卡片阶段前端 lint/build 通过，后续此模块未改前端。
- 详情：`docs/acceptance/RETRIEVAL_V2_20261008.md`。HTTP adapter 只做了模拟协议测试，真实 Cross Encoder、代表性数据质量/延迟对照仍 N/A；parent-child 结构切分尚未完成。下一阶段继续 Chunk / Parent-child，再推进 Recommendation Evaluation；其余未完成项保留在进度表。


## 2026-10-08 — 续作：P2 卡片级间隔复习

- 完成第一轮实现：每张卡片独立保存 difficulty/stability、最后复习/下次到期、复习/遗忘次数和版本；支持 Again / Hard / Good / Easy、到期队列、逾期统计、最近 50 条历史及首页/侧栏入口。
- 新增 038 并安装本地：旧卡组回填规范化卡片，缺少 ID 时使用稳定 `legacy-N`；回填不修改原始产物 JSON 或更新时间。编辑卡面/答案/Topic、恢复删除的卡片会重置该卡状态，历史保留；归档 Topic 和移除卡片不进入队列。
- 复习 RPC 在同一事务提交卡片状态、Mastery、绩效历史和学习事件；请求 UUID 幂等、卡片版本及 Mastery 时间戳冲突返回 409，跨用户不可读写。旧客户端可省略请求编号/版本，但只有携带编号的调用能跨网络重试幂等。
- 闪卡自评不增加 assessmentCount 或评估置信度；曾掌握 Topic 的 Again 设置回忆风险并清零评估正确连续次数，后续闪卡 Easy 不清除风险，需要三个连续客观评估正确。Mastery 更新触发现有 Study Plan v3 重排标记；持续 Worker/Beat 链路仍待验收。
- Guided 闪卡步骤改读持久化卡片进度，刷新后已评价状态恢复；完成验证读取当前内容版本的复习次数，旧内容的历史评价不能冒充完成。
- 验证：后端完整 **303 passed, 3 warnings**；前端 lint/build 通过，最大 chunk 250.65 kB。真实 PostgreSQL 事务验收及真实 Supabase 只读 API 联调通过，所有验证行回滚。脚本 `backend/scripts/verify_flashcards.py --api`；`--apply` 仅安装本地缺失迁移。
- 验收详情：`docs/acceptance/FLASHCARD_SCHEDULER_20261008.md`。调度为可解释的 `card-scheduler-v1` 启发式，尚未实现/校准 FSRS；真实 JWT、浏览器流程、长期记忆效果及多时区仍待验收。下一模块为 P2 检索 / reranker。


## 2026-10-07 — 续作：Study Plan v3（当前入口）

- 本次 P1 三模块均已完成第一轮实现：引导学习、Formal/Adaptive 分离、计划 v3；仍有独立诊断、AI 学习质量与浏览器 E2E 等待验收，不能声明指南全部功能完成。
- Plan 支持考试目标/范围权重与三种 Mode、逐日时间覆盖、任务锁定、事务重排、变更/逾期信号和调整记录；先扣除受保护任务时间，失败保留原计划。新增 Celery Beat 每五分钟执行确定性重排，旧 v2 计划需先生成 v3；运行环境须重启 Worker 并另启 Beat。
- 036 本地事务验收通过；真实 Supabase + TestClient 的会话列表、计划读取与三种 Mode 预览通过，跨用户列表/预览均 404。冷启动信心字段缺失已修复并加回归。
- 本地实际缺少 026，已仅补安装这一历史依赖。033–037 均已安装；037 限制 processing_tasks/learning_events 直写，learning_interactions 保持后端独占，防止伪造会话完成凭据与暴露评价答案。所有数据库验收数据全回滚。
- 详见 `docs/acceptance/STUDY_PLAN_V3_20261007.md`，另有 Guided / Adaptive 独立验收文档。模块进度和后续依赖以 `docs/OPTIMIZATION_PROGRESS.md` 为准。
- 最终回归：后端 **287 passed, 3 warnings**；Ruff F、前端 lint/build 通过，最大 chunk 250.07 kB。以下较小测试数字为各模块完成时的阶段证据。
- 下一优先级：P2 卡片级间隔复习，再推进检索/reranker、parent-child chunk 与推荐评测。当前没有可调用浏览器工具，真实 UI/AI 全链路学习质量 N/A；持续 Beat/Worker 事件链路尚未验收。

## 2026-10-07 — 续作：Adaptive Quiz / Formal Exam

- 已完成第一轮模式分离、Formal 保存/整卷提交与结果隐藏、Adaptive 逐题反馈与三类 Stop Policy、暂停复习记录/恢复，接入 Guided Study。
- 数据库行锁维护最近五题窗口；暂停不能绕过保存/确认/提交。固定答案、未提交正式评分以及模式/评分/Mastery 写入均加 RLS 限制；重复评分不重复提升 Mastery。
- Adaptive + Guided 专项 31 passed；前端 lint/build 通过。035 已安装本地；真实 PostgreSQL 三类暂停、恢复、跨用户隔离和正式评分释放验证通过，验收数据全回滚。
- 详见 `docs/acceptance/ADAPTIVE_ASSESSMENT_20261007.md`。复习记录是用户自述，尚未实现独立诊断评估；真实浏览器/模型评分与跨服务补偿待验收。
- 继续推进 Study Plan v3；P2/P3 仍按进度索引保留未完成项。

## 2026-10-07 — 续作：Guided Study Session（当前进度）

- P1 引导学习已完成第一轮实现与技术验证：持久化步骤、预算编辑、确认、逐步执行、跳过、取消、刷新恢复与学习总结；首页推荐进入 `/guided-study?topicId=...`。
- 完成凭据由后端验证，阅读只记覆盖，闪卡不计 assessment，苏格拉底需实际互动评估完成，测验需本人同科目且属于该步骤试卷的 graded attempt。未达标追加最多两轮补习/重测。
- 新增 033/034 已安装本地数据库。会话与信心专项 27 passed；前端 lint/build 通过。数据库版本冲突、事务回滚和跨用户 RLS 验证通过，测试记录全部回滚。
- 详见 `docs/acceptance/GUIDED_STUDY_20261007.md`。本阶段仍在继续 Adaptive Quiz 与 Study Plan v3，尚不能把指南全部 P1 标为完成。
- 下文各阶段数据是历史证据，以此处及后续新记录为当前状态。真实浏览器和 AI 学习效果验收尚未执行。

## 2026-10-07 — 指南优化：Next Best Action / Dashboard（当前入口）

> 本轮进度索引：`docs/OPTIMIZATION_PROGRESS.md`。详细交付证据：`docs/acceptance/LEARNING_FOUNDATION_20261007.md`。
> 本轮为 P0 基础与首页推荐的阶段性交付，指南其余模块继续按优先级推进，不能声明整个规划完成。

- 新增 `/api/v1/recommendations/next-actions`，统一返回 Top 3、近期考试、到期复习数、薄弱 Topic 与今日待办。计算使用权威数据库状态，推荐结果不采用浏览器快照。
- Next Action 基于统一 Need Score，增加考试日期/范围/相对权重、到期复习与误解风险；返回原因和分数组件。不在考试范围内的 Topic 无考试加权；已结束/归档考试不加权，已掌握且未到期 Topic 不强制推荐。
- 首页新增“现在建议做什么”，开始动作先切换科目，再进入带 Topic 参数的学习室/练习；没有 Topic 时提示建立课程目录。推荐读取失败显示错误，不伪造建议；冷启动明确标注证据不足。
- 查询按用户/可选学科限制，使用批量查询、必要字段投影与分页，避免每个科目重复查询及 PostgREST 1000 行截断。
- 验证：最新完整后端 **243 passed, 3 warnings**；前端 TypeScript 检查与生产构建通过，最大 chunk 248.29 kB，无大 chunk 警告。推荐测试包括 3 天后考试的薄弱 Topic 优先、范围权重、过期/归档排除、冷启动、已掌握/到期状态、所有者范围与分页。确认答题重放不重复更新 Mastery 的回归已补齐。
- 本地真实 Supabase + TestClient 只读联调：structure、learner-state、exam-goals、next-actions 均 HTTP 200；跨用户结构/推荐读取均 404。此联调覆盖新代码与真实数据库，但使用认证依赖覆盖，不替代真实 JWT/浏览器 E2E。
- 本地 029–032 迁移均已安装；验证数据全部事务回滚。新增脚本：`cd backend; .\.venv\Scripts\python.exe scripts/verify_course_structure.py --api`，默认验证；`--apply` 仅安装本地缺失迁移。
- 尚未完成：Guided Session、Adaptive Quiz、Study Plan v3、自动大纲/章节解析、卡片级排期、reranker、parent-child chunk、统一 Turn Into、事件驱动重排及真实浏览器/AI 质量验收。当前推荐直接进入既有学习工具，不能宣称已启动 Guided Session。
- 应用日程解释使用 Asia/Shanghai（UTC+8）。多时区配置与个性化可用时间尚待 Study Plan/Calendar 模块。
- 本轮未修改用户已改动的 `PROJECT_TECHNICAL_INTERVIEW_GUIDE.md`；未创建提交。长期运行的无 reload 后端需按现有启动流程重启，才能提供新代码中的路由。
- 最终首页强调文本调整后，`npm run lint`、`npm run build` 再次通过，最大 chunk 仍为 248.29 kB；`git diff --check` 无空白错误。工作区保留全部新增模块与验收脚本。


## 2026-10-07 — 指南优化：Exam Event / Syllabus 及 P0 验证

- 新增 `032_exam_events_and_syllabi.sql`：syllabi、syllabus_topics、exam_events、exam_topic_map，全部 owner/subject 复合外键与 authenticated RLS。考试创建/编辑与范围替换在单个 RPC 事务完成，失败不会清空旧范围。
- 新增考试目标 API 和课程结构页的目标/大纲区域：考试日期、Topic 范围、权重、状态、关联大纲可维护；当前课程目录与评分方式可保存为人工大纲快照，稳定 Topic ID 关系保留。
- 029–032 均已安装到本地 PostgreSQL。真实验证：Topic 别名/改名、覆盖幂等、信心字段读写与范围约束、大纲/考试关联、跨学科映射拒绝及失败事务回滚、新表 authenticated RLS；全部临时验收行回滚。
- 当前完整后端回归 **234 passed, 3 warnings**；之后新增 Mastery 持续状态演进专项 **5 passed**。前端 `npm run lint` 与 `npm run build` 通过，最大 chunk 248.24 kB；新页面与信心区域机械设计检查无发现。
- 本轮已完成 P0 的第一轮数据与交互基础，不能声明指南所有 P0/P1 最终验收完成。大纲自动解析、上传资料关联、真实浏览器流程、真实模型绑定率、自动事件闭环、质量校准仍待后续模块。
- 新增脚本 `backend/scripts/verify_course_structure.py` 现在统一检查 029–032；默认只验证，`--apply` 安装缺失迁移，仅接受本地数据库。


## 2026-10-07 — 指南优化：Response Confidence

- 答题页面新增可选信心选择（不太确定/有些把握/很确定/暂不填写）；不推断未填写值。改答案会重置信心，确认后与答案一起锁定，恢复 attempt 返回原信心。
- 保存/确认 API 支持 learnerConfidence∈[0,1]，拒绝 NaN/Inf/越界；新增 `031_response_confidence.sql`，exam_responses 与 grading_results 持久化 learner_confidence，评分结果另存 confidence_mismatch。
- 评分把信心传入 Mastery 的 self_rating，返回四象限反馈；提交整卷读取已保存信心。已确认题目重复调用不会再次更新 Mastery，提交不同信心返回 409。
- Study Signal 升级为 `study-signal-v2-confidence`：新增平均信心偏差与推荐原因。权重调整为 masteryGap 30%、practiceLoss 20%、forgetting 15%、dialogueConfusion 15%、importance 10%、dataConfidence 5%、confidenceMismatch 5%；已有 Study Plan 使用该信号。
- 验证：Confidence、Learner State、Course、Study Plan、Exams 专项 **44 passed**；TypeScript 检查通过。`031` 待本轮统一数据库验收。
- 限制：Adaptive Quiz 暂停策略、Formal Test 隐藏即时评分、真实浏览器答题验收及学习效果校准评测尚未完成，不能将本轮记录为完整 Assessment 模块完成。


## 2026-10-07 — 指南优化：统一 Learner State

- 新增 `learner_state_service.py` 与 `/api/v1/courses/{subject_id}/learner-state`，直接从稳定 Topic、Mastery 和覆盖记录投影 `not_started / covered / practicing / mastered / at_risk`。Memory/浏览器缓存不作为权威状态。
- 新增迁移 `030_topic_coverage.sql`、幂等标记已学习 API；课程页面显示状态、评估证据数和需复习原因。阅读不提升 Mastery，归档 Topic 不进入活动状态统计。
- Mastery v2 把自评信心从得分更新中移出，错误答案不会因自信而提高评估表现；明确区分数据置信度、学习者信心、误解风险。仅 assessment 计入掌握证据，闪卡标记为 flashcard。掌握需要 mastery≥0.8、评估≥3 次、连续评估正确≥3 次及数据置信度≥0.5。
- 新绩效历史保存版本、Topic ID、stateBefore/stateAfter；到期状态在读取时实时计算，避免缓存长期显示已掌握。
- 验证：Learner State、Course、Study Plan、Artifacts 专项 **30 passed**。
- 限制：`030` 代码已就绪，数据库验收待本轮统一执行；历史未标注证据来源的记录不自动算作 assessment，需完成新的评估确认掌握。尚未自动采集资料阅读/Guided Session 覆盖事件；状态到期变化尚无 Worker 主动通知；全量历史迁移与校准质量评测未完成。
- 后续：Response Confidence 接入，随后 Exam Event / Syllabus；模块完整闭环验收仍需后续 P1 集成。


## 2026-10-07 — 指南优化：课程结构 / Topic Domain

- 已完成第一轮课程结构基础：迁移 `029_course_structure.sql`，新增章节、Topic 别名、产物 Topic 关联及复习任务稳定 ID；新增 `/api/v1/courses/{subject_id}/structure`、章节创建/更新、Topic 创建/更新接口，以及侧栏“课程结构”页面。
- Topic 的 `id` 与 `knowledge_key` 保持稳定。改名添加新别名且保留旧别名；归档保留历史。题目生成改用事务 RPC，修复原 upsert 覆盖用户显示名称的问题；新闪卡与新计划任务绑定 Topic。RPC 使用事务锁处理同名并发创建，关系使用 owner/subject 复合外键。
- 验证：课程、考试、产物、计划、生成专项 **47 passed**；`npm run lint` 通过。本地 PostgreSQL 已安装 `029`，真实验证大小写/空白别名去重、改名保留、跨用户/跨学科隔离、外键与 authenticated RLS；验收行全部回滚。
- 限制：未做真实浏览器验收；历史语义重复 Topic 不自动合并，以免误合并历史 Mastery；95% 题目绑定率、100% 新闪卡绑定率仍需真实生成样本统计。Heading 提案与来源块自动提取留到 Ingestion/Parse 模块；Syllabus/Exam Event 是下一独立模块。
- 后续按指南 P0 顺序：统一 Learner State → Exam Event / Syllabus → Response Confidence，再进入 P1。
- 详细验收见 `docs/acceptance/COURSE_STRUCTURE_20261007.md`；复验命令：`cd backend; .\.venv\Scripts\python.exe scripts/verify_course_structure.py`。此脚本仅允许本地数据库，验证数据事务回滚；只有 `--apply` 会安装迁移。


## 2026-09-13 — Dayend V3 本地持久化验收与质量评估豁免（最新）

> 当前全项目验收索引：`docs/acceptance/CURRENT_PROJECT_ACCEPTANCE_20260913.md`。
> 结论为“有条件通过（本地技术交付）”，不是生产级最终验收。

### 本轮已完成

- Closure 合同新增约束：模型分类为 `uncertain` 的事项必须引用有效
  `needs_confirmation_ids`；新增 `test_closure_contract.py`，完整后端回归为
  `205 passed, 3 warnings`。
- `/api/v3/runs/stream` 在 `confirmation_required` 后不再错误发出
  `run_completed`；所有者隔离已真实验证：owner `GET` 为 200，另一账户
  `GET`/`resume` 均为 404。
- A/B/C 盲评流程已补齐私有 answer key：评审包只含 `review_id`，协调者通过
  `merge_dayend_blind_scores.py` 在评分回收后再映射 `case_id`/`variant`。
  评分工具回归 `4 passed`；评审包位于 `.run/dayend-blind-review/`，私钥位于
  `.run/dayend-blind-review-keys/`，后者绝不可发给评审者。
- PostgreSQL 持久化代码准备已完成：新增 `langgraph-checkpoint-postgres`，
  `DAYEND_PERSISTENCE_BACKEND=postgres` 时 checkpoint 使用
  `AsyncPostgresSaver`，业务投影使用 JSONB upsert；新增迁移
  `backend/migrations/028_dayend_business_persistence.sql`。SQLite 兼容路径
  回归 `5 passed`。
- 本地 Supabase PostgreSQL 已恢复后，`028` 已核验存在 `dayend_runs`、
  `dayend_night_states` 及 `dayend_runs_user_created_idx`。Windows 下发现
  `psycopg` 与 Proactor event loop 不兼容，已新增 PostgreSQL 模式专用的
  Selector 启动兼容层。两次独立进程已验证 checkpoint 中断后 resume 与 JSONB
  业务投影读取，测试记录已清理；新的无 reload 后端启动器健康检查通过。

### 未完成 / 不得误报

- VS Code Codex 当前没有可用 Browser 控制面板；Dayend Activity Drawer 的真实
  浏览器确认/resume 验收仍未执行，不得标记为通过。
- 用户确认无法取得两位独立评审的 JSONL；本交付将 A/B/C 质量指标与货币成本
  正式记为 `N/A（质量复核未完成）`。评审包和私有 answer key 继续保留，以便未来
  独立复核；不得用自动评分、协调者评分或推断结果替代。
- PostgreSQL 已在本地 Supabase 环境通过迁移对象、进程重启恢复与启动器验证；
  这仅代表本地验收，尚未构成部署到生产环境的声明。
- Windows `uvicorn --reload` 在该环境可能陷入命名管道 `WinError 5` 循环。
  验收时使用无 reload 的单进程后端，并确保它继承
  `NO_PROXY=localhost,127.0.0.1`，否则本地 Supabase 认证会错误走系统代理。

### 当前交付结论与后续顺序

- Dayend V3 后端技术验收为**有限通过**：真实运行批次、权限、SSE 语义、SQLite /
  PostgreSQL 持久化恢复及专项回归已有证据。
- A/B/C 人工质量结论为 **N/A（豁免，待未来独立复核）**，不构成质量优于基线或
  最终完整验收通过的证据。
- Activity Drawer 的真实浏览器 HITL 验收仍为未完成。
- 前端生产构建已完成 vendor 分包；最大 chunk 由 517.26 kB 降至 246.83 kB，
  不再出现 >500 kB 构建警告。
- 真实完整 E2E `acceptance-20260913T205814-live` 完成为 43/46：认证、真实 PDF
  处理、隔离、Chat、Artifacts（含思维导图）、考试/评分、计划及隐私流程通过；
  Chandler/Andrews/Johnson 检索检查仍未达标，Golden Recall@5 为 18/20。

1. 在支持 Browser 的 Codex 客户端完成真实 Activity Drawer 与 HITL UI 验收。
2. 如未来取得两位独立评分 JSONL，再用私有 answer key 合并、校验并补发 A/B/C
   质量报告；此前不得修改 `N/A` 结论。

## 2026-09-10 — Dayend V3 真实验收与工作区整理续作（最新）

### 已完成并提交

- 工作区已整理为干净状态；已删除 17 个 `test-*.sqlite` 测试产物，并在 `.gitignore` 中忽略根目录 `data/dayend/*.sqlite`。
- 已提交：
  - `cc2b171 feat(dayend): add stateful multi-agent runtime and acceptance`
  - `be97fea fix(dayend): make checkpoint persistence async-safe`
- 真实 SiliconFlow 逐 Agent 结构化验收已覆盖 Supervisor、Closure、Planning、Emotion、Safety、Critic、Morning；运行元数据记录在本地 `.run/dayend-*.log`，不提交。
- 真实 Mixed 图验收完成：Closure/Emotion 并行，分别依赖到 Planning/Safety，最终由 Critic 汇合。
- 真实 Critic revision 验收完成：Critic 指向 `planning_agent`，Planning 带反馈修订，Critic 复审通过；完整 Trace 为 3 条。
- 真实 HITL 验收完成：真实 Closure → SQLite checkpoint → 新图实例 → `resume(thread_id)`；人工响应为 `{"confirmed": false, "status": "unfinished"}`。

### 本轮修复

- Dayend async 图原先搭配同步 `SqliteSaver`，真实 HITL 报错。生产 `/api/v3` 现使用 `AsyncSqliteSaver`，子图由根图持久化。
- Dayend checkpoint serializer 显式允许 `AgentEnvelope[TypeVar]` 和 `AgentTrace`，跨实例 resume 不再出现未来版本将拒绝的未注册类型警告。
- Agent runtime 增加 120 秒硬超时、失败类型 Trace 和 provider token usage 采集；Critic 的路由目标由其 issue 的 `target_agent` 确定性投影，避免重复字段冲突。
- 持久化测试显式关闭 SQLite saver，防止 Windows 留下锁定的测试数据库。

### 当前验收状态与门禁

- Dayend/图/API/运行时专项测试通过；最近一轮异步持久化相关回归为 `14 passed`，serializer 修复后的本地回归为 `3 passed`。
- 前端 `npm run lint`、`npm run build` 通过；构建仍有 509.37 kB 主 chunk 警告。
- 后端完整 `pytest tests -q` 能推进到约 85%，随后在后段检索/计划测试无 CPU 进展；该完整回归目前为未完成，不能写成通过。单独的 assistant 用例可通过。

### 下一步（严格顺序）

1. 补齐 `/api/v3/runs/stream` 的细粒度 SSE：`agent_started`、真实 tool-call、`revision_started`、`critic_failed`、明确 `run_failed`/`run_completed`。
2. 前端在 `MainLayout` 挂载 Dayend Activity Drawer；使用受认证的 fetch streaming 消费 POST SSE，并提供 HITL 确认/resume 交互。
3. 为 SSE 与前端消费增加自动化契约测试和一次真实流式验收；不得用模拟活动替代真实 Trace。
4. 诊断并恢复完整后端 pytest 门禁，再进入 100-case evaluation、A/B/C ablation 与生产 PostgreSQL 迁移。

### 后续启动提示

```powershell
Set-Location C:\Users\xingk\Desktop\Final-Term-main
git status --short
Get-Content -Raw -Encoding UTF8 .\HANDOFF.md

Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests\graphs tests\architecture\test_v3_api_contract.py tests\runtime\test_agent_factory.py tests\scripts -q -p no:cacheprovider
```

真实 Dayend 验收前只检查非敏感开关：`MOCK_EXTERNAL_APIS=false`；不得输出 API key、提交 `.run/`、`data/` 或 `.env`。

## 2026-09-01 — Dayend V3 Multi-Agent 重构续作（最新）

### 本轮新增与已验证

- 新增 Dayend V3 独立运行时（不替换现有 `/api/v1` 考试复习 API）：
  - 7 个 Agent：Supervisor、Closure、Planning、Emotion、Safety、Critic、Morning；
  - LangGraph shared state、Critic revision loop、HITL `interrupt()/resume`、SQLite checkpoint；
  - Closure → Planning、Emotion → Safety 依赖；Mixed 图使用 fan-out/fan-in；
  - 独立 V3 business SQLite 保存 Closure、Planning、Emotion、人工确认与 run projection；
  - `/api/v3/runs`、查询、resume 和 SSE run stream 已挂载。
- 真实模型统一走项目现有 SiliconFlow OpenAI-compatible 配置：
  - `EXAMAI_OPENAI_BASE_URL=https://api.siliconflow.cn/v1`；
  - `EXAMAI_OPENAI_API_KEY`（绝不输出或提交）；
  - Dayend 显式使用 `trust_env=False`，避免环境中错误的 `127.0.0.1:9` 代理；
  - 可用 `DAYEND_ORCHESTRATOR_MODEL`、`DAYEND_SPECIALIST_MODEL`、
    `DAYEND_CRITIC_MODEL`、`DAYEND_SAFETY_MODEL` 在同一 SiliconFlow provider 内按角色选模型。
- 真实调用验收已成功（不是 mock）：
  - SiliconFlow `/models` 带鉴权请求返回 HTTP 200；
  - Dayend `supervisor_agent` 完成一次真实结构化调用，返回 `SupervisorOutput`，
    trace `success`，模型为 `deepseek-ai/DeepSeek-V4-Flash`，attempt=1；
  - 模型故障时运行时抛出 `AgentRunFailed`，没有旧规则 fallback。
- 最近本地专项验收：业务持久化、Mixed/Morning 图和 Critic revision 相关测试 6/6 通过；
  更早一轮 V3 图/API/架构专项测试 17/17 通过。pytest 仍可能报告 Windows pytest cache 目录权限 warning，
  不代表测试失败。

### 关键文件

| 用途 | 位置 |
| --- | --- |
| V3 主图 / 子图 | `backend/app/graphs/root_graph.py`、`mixed_graph.py`、`morning_graph.py` |
| Agent runtime 与 SiliconFlow 模型工厂 | `backend/app/runtime/agent_factory.py`、`model_factory.py` |
| V3 API 与 run service | `backend/app/api/runs.py`、`backend/app/services/dayend_run_service.py` |
| Checkpoint / 业务持久化 | `backend/app/persistence/checkpointer.py`、`store.py` |
| V3 合约、状态、工具 | `backend/app/schemas/`、`state/dayend_state.py`、`tools/` |
| 真实模型验收脚本 | `backend/scripts/verify_dayend_live.py` |
| 审计与验收文档 | `docs/V2_ARCHITECTURE_AUDIT.md`、`docs/MULTI_AGENT_*.md`、`docs/AGENT_*.md` |

### 仍未完成 / 不得误报

- 100-case evaluation 与 A/B/C ablation 尚未建立或运行；
- 前端尚未接入 V3 SSE Agent Activity Drawer 与人工确认 UI；
- SSE 仍未完整覆盖规范要求的所有细粒度事件（例如真实 tool-call、critic-failed、revision-start）；
- 生产 PostgreSQL checkpoint、生产业务数据库迁移和完整 server-restart E2E 尚未完成；
- 需继续以真实 SiliconFlow 调用覆盖 Closure、Planning、Emotion、Safety、Critic、Morning 及 Mixed 全链路，
  不得用 mock 代替真实架构验收。

### 后续执行顺序

1. 逐 Agent 跑真实 SiliconFlow structured-output 验收，并记录 trace/latency/token；
2. 补齐 Critic revision、Mixed、HITL resume 的真实端到端测试；
3. 补齐 SSE 细粒度事件并在前端消费真实 trace；
4. 建立 100-case 数据集、A/B/C ablation 和真实指标报告；
5. 完成生产持久化迁移及重启恢复验收后，才可宣称 V3 完整完成。

更新时间：2026-08-24（Asia/Shanghai）

项目路径：`C:\Users\xingk\Desktop\Final-Term-main`

基线提交：`2a058b8d511f3d58bf204798d95a747eda8f269a`（`main`）

## 新窗口首先执行

```powershell
Set-Location C:\Users\xingk\Desktop\Final-Term-main
git status --short
Get-Content -Raw -Encoding UTF8 .\HANDOFF.md
```

必须遵守：

- 当前工作区包含尚未提交的连续修复和验收文档，不要执行 `git reset --hard`、`git checkout --` 或覆盖现有改动。
- `.env` 含真实密钥并被 `.gitignore` 忽略。只能查看必要的布尔开关，禁止输出、提交或复制密钥值。
- 不要删除 `PDF资料/` 中的用户资料，也不要擅自更改其提交状态。
- Windows PowerShell 5 读取中文文件时显式使用 `-Encoding UTF8`。
- 真实验收不得自动切换 Mock；未运行真实外部服务时必须写 N/A 或未验证。

## 当前工作区结论

本轮用户限定只完成原规划中的：

1. 第一阶段：建立基线。
2. 第二阶段：代码去重与失效代码清理。
3. 第三阶段：接口矩阵与契约收敛。
4. 第九阶段：项目技术面试文档。

真实 E2E、可观测性改造、性能成本采集、故障注入及修复后的第二轮真实验收不在本轮范围内。不能用本轮的 170 个自动化测试宣称完整真实验收通过。

当前 Git 工作区是脏的。主要变更约为 48 个已跟踪文件、126 行新增、671 行删除，另有以下未跟踪交付物：

- `backend/app/services/generation_task_service.py`
- `docs/acceptance/`
- `PROJECT_TECHNICAL_INTERVIEW_GUIDE.md`

提交前必须重新查看 `git status --short`，数字以当时结果为准。

## 当前运行状态

以下为 2026-08-24 本轮只读探测结果：

| 服务 | 当前状态 | 地址/证据 |
| --- | --- | --- |
| Frontend | 未运行 | `127.0.0.1:5173` 不可连接 |
| Backend | 未运行 | `127.0.0.1:8000` 不可连接，`/health` 不可用 |
| Supabase | 端口可连接 | `http://127.0.0.1:18000` |
| Mailpit | 端口可连接 | `http://127.0.0.1:8025` |
| Redis | 端口可连接 | `127.0.0.1:6379` |
| Celery Worker | 在线 | `celery@sky: OK / pong`，1 node |
| Celery Beat | 本轮未单独复验 | N/A |

启动与停止：

```powershell
.\start-project.ps1 -NoBrowser
.\stop-project.ps1
```

启动器负责本地 Supabase、Redis/Celery 组件、Windows Worker、FastAPI 与 Vite。Windows Worker 的历史原因是 Docker/WSL 到阿里云 OSS 曾出现 TLS `UNEXPECTED_EOF_WHILE_READING`，Windows 主机直连正常。

## 本轮已完成：基线与回归

### 清理前基线

| 门禁 | 结果 |
| --- | --- |
| 后端完整测试 | `170 passed, 3 warnings`，15.47s |
| 前端 lint（`tsc --noEmit`） | 通过 |
| 前端生产 build | 通过，7.46s |
| 最大 chunk | 509.75 kB，gzip 150.70 kB |
| OpenAPI | 147 paths / 177 operations |

### 清理后最终回归

| 门禁 | 结果 |
| --- | --- |
| 后端完整测试 | `170 passed, 3 warnings`，10.27s |
| 受影响测试 | `35 passed, 1 warning` |
| 前端 lint | 通过 |
| 前端生产 build | 通过，6.27s |
| 最大 chunk | 509.37 kB，gzip 150.58 kB；仍有 Vite 警告 |
| Ruff `F` 类 | 通过，0 条 |
| Knip | 通过，0 个未使用依赖/文件/导出 |
| E2E 脚本 | `py_compile` 通过；未执行真实 E2E |
| OpenAPI | 62 paths / 75 operations，当前契约校验通过 |

pytest 的 3 条警告来自 Starlette TestClient/httpx2 迁移，以及 Supabase client 的 `timeout`/`verify` 弃用参数，不是本轮回归失败。

## 本轮已完成：API 收敛

### 唯一业务前缀

- 所有业务 API 只挂载在 `/api/v1`。
- `/health` 是唯一无版本公开路径。
- 删除 68 条无前缀业务镜像。
- 前端 `apiV1()`、自动化测试和 E2E 脚本均已改为 `/api/v1`。

### 删除 Workbench Mock

- 删除 `backend/app/api/workbench.py`（121 行占位数据）。
- 删除 `/api/workbench/*` 的 10 个 path。
- 删除对应占位测试和前端 `VITE_MOCK_APP` 分支。
- `.env.example` 与 `frontend/.env.example` 不再声明 `VITE_MOCK_APP`。
- 本地真实 `.env` 里即使还保留历史 `VITE_MOCK_APP=false`，代码也不再读取它。

`mock_external_service.py` 仍保留，用于自动化测试的确定性模型替身；它与已删除的无认证 Workbench Mock 不同。真实验收必须设置 `MOCK_EXTERNAL_APIS=false`。

### 重复业务入口

| 已删除入口 | 唯一替代入口 |
| --- | --- |
| `/exams/attempts/*` | `/api/v1/exam-attempts/*` |
| `/outline/generate` | `/api/v1/artifacts/outlines` |
| `/quiz/generate` | `/api/v1/exams/generations` |
| `POST /api/v1/exams` 同步生成 | `POST /api/v1/exams/generations` |
| `POST /api/v1/study-plans` 同步生成 | `POST /api/v1/study-plans/generations` |
| 错题本页面/公开说明 | 练习表现分析、掌握度与学习信号 |

考试和复习计划的内部 service 仍保留，供 Celery Worker 与 assistant 编排调用；删除的是重复的同步 HTTP 入口。

### 错题本边界

- 已删除前端旧重定向、README 公开错题本说明和失效静态验收脚本。
- router agent 仍识别“错题”等旧用户表达，将其映射为“分析练习表现”；这不是错题本入口。
- `wrong_answers` 历史表按用户要求暂时保留。
- 隐私导出、数据删除和账户删除仍覆盖该表。

## 本轮已完成：代码去重

### Generation task 公共实现

考试与计划 generation service 原本各自实现：

- payload 规范化；
- SHA-256 指纹；
- queued/running 活跃任务查询；
- 幂等复用；
- `processing_tasks` 创建与元数据初始化。

现在统一到：

- `backend/app/services/generation_task_service.py`

两个原 service 保留为薄适配器，仅传入 task type、idempotency 前缀和结果字段（`examId` / `planId`）。指纹稳定性有自动化测试保护。

### 静态扫描结果

| 工具 | 清理前 | 清理后 |
| --- | --- | --- |
| Knip | 2 个未使用依赖、11 个未使用导出 | 0 |
| Ruff 未使用/未定义符号 | 存在真实未使用 import | `--select F` 为 0 |
| Vulture 80% | — | 仅 2 个 Pydantic validator `cls` 反射误报 |
| jscpd 克隆块 | 19 | 14 |
| jscpd 重复行 | 133（1.01%） | 91（0.71%） |

已删除的典型失效代码：4 个旧 agent 占位模块、旧 constants/eval/logger 包装、同步 LLM 包装、旧 parse 包装、`verify_plan_coverage.py`、未使用的 GSAP 依赖和前端同步 `createExam` 方法。

### 有意保留的候选

- `/api/v1/materials/upload` 同步接口仍存在，目前由后端处理链路测试使用；正式前端和 E2E 已统一到 `/materials/uploads`。删除前应先把同步处理测试下沉到 service 层。
- jscpd 剩余 14 个短克隆多为 API 适配、模型字段或 assistant 分支；继续抽取未必提高可读性。
- Ruff 首次全规则有 214 条，其中大量是 FastAPI `Depends` 的 B008、导入排序和宽泛异常历史债；本轮没有用自动格式化扩大修改范围。

## 新增交付文档

| 文档 | 内容 |
| --- | --- |
| `docs/acceptance/ACCEPTANCE_PLAN.md` | 本轮范围、环境、基线、实施结果和回归证据 |
| `docs/acceptance/API_ACCEPTANCE_MATRIX.md` | 页面 → 前端方法 → HTTP → Service → 数据表 → 测试 |
| `docs/acceptance/DUPLICATION_AUDIT.md` | Ruff/Vulture/Knip/jscpd 候选、处理和保留理由 |
| `docs/acceptance/openapi-before.json` | 清理前 147 paths / 177 operations |
| `docs/acceptance/openapi-after.json` | 清理后 62 paths / 75 operations |
| `PROJECT_TECHNICAL_INTERVIEW_GUIDE.md` | 架构、时序、技术选型、RAG、异步、安全、40 个问答和演示流程 |

旧 `backend/BASELINE.md` 已删除，避免继续传播 `88 passed` 和失效静态脚本结果。

## 历史真实链路修复（2026-08-23 证据）

以下是上一轮已完成并写入原交接文档的真实运行事实。本轮没有重新执行真实 E2E，不应把它们当作 2026-08-24 新验收结果。

### 认证、UUID 与账号隔离

- 前端不再用 `math` 等 Mock 学科 ID 调用 UUID 接口。
- localStorage 当前学科按账号隔离，并验证 UUID。
- 非 UUID 学科输入返回明确校验错误，不再导致数据库 500。

### MinerU 与 Worker 恢复

- MinerU Token 当时已验证有效，能签发上传票据。
- `mineru_client.py` 控制请求和文件传输不读取失效系统代理。
- Worker 重启会恢复 queued/running 任务；终态重复投递保持幂等。
- 相关代码：`backend/app/worker/recover.py`、`scripts/dev-worker.ps1`。

### LightRAG 降级

- MinerU、内容块与向量化完成后，LightRAG 不再阻塞材料 ready。
- LightRAG 有 180 秒总超时；失败时记录 index failed，但关键词与 pgvector 继续使用。
- 当时的 Embedding 为 4096 维，而 PostgreSQL pgvector HNSW 索引限制为最多 2000 维；LightRAG 图索引不能按当前方案建立 HNSW。
- 不要为了恢复 LightRAG 再次让它阻塞材料 ready。可选长期方案：LightRAG 单独低维 Embedding 或替换向量存储。

### `What is strategy` 历史回归

- 查询 Embedding 不再读取失效系统代理。
- 定义类问题支持中英文查询扩展和同页上下文补充。
- 历史实测检索耗时约 0.74s，首条证据为 `Lecture 2.pdf` 第 33 页，召回 Chandler（1962）定义。
- 该耗时是历史单次结果，不是 p50/p95。

### 真实模型历史配置

- 上一轮记录为 `MOCK_EXTERNAL_APIS=false`。
- Provider：`openai_compatible`。
- Chat：`deepseek-ai/DeepSeek-V4-Flash`。
- Embedding：`Qwen/Qwen3-VL-Embedding-8B`。
- 历史 Chat 日志延迟约 9–12s。

本轮只确认设置默认值与文档，没有输出密钥，也没有重新发起模型请求。真实验收前必须再次检查布尔开关与 `generation.mocked=false`。

### 专项练习

- practice 的主题必填；单题型数量允许 0～20，总数至少为 1，页面总上限 20。
- `course_first` 默认以课程资料为准，公开知识失败时安全降级并记录 warning。
- 生成按批次执行，默认每批 4 题、60 秒超时、失败批次局部重试 1 次。
- checkpoint 保存已完成题目和证据；Worker 重启后可从剩余批次继续。

## 关键代码位置

| 功能 | 文件 |
| --- | --- |
| FastAPI 挂载与异常 | `backend/app/main.py` |
| API router | `backend/app/api/router.py` |
| 配置 | `backend/app/config/settings.py` |
| 统一 generation task | `backend/app/services/generation_task_service.py` |
| 考试异步入口 | `backend/app/api/exams.py` |
| 考试作答入口 | `backend/app/api/exam_attempts.py` |
| 考试生成与校验 | `backend/app/services/exam_service.py` |
| 考试证据检索 | `backend/app/services/exam_retrieval_service.py` |
| 计划异步入口 | `backend/app/api/study_plans.py` |
| 计划排程 | `backend/app/services/study_plan_service.py` |
| MinerU | `backend/app/services/mineru_client.py`、`mineru_parser.py` |
| 资料入队/处理 | `backend/app/services/ingestion_service.py`、`material_service.py` |
| 混合检索 | `backend/app/services/retrieval_service.py` |
| LightRAG | `backend/app/services/lightrag_service.py` |
| RAG 回答 | `backend/app/services/rag_service.py` |
| Worker 任务/恢复 | `backend/app/worker/tasks.py`、`recover.py` |
| 前端 API | `frontend/src/api/client.ts` |
| 账号隔离状态 | `frontend/src/stores/useAppStore.ts` |
| 考试页面 | `frontend/src/pages/Exams/index.tsx` |
| 计划页面 | `frontend/src/pages/Plan/index.tsx` |
| 动态 E2E | `backend/scripts/e2e_acceptance.py` |

## 环境与验收命令

### 只显示关键布尔值

不要打印整个 `.env`：

```powershell
$names = 'MOCK_EXTERNAL_APIS','CELERY_TASK_ALWAYS_EAGER','ENABLE_MINERU'
foreach ($name in $names) {
  Get-Content .env |
    Where-Object { $_ -match ('^' + [regex]::Escape($name) + '=') } |
    Select-Object -Last 1
}
```

真实验收硬门槛：

```text
MOCK_EXTERNAL_APIS=false
CELERY_TASK_ALWAYS_EAGER=false
ENABLE_MINERU=true
```

前端已没有 `VITE_MOCK_APP` 模式。

### 自动化回归

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe -m py_compile scripts\e2e_acceptance.py

Set-Location ..\frontend
npm run lint
npm run build
```

### 服务健康

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health

Set-Location .\backend
.\.venv\Scripts\python.exe -m celery `
  -A app.worker.celery_app:celery_app inspect ping --timeout 5
```

### OpenAPI 保护

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -c "from app.main import app; p=app.openapi()['paths']; assert not any(x.startswith('/api/workbench') for x in p); assert '/subjects' not in p; assert '/api/v1/subjects' in p; print(len(p))"
```

预期输出：`62`。

## 当前数据状态（历史，未在本轮复验）

- `Lecture 2.pdf`：历史状态 ready，任务 succeeded，160/160 切片有向量。
- `Lecture 3.pdf`：历史状态 ready，任务 succeeded，127/127 切片有向量。
- 两个文件历史 LightRAG 状态为 failed，但关键词和向量问答可用。
- 本轮没有查询数据库重新确认，是否需要重新上传应先通过真实 API/数据库检查，不要仅依据本文猜测。

## 已知限制

- 本轮未执行真实 Supabase 登录、邮件、真实 PDF、MinerU、Embedding、Chat、双用户隔离或故障注入。
- p50/p95/max、Token、模型成本和外部服务成本均为 N/A，不能写成 0。
- 前端主 chunk 仍超过 500 kB。
- `/api/v1/materials/upload` 同步迁移候选尚未删除。
- OpenAPI 与前端类型尚未自动生成绑定，当前靠手写适配、lint 和接口矩阵保护。
- Ruff 全规则历史债尚未建立正式项目配置。

## 建议的后续任务

按优先级：

1. 提交或按主题拆分当前工作区，先保住阶段 1/2/3/9 成果。
2. 启动 FastAPI/Vite 后执行真实环境预检，确认所有关键服务和 Mock 开关。
3. 建立 20～30 个带页码 Golden Questions，执行 Recall@5、引用页码和跨学科污染评估。
4. 用两个真实用户完成认证、资源 UUID 越权、缓存与隐私隔离测试。
5. 执行真实异步资料、考试、评分、学习信号和计划闭环。
6. 注入 Redis、Worker、MinerU、模型、LightRAG、Token 与网络异常。
7. 补齐阶段耗时、Token、模型价格和 JSONL/CSV 成本报告。
8. 修复问题后执行第二轮完整真实回归，不能只重跑失败步骤。
9. 将 `/materials/upload` 的处理测试下沉 service 后删除同步入口。
10. 做路由/依赖拆包，解决 509.37 kB chunk 警告。

## 提交建议

不要提交 `.env`、`.env.worker`、`.run/`、日志、缓存或密钥。可按以下主题拆分：

1. `refactor(api): remove legacy and workbench routes`
2. `refactor(tasks): unify generation idempotency`
3. `test(api): protect canonical v1 contracts`
4. `docs: add baseline audit matrix and interview guide`

提交前再次运行后端完整测试、前端 lint/build 和 `git diff --check`。

## 给后续助手的建议提示词

> 请先阅读 `C:\Users\xingk\Desktop\Final-Term-main\HANDOFF.md`、`docs/acceptance/ACCEPTANCE_PLAN.md` 和当前 `git status`。保留所有现有改动与密钥安全约束。业务接口只允许 `/api/v1`，不要恢复无前缀路由、`/api/workbench/*`、同步考试/计划入口或公开错题本。未执行真实链路时必须写 N/A，不要把自动化测试当成真实验收。

## 2026-08-24 阶段 4–6 续作

已完成可观测性与真实 E2E 改造，并执行真实后端验收。最终 run：`acceptance-20260824T021739-934fed33`，42/47 通过；Golden Recall@5 为 0.90。真实 Supabase 双账号、真实 PDF、MinerU、Embedding、Chat、异步考试/评分、复习计划、导出和隐私清理均已运行。思维导图真实调用仍为 502；Andrews/Johnson 两条 Golden Questions 未命中目标页；前端真实登录态因内置浏览器插件初始化冲突为 N/A。详见 `docs/acceptance/PHASE_4_6_ACCEPTANCE.md`。

新增迁移 `backend/migrations/027_observability_trace_context.sql` 只需应用一次。不要再次用验收脚本重放全部历史迁移；历史 migration 中 `search_content_blocks` 返回类型变更不可重复执行。

最终 run 时旧 `.env` 零价导致原始报告成本错误显示为 0；现已把本地非敏感价格键修正为 SiliconFlow 官方 CNY 价格，并在 E2E 中增加正价格硬门槛。原始 0 不得作为成本证据。
