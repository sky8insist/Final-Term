# 上传恢复与超时保护验收

日期：2026-11-23。迁移：061_upload_intents.sql；[运行说明](../UPLOAD_RECOVERY.md)。

## 本地真实验收

[报告](upload_recovery_20261123/report.json)：**10/10 passed，success=true，cleanup=true**。

- pending预览只读，宽限期内不领取；真实Storage孤儿对象清理后持久确认，未完成材料可重新上传。
- registered文件受保护；登记确认丢失时以manifest为准恢复registered，不删文件。
- 登记错误回滚manifest及任务，上传意图继续用于清理。
- Storage故障为明确注入，保留记录/退避且只保存异常类别；恢复后可重试。
- 错误token、普通authenticated直接写入被拒绝，另一owner没有候选。
- 不可取消的测试协程超时后，真实PostgreSQL锁继续保持，产品隐私删除返回409；后台结束才关闭事务。
- 协作式协程被取消，没有迟到写入；事务随之释放。
- 科目和隐私删除覆盖pending目标，导出包含本人意图；测试账号及所有确切目标最终清理。

脚本 `backend/scripts/verify_upload_recovery.py` 仅允许本地数据库/Supabase/Redis。没有普通JWT、浏览器、真实模型或图供应商验收，也未启用真实用户自动清理。

## 仓库精炼

- 当前交接由942行归档后压缩；历史证据保持原样，避免删除失败记录。
- README移除冗长请求/响应示例和过时默认说明，保留启动、配置、验证与文档入口。
- 必要配置统一为config.env.template，删除根模板已覆盖的前端示例；启动/修复脚本及Supabase配置消费者同步修改。
- 前端包名从react-example改为exam-ai-workbench；回归数据集与质量标签是验证依赖，保留。
- .gitignore补充测试临时目录和本地数据库，提交前单独检查暂存范围及敏感信息。

## 回归结果

- 完整后端 **932 passed，3个既有弃用警告**；新增4项图生命周期和6项上传清理回归。首次新清理模块的测试替身绑定导致3项失败，修正后完整确认通过，没有放宽生产锁。
- 前端 **33 passed**，lint/build通过，最大chunk255.61 kB；esbuild/Node首次受沙箱EPERM阻止，按工具权限复跑成功。
- npm audit报告0漏洞，符合GitHub CI的critical门槛。
- Ruff F、compileall、离线quality gate通过；提交前检查配置消费者、文档链接、差异及敏感信息。GitHub CI新增前端lint和33项逻辑回归。
- GitHub目标为sky8insist/Final-Term的main；交付提交主题为“feat: complete learning workspace and harden upload recovery”，确切提交号在main历史及交付回复中核对。文件哈希见 [evidence.json](upload_recovery_20261123/evidence.json)。
