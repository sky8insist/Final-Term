# 项目交接

更新：2026-11-23。当前迁移：**061**。本文件只保留接续必需的信息；此前942行记录完整归档至 [历史交接](docs/history/HANDOFF_HISTORY_20261123.md)。

## 本轮完成

1. **上传恢复**：Storage IO之前登记持久意图；文件清单、处理任务及registered状态原子提交。默认1小时后才处理未完成意图，按owner锁和令牌领取，失败退避，登记成功的文件不会被删除。隐私及科目删除覆盖尚未登记的目标路径，导出包含意图记录。
2. **图超时保护**：协作式异步调用超时后取消；等待图锁已超时的线程不再启动。不能立即取消的同步调用继续持有owner数据库事务，直到后台真正结束，期间同账号删除/上传返回409，避免锁先释放而后台迟到写入。
3. **文件精炼**：README与当前交接压缩，历史验收保留；移除冗余前端示例配置，其他必要配置统一为config.env.template，更新启动脚本及消费者；前端正式命名exam-ai-workbench。回归夹具和质量标签继续保留，因为它们是验证依据。

详细范围：[恢复与清理](docs/UPLOAD_RECOVERY.md)、[本轮验收](docs/acceptance/UPLOAD_RECOVERY_20261123.md)、[总进度](docs/OPTIMIZATION_PROGRESS.md)。

## 验证

本地PostgreSQL/Storage/真实owner锁共10项验收通过，临时账号和对象已清理；图使用显式测试协程。完整后端 **932 passed，3个既有弃用警告**；前端 **33 passed**，lint/build、Ruff F及离线quality gate通过，npm audit为0漏洞。最大前端chunk255.61 kB。初次完整回归的新测试锁替身绑定问题已修复并全量确认；esbuild/Node首次遇沙箱EPERM后按工具权限复跑。

历史基线为922项后端回归及材料摄取10项本地验收；学习记录页曾有Edge/Chrome各11项浏览器验收，不能外推为本轮全站浏览器通过。

## 部署约束

- 暂停投递、排空旧材料Worker，依序安装至061，再同时部署API/Worker并恢复Beat。不要混用旧无租约或无上传意图的Worker。
- UPLOAD_CLEANUP_ENABLED默认false；UPLOAD_CLEANUP_GRACE_SECONDS默认3600。DATA_RETENTION_ENABLED也仍默认false。安装迁移不会自动清理真实数据。
- owner锁跨后台IO保持；不能取消的供应商调用可能延长该账号繁忙时间。当前不提供强制释放并允许删除的旁路。
- 本轮未修改实际.env、未重启既有业务服务或启用真实用户清理；配置模板、环境文件及本机数据的发布边界见README。

## 下一步

- 无意图的历史孤儿对象需独立盘点；本轮不扫描和删除未知文件。
- 完成持续Beat、多机/断连/长任务/P95验收，验证真实MinerU/ASR/向量模型/图供应商。
- 原始二进制打包导出，服务日志/备份/SQLite副本保留策略及全站安全/浏览器验收。
- 整体计划成功率、独立测验补救指标和真实长期学习效果，详见总进度。

## GitHub

仓库：[sky8insist/Final-Term](https://github.com/sky8insist/Final-Term)，分支main。交付提交主题为“feat: complete learning workspace and harden upload recovery”，包含此前尚未提交的模块。确切提交号以main提交历史及本次交付回复为准；只使用非强制推送，本机环境、运行数据和密钥不发布。
