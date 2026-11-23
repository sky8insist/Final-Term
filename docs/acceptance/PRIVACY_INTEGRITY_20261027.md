# 账号删除与隐私完整性验收

日期：2026-10-27。依据：技术指南第25项；承接学习记录浏览器验收发现的Auth删除500。

## 结果与范围

- 本地迁移058已安装；最终报告 [report.json](privacy_integrity_20261027/report.json)：**10/10 passed，success=true，cleanup=true**。通过正常Supabase密码登录取得JWT，启动自有随机端口Uvicorn，通过真实HTTP调用产品API，无TestClient或身份覆盖。
- 完整后端 **899 passed，3 warnings**；新增13项回归，另更新原日历删除测试以匹配事务RPC。Ruff F、离线quality gate及diff检查通过。前端未变，本轮没有重复前端构建或浏览器验收。
- 使用3个本轮新建临时账号、79张导出表、1,005条合成事件及真实Storage音频/转录占位文件；不使用真实用户数据、不调用模型。文件只验证保管/删除，不表示真实ASR。

## 一、Auth删除500

1. 上轮Auth日志明确为 `permission denied for table study_plans (SQLSTATE 42501)`。原因是级联删除知识点等记录调用 `mark_study_plan_changed`，以Auth数据库角色执行跨表更新。将此触发器及删除Memory后清快照触发器改为 `SECURITY DEFINER`，保留固定search_path、撤销公开调用权限，不向Auth角色授予业务表权限。
2. 加入完整考试/题目关联后进一步复现 `exam_questions_question_id_fkey (SQLSTATE 23503)`。只修权限仍失败；只改普通NO ACTION也未解决。最终将五条旧RESTRICT约束改为 **NO ACTION DEFERRABLE INITIALLY DEFERRED**，在事务提交时核验，允许同事务的账号级联先完整结束。单独删除仍被考试引用的题目，在强制约束检查时继续被拒绝。
3. 最终真实Auth管理员API删除含Topic、Memory、考试/题目关联的临时账号成功。它仍不是完整隐私删除入口：旧Dayend的text user_id没有Auth外键，外部Storage也不受Auth级联管理；产品入口先执行完整学习数据清理。

失败证据边界：首次脚本被外键和Windows临时目录清理权限中断，没有产出完整报告；随后已核验并精确清理首次3个临时ID。修正中间轮保留 [second-report.json](privacy_integrity_20261027/second-report.json)，该轮checks为空、cleanup=true，**不是通过报告**；它在最终success字段加入前生成，实际退出为Auth 500。以上错误来自捕获的执行输出和本地Auth日志，不把它们改写为成功。没有保存密码、JWT、HAR或完整服务日志。

## 二、导出完整性

- 旧实现对每张表只请求一页，且捕获异常后填写空数组，可能把截断或失败当完整导出。新增私有 `export_privacy_bundle`，STABLE函数使用调用语句的一致快照聚合为单个JSON对象，不受PostgREST表查询的行数上限截断；任意错误返回503，不交付部分结果。
- 按public普通/分区根表的user_id列发现本人记录（兼容旧text user_id），补profiles及无user_id的考试章节/关联题目/题目版本；包含此前遗漏的Dayend和LightRAG索引元数据。只通过本人JWT映射服务端p_user；RPC只允许service_role，不能从客户端指定别人ID。
- 实际断言1,005条product_events全部导出；两账号分别只返回本人行；profile、旧Dayend、子表和两条文件manifest都在导出中；响应 `Cache-Control: no-store`。
- 这是关系数据及文件元数据JSON导出，**不含原始二进制文件、Auth秘密、服务日志或备份**。单JSON内存/超时与大规模P95尚未验收。新增无user_id子表仍需人工加入父链关联规则；不能据此宣称所有未来schema自动覆盖。

## 三、删除与失败恢复

- 外部索引和Storage清理先执行，成功后调用私有 `delete_privacy_learning_data`。关系删除、旧Dayend/全局审计清理及快照代次撤销在一个事务内；保留账户身份和profiles，其他本人user_id数据清理，按需留下无学习内容的缓存代次。
- 索引/文件清单分页读到空页，避免只清前一页；Storage每批100条。索引包含failed/indexing，缺失维度元数据则明确502并保留关系清理凭据。LightRAG/Storage异常不能先删除考试行；部分已成功的外部删除不能回滚，但manifest保留以便重试。
- SQL故障注入在临时触发器中拒绝删除旧Dayend；核验此前删除的科目和考试均回滚。触发器及函数仅存在于回滚事务，不留在数据库。
- 真实产品DELETE /privacy/data删除全部测试学习、审计、旧Dayend和Storage音频/转录文件；下载返回明确不存在的Storage错误，账号仍可导出，重复删除成功。
- 重填数据后真实DELETE /privacy/account删除Auth身份；旧JWT访问隐私/科目API均401，再次密码登录失败，另一个账号的事件数据保持1条。第二个带数据账号也通过正常产品入口删除。
- 增加每个保护请求的Auth在线身份核验；只验证JWT签名/有效期无法拒绝已删除账号的旧令牌。Auth明确拒绝映射401、服务不可用映射503，失败关闭，不缓存账号存活状态。代价是每个保护请求额外一次Auth调用；本轮未测P95。
- 回归另外覆盖Auth最终删除失败时502、重试成功、错误不泄露内部细节、确认字符串错误不执行删除、索引/Storage/元数据失败不调用关系删除。

## 复跑、部署与剩余

backend下运行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_privacy_integrity.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_privacy_full
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

其他环境须先依序安装历史迁移至057及 **058_privacy_integrity.sql**，再部署API；本地首次可给验收脚本加 `--apply`。脚本限制本机DB/Auth/Redis，不修改.env，不重启既有服务。Windows临时目录/子进程限制时已按工具权限运行。结束清理生成的精确账号、本人Redis键和Storage路径；失败清理用SQL不计作产品删除通过。证据哈希见 [evidence.json](privacy_integrity_20261027/evidence.json)。

仍待完成：上传/Worker与删除的统一互斥及跨服务发布栅栏、孤儿Storage对象和真实LightRAG内容清理验收、原始文件打包导出、大规模性能、音频/审计/事件保留期限和定时清理、生产/浏览器隐私界面及完整全站跨用户安全矩阵。本轮是有界后端专项，不宣称指南第25项全部完成；正常Auth/Storage日志与备份仍按各自策略保留。
