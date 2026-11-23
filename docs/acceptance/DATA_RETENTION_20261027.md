# 数据保留与运行可靠性验收

日期：2026-10-27。承接隐私完整性阶段，范围限定保留策略、去重保护及到期附件清理；[策略与运维入口](../DATA_RETENTION.md)。

## 结果

- 新增并本地安装 **059_data_retention.sql**，包括私有清理/预览RPC、receipt RLS与指纹、重放拦截、附件租约/退避/确认及查询索引。没有实际.env改动、真实用户清理或现有Worker/Beat重启。
- [最终报告](data_retention_20261027/report.json)：**10项全部通过，success=true，cleanup=true**。数据为2个本轮新建用户的合成记录及Storage占位文件，不是实际学习效果或ASR质量。
- 新增15项回归，完整后端 **914 passed，3个既有弃用警告**；Ruff F、离线quality gate、diff检查通过。运维CLI还用精确不存在的测试UUID验证只读预览，不扫描或删除真实用户记录。
- 两个实际PostgreSQL连接验证SKIP LOCKED互斥；真实本地Storage删除、Redis传输及独立命名队列/solo Celery Worker验证3次投递。没有TestClient身份覆盖，也没有浏览器/普通用户JWT验收：本轮入口为服务角色私有运维。
- 首轮 [initial-report.json](data_retention_20261027/initial-report.json) 保留：当时9项检查都通过，但脚本错误地预期10项，所以success=false；不得把它当通过报告。补充第10项旧步骤恢复检查并稳定夹具选择后，最终10/10通过。未伪造或覆盖首轮报告。

## 模块一：关系数据策略与去重

1. 默认审计/产品事件180天、cohort deadline/预测样本365天、已消费领域事件180天；最短120天，保护现有90天指标及7天成熟窗口。默认只读预览，每类有界处理，自动调度默认关闭。
2. 真实SQL验证六类候选各2条预览不写数据；两批分别每类删除2/1条后下一批为0。近期记录、另账号记录、未消费事件、关联死信未成功任务均保留。
3. 用临时拒绝删除触发器注入SQL故障，receipt及关系删除整批回滚；测试触发器/函数随后回滚，不留在数据库。
4. 记录owner/subject/类别/SHA256/清理时间的最小凭据，与删除同事务。清理后的六类旧来源重放全部不落库；产品/领域/cohort即使换新行UUID仍按源唯一键拦截。领域事件不重建outbox，首次预测不变成新的校准样本。
5. 原capture_learning_cohort依赖step.completed事件判断旧成绩，事件过期后改查指纹补充保护。真实插入旧已完成低分步骤，验证没有新quiz_remediation cohort。
6. receipt没有authenticated直接读取或写入权限，清理RPC仅service_role可调；058导出自动包含本人凭据，正常隐私清理也移除凭据。凭据为伪名数据，不能宣称匿名；任务回执与凭据长期规模仍需后续管理。

## 模块二：附件租约与恢复

- 依每条expires_at，保护null/未来期限、非终态资料、在途摄取与转录，不回填历史过期日期。领取5分钟租约、新token及原sha256/期限快照；执行前重验，成功后CAS确认。
- 两个连接同时领取不同对象；错误token拒绝。续期后旧领取者不能检查通过或删除manifest；失败保留manifest并记录异常类别、等待退避。配置桶/本人路径校验有单元回归覆盖。
- 真实Storage先删除一个文件，模拟进程在数据库确认前中断；强制该测试租约过期。隔离Worker第1次重新删除不存在的对象并确认成功，第2次清理退避已解除的另一个文件，第3次领取为0。未来及有在途任务的两个文件仍可实际下载，manifest保留。
- Storage失败、数据库确认失败、失效租约和已续期确认分别有回归；外部错误不会删除关系清单或把provider错误正文写入状态。真实文件失败不是服务断网实验，SQL故障/崩溃/退避到期均明确为测试注入。

## 复跑与边界

backend目录下：

```powershell
.\.venv\Scripts\python.exe scripts/verify_data_retention.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_tmp_retention_full
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

首次本地安装迁移可给verify脚本加 `--apply`；重复使用已安装数据库时不要重复创建表。只允许本地DB/Supabase/Redis，调度开关只在测试进程临时打开且Worker任务限定生成的owner；不消费既有业务队列。最后清理精确临时账号、4个Storage路径、本人Redis键、3个结果及唯一队列；成功SQL清理不代替产品隐私API验收，产品API证据在上轮058记录。

源码/报告哈希另见 [evidence.json](data_retention_20261027/evidence.json)。持续Beat/跨主机并发/P95、所有上传与删除的统一栅栏、孤儿Storage/真实LightRAG、原始二进制打包导出、模型/安全/操作及服务日志/备份/SQLite副本期限仍未完成；canonical转录文本和学习成绩不因附件到期自动删除。本轮未改前端，不重复前端构建或浏览器验收。
