# 材料摄取恢复与发布验收

日期：2026-10-27。依赖：060_material_ingestion_jobs.sql；[运行/部署说明](../MATERIAL_INGESTION_JOBS.md)。

## 范围与证据

[最终报告](material_ingestion_jobs_20261027/report.json) **10/10通过，success=true，cleanup=true**。真实本地PostgreSQL、Supabase Storage、Redis及独立命名队列的solo Celery Worker；使用新建临时用户、TXT占位文件。解析器实际运行，向量为明确的3维确定性替身，图为明确故障注入，不调用付费模型、MinerU、ASR或真实LightRAG。

本轮不是普通用户JWT、生产或浏览器验收；核心调用为服务角色私有摄取RPC。原章节/上传Notes测试已迁移到核心成功后的可选处理，保留失败不影响核心的语义；旧Worker恢复测试改为验证不擅自清running或重置attempts。单元测试的owner锁为显式替身，独立锁测试和本脚本的真实两线程检查补齐锁行为。

新增8项回归，完整后端 **922 passed，3个既有弃用警告**；最终相关模块 **85 passed**，Ruff F、离线quality gate及diff检查通过。全量套件运行486.18秒，不据此宣称任何产品性能结论。

## 十项实际检查

1. 正常上传到真实Storage；登记manifest/任务同事务；模拟broker失败，任务仍queued/attempts=0且能被持久补扫读取。
2. 在发布更新任务succeeded时注入SQL异常，确认此前同事务内容块/分块/向量/ready全部回滚；parsed/embedded两个检查点仍保留。
3. 注入退避到期后重投，复用检查点发布成功，parse=1、embed=1、graph=2；实际向量维度3、图状态failed但材料ready；只产生1条material.indexed领域事件，成功后大检查点清除。
4. 第3次已成功任务投递skipped，不重新解析/向量或发布。
5. 有效租约拒绝重复领取/错误token；注入租约过期后发新token、attempts从1变2，旧token不能续租。
6. 取消撤销令牌；晚到发布及失败写回拒绝，不能恢复cancelled或创建canonical内容块。
7. 另一用户不能取消，authenticated不能直接调用发布RPC。
8. 持有真实owner IO锁时，另一个实际线程的产品隐私删除收到409，Worker收到busy，数据未删除且没有新领取。
9. 附件先达到过期条件，再持有IO锁；另一线程的真实清理跳过，Storage对象仍能实际下载。
10. 本人导出包含检查点表；IO结束后正常产品隐私服务清理任务/检查点。为避免假图触发真实图服务，先删除本轮假图manifest，此操作明确不作为真实LightRAG删除验收。

## 首轮失败与清理

首轮10项业务检查通过，但finally重复Storage清理遇到ReadTimeout，完整报告未写出。保留 [initial-report.json](material_ingestion_jobs_20261027/initial-report.json)，明确从捕获输出重建、不补造运行时间或计数，success=false/cleanup=false。核验同一夹具创建事务的精确两个无邮箱临时ID后，清理残余Auth身份及本人Redis快照。

清理脚本改为在外部操作前提交测试DDL清理，并从启动时就保存临时owner清单；Storage清理失败也不再跳过DB清理及报告。确认轮10项通过且清理完成，3个任务结果与本轮唯一队列已移除。首轮中断前的结果缓存按Redis/Celery既有TTL留存，不把它们冒充已精确清除；不清理任何现有业务结果。正常服务日志/备份也不承诺清除。

## 边界

- 取消/租约的canonical事务栅栏已经实现，不表示Storage/外部图原子提交；上传至登记前的孤儿窗口、不可取消后台图线程、旧代码/手工管理员操作仍可能绕过协作锁。
- 同owner材料IO串行且繁忙返回409，浏览器交互、持续Beat、多主机、长任务/断连/P95尚待验收。
- 当前私有parsed/embedded检查点单份限20MiB，版本改变不复用；模型成功后检查点提交前中断仍可能重复计费。未声称真实AI质量提升或全资料批处理完成。
- 前端未改，不重复前端构建/浏览器；没有修改实际.env、用户技术指南或重启既有业务Worker。部署须排空旧材料Worker再切换060，不能混用旧无租约实现。

源码/最终报告/失败记录的文件SHA256见 [evidence.json](material_ingestion_jobs_20261027/evidence.json)。
