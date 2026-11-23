# 材料摄取恢复与部署

版本：ingestion-checkpoint-v1，2026-10-27。依赖迁移060及之前全部迁移。

2026-11-23续作已由061补上上传前意图和图超时后台锁延寿；当前部署与剩余范围以[上传恢复说明](UPLOAD_RECOVERY.md)为准，下文保留060机制的说明。

## 运行方式

- 异步上传先存Storage，再由register_material_upload在同一事务登记原件manifest和processing_tasks。任务行同时是持久投递记录，不依赖broker确认。投递失败保持queued/attempts=0并显示等待自动投递；每分钟Beat补扫最多50条。
- Worker原子领取任务，2分钟租约、每30秒心跳；重复活跃投递跳过，超时重领换token并增加attempts。自动最多沿用任务max_attempts（默认3次），失败30/60/90秒退避（封顶300秒）；耗尽变failed。手动重试沿用046的归属、原件可用与材料状态检查，开始新有界周期。
- parsed检查点保存经结构提取、ContentBlock验证及安全扫描的内容块；embedded检查点保存分块/父块及向量。版本包含原件hash、模型、chunk配置、解析配置及mock开关；版本改变不复用。检查点单份上限20MiB，超过会明确失败，不静默截断。
- 崩溃/失败后保留检查点，避免重新解析及重复生成向量。外部调用完成、检查点提交之前中断仍可能重复调用；不能宣称模型计费exactly-once。完成时删除大检查点；原件manifest被删除时也移除关联检查点；其余随任务/科目/账户删除，纳入本人隐私导出。
- 内容块、父子分块、向量、图状态、材料ready、任务succeeded及检查点清理在一个发布事务中核验租约/token。失败整批回滚；取消同事务撤销token并把材料置failed，旧Worker不能发布、写检查点或覆盖取消状态。
- LightRAG仍是可选增强：失败保留关键词/向量ready和图失败状态。图调用可能重复；PostgreSQL发布并不使外部图事务原子。特别是现有LightRAG超时后台线程可能晚于调用方返回结束，不能据此宣称图的所有迟到写入已被隔离。
- 章节提案/可选上传Notes只在核心发布后执行，失败不推翻成功；warning保存在任务metadata，Notes意图另由既有补扫恢复。解析期间MinerU批次进度保持，模型调用恢复本人trace/预算上下文。

## 同账号IO互斥

异步上传、同步旧上传、摄取执行、产品学习数据/账号删除、科目删除、附件清理共用owner级事务advisory lock。锁跨外部调用保持，独立数据库事务防止连接池换后端；嵌套隐私调用复用当前连接。

竞争操作非阻塞拒绝：产品请求返回409“资料正在处理或清理，请稍后重试”；Worker返回busy且不增加attempts，持久队列下轮补扫；附件清理跳过，租约到期再领取。同账号不同资料也串行，这是当前保守取舍，不是最大并行吞吐实现。取消不取得该IO锁，仍能立即通过数据库令牌栅栏撤销运行中的任务。

该锁只约束使用新代码的合作路径；直接Auth管理员删除、手工SQL、旧Worker或独立工具不遵守它。Storage上传后、登记事务前的崩溃仍可能留下孤儿对象；不支持后台线程取消的外部服务、全量图清理和跨服务补偿仍需续作。客户端不能直接调用私有摄取RPC写入任意发布数据。

## 部署与恢复

1. 暂停新材料任务投递并停止/排空旧版材料Worker，避免旧无租约代码和新版并行处理同一任务；不要只滚动更新一部分Worker。
2. 依序安装迁移至060，部署API和Worker代码，再恢复材料投递并重启Beat。迁移不主动处理真实排队任务；旧running记录没有租约，会由新版领取恢复，因此必须先排空旧执行者。
3. 启动时可运行既有worker.recover，但材料任务只重新投递，不再重置running、attempts或偷取租约；常规恢复由每分钟sweep_material_ingestions负责。考试等旧恢复逻辑保留，未宣称已全面改为新机制。
4. 观察processing_tasks.status/attempts/error_code、ingestion_available_at、ingestion_lease_until及metadata.failedStage；错误仅保存异常类别，不保存provider密钥或错误正文。服务角色可查询检查点stage/pipeline_version，普通用户不能直接读取。

本轮没有更改实际.env、启动既有业务消费者或重启现有Worker/Beat。前端接口结构不变，处理中的并发上传/删除可能新增409；浏览器提示与全流程仍待验收。持续Beat、跨主机断连、吞吐/P95、长材料大检查点、真实MinerU/ASR/向量模型/LightRAG及孤儿补偿不在本次本地合成验收结论内。

本地复跑（backend）：

```powershell
.\.venv\Scripts\python.exe scripts/verify_material_ingestion_jobs.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_ingestion_full
```

verify脚本仅首次本地安装时加--apply，已有060不要重复建表。验收使用真实TXT解析、DB/Storage/Redis/独立solo Worker，但向量和图明确为测试替身，见[验收记录](acceptance/MATERIAL_INGESTION_JOBS_20261027.md)。
