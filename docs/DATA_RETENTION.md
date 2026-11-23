# 数据保留与清理运维

版本：retention-v1，2026-10-27；060补充协作IO保护，061补上传意图与图后台锁延寿。当前代码依赖至061及新版API/Worker；清理为私有运维能力，没有面向用户的全局删除接口。

## 策略

以下是项目的可配置工程默认值，不代表法律规定。新增自动清理 **默认关闭**，不会因安装迁移就删除历史数据。

| 数据 | 默认保留规则 | 到期处理 / 保护 |
| --- | --- | --- |
| 原文件、音频原件/派生片段、MinerU附件 | 使用每条material_assets.expires_at；现有写入默认90天 | 仅ready/failed资料、无queued/running摄取任务及queued/transcribing音频片段时可领取；未设expires_at不补造期限 |
| 推荐审计、产品事件 | created_at后180天 | 有界删除正文和快照，保存最小去重指纹 |
| 学习完成cohort | deadline后365天 | 不在观察窗口内删除，不动当前任务/计划 |
| 首次预测样本、覆盖记录 | released_at后365天 | 删除历史样本，保留指纹防止重放重新计样本 |
| 学习领域事件 | occurred_at后180天 | 必须已消费且没有相关未成功projection任务；未消费/queued/running/dead保护，避免丢待处理或人工重试依据 |
| 去重凭据、学习任务回执 | 至所属科目/账号明确删除 | 凭据只保留owner/subject、类别、SHA256及清理时间，不保留原payload、答案或成绩；不是匿名数据，仍随隐私导出/删除处理 |
| 已解析正文/转录、笔记、成绩、计划、稳定记忆 | 继续随产品明确删除操作 | 本轮不按附件过期自动抹除权威学习记录；用户隐私删除沿用058 |
| 模型/安全/操作日志、Auth/Storage服务日志、备份、SQLite Dayend副本 | 本轮未新增自动期限 | 留待专门策略；不得宣称上述日志/副本已清除 |

审计/指标/事件窗口最短120天，长于产品最多90天的指标窗口并留出7天成熟余量。历史详情超过保留期限会消失/404；当前权威Mastery和成绩不由清理重写。旧任务回放由BEFORE INSERT去重凭据拦截，不生成新事件/样本/队列；旧已完成测验步骤恢复也不会生成新的补救cohort。

## 预览、执行与启用

backend目录下，先预览（默认只读候选，无Storage删除、无领取/凭据写入）：

```powershell
.\.venv\Scripts\python.exe scripts/run_data_retention.py
.\.venv\Scripts\python.exe scripts/run_data_retention.py --user-id <精确用户UUID>
```

确认运维范围后，手动执行一批需显式 `--execute`；可继续加 `--user-id` 限定本人范围。手动执行不依赖调度开关，命令本身表示运维执行意图。

```powershell
.\.venv\Scripts\python.exe scripts/run_data_retention.py --execute --user-id <精确用户UUID>
```

关系数据每类默认200条，最多1000；附件每次50条，最多100。`moreMayRemain=true`表示达到本批上限，可能尚有余量；并发SKIP LOCKED会跳过别人正在处理的行，一次0条不证明全库无待清理数据。重复运行分批推进，不在单任务内无限循环。

计划启用自动清理时设置部署环境并重启Worker/Beat：

```dotenv
DATA_RETENTION_ENABLED=true
RETENTION_AUDIT_DAYS=180
RETENTION_METRIC_DAYS=365
RETENTION_EVENT_DAYS=180
RETENTION_BATCH_SIZE=200
RETENTION_ASSET_BATCH_SIZE=50
```

复用原cleanup_expired_assets任务，Beat从每日改为每小时；该旧任务现在也受开关控制。**默认false会暂停原来的每日附件删除**，不是沿用旧任务无条件删除。此次只更新.env.example，没有更改实际.env、启用真实用户清理或重启现有服务。其他环境先部署至059，再部署代码和重启加载新配置。

## 失败与恢复

- 关系清理与SHA256凭据同一事务，失败整批回滚；每类ORDER BY到期时间/id、FOR UPDATE SKIP LOCKED，有界处理。receipt及必要全局到期索引已添加，规模/P95仍待测试。
- 附件领取在数据库中原子产生5分钟租约和新token；每个对象操作前核验当前token、租约、sha256、期限及无在途处理。只允许配置的材料桶及owner目录，异常路径保留并报UnsafeAssetPath。
- Storage成功后才确认删除manifest；Storage失败保留manifest、保存异常类别并退避（首次120秒，封顶24小时）。错误文本/密钥/路径不写入cleanup_error。数据库确认失败则任务报错，租约到期可重领；Storage删除已不存在的对象可安全重试。
- 新期限/哈希或新token不能被旧领取者确认删除。派生音频片段的asset_id按已有外键置空，已解析转录不跟随二进制过期删除；摄取重试没有原件时沿用“原文件已过期或不可用，请重新上传”。
- 失败信息可从material_assets的cleanup_attempts/cleanup_error/cleanup_retry_at及Celery结果定位。本轮未新增告警渠道或可视化运维台。

这不是Storage和PostgreSQL的跨服务原子事务。060已为合作的新上传、材料Worker、产品删除和附件清理补充同owner IO互斥，活跃IO期间清理跳过，不再只靠删除前的独立核验；见[摄取部署说明](MATERIAL_INGESTION_JOBS.md)。直接管理员/旧代码、不可取消的外部图后台线程仍不受完整约束；上传后未成功登记manifest的孤儿对象也不在清理范围。持续Beat、多Worker进程/主机、长时间运行、全库压力和真实音视频/LightRAG质量仍待验收。

本地合成夹具和隔离Worker证据见[验收记录](acceptance/DATA_RETENTION_20261027.md)；它不代表已经对真实用户执行或整夜运行。
