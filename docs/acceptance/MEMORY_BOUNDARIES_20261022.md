# Memory / Learner Profile 验收 — 2026-10-22

本轮围绕指南第 20 节落实稳定偏好与业务学习状态的边界，不增加 Agent 或真实用户自动写入。

## 实现范围

- memory-boundary-v1 用保守中英文词法规则识别 preference/habit/difficulty/long_term_goal，拒绝已知学习/考试/复习状态与未识别文本。普通写入、旧审批和数据库触发器均检查；原安全扫描和敏感信息审批保留。自动候选一律需用户确认。
- 050 增加分类、provenance 与快照 policy_version/teaching_profile/manifest。来源由服务端写入，不接收客户端 provenance；事件必须属于本人同科目。历史记忆保留为 legacy，可查看/删除/重新确认，未分类内容不进入快照；不自动改写真实记录。
- 去重/匹配严格区分全局和各科目，按 ID 编辑保留原科目；相同文本可独立存在。容量仍按用户/target 汇总，局部操作不淘汰其他科目偏好。
- 快照 RPC 使用事务会话锁，绑定精确科目，只组合全局与当前科目合规内容。合规旧会话冻结、新会话更新；禁用记忆及旧版本快照返回空上下文。删除记忆清除本人快照，隐私删除优先于冻结。角色/篇幅偏好只保存白名单字段，RAG 使用冻结篇幅偏好，记忆不充当事实证据。
- 全局画像不再消费考试日期，也拒绝新日期写入；旧字段保留但读取返回 null。Assistant 计划不再回退全局日期，用户需明确当前考试目标或本次请求日期。教学角色限制现有角色集合。
- 30 天 Study Behavior Summary 以只读 API 聚合 Guided Session 数、完成/取消数与完成会话预算分钟，并标记来源、窗口和时间。预算分钟不等于实测学习时间，不复制 Mastery/成绩到 Memory，也不根据活动计数自动推断偏好。

## 验证结果

| 检查 | 结果 |
|---|---|
| 新增 memory boundary 单测 | 38 passed |
| 完整后端 pytest | 741 passed，3 项既有依赖弃用警告 |
| Ruff F、统一离线 quality gate | 通过 |
| git diff --check | 通过 |
| 本地 050 安装与事务回滚验收 | 通过 |
| 实际 Supabase 只读行为 API | 200 / 缺失或无权科目 404 / 匿名 401 |

单测覆盖分类正反例、混入状态拒绝、自动提案审批、旧请求重新检查、角色/输入/来源伪造拒绝、考试日期写入拒绝、RPC 错误映射、快照与 API 身份、科目匹配、legacy 同文重新确认与跨范围容量。

真实 SQL 验证 Python/SQL 分类一致、本人同科目来源事件约束与 provenance、跨科目同文、会话冻结/新会话更新/禁用/旧快照抑制、画像日期拦截、行为投影及私有 RPC/RLS。删除 Study Plan 后偏好存在；删除 Memory 后 Mastery 保留，旧快照失效。所有临时用户、业务记录和快照回滚。

API 使用真实本地 Supabase 与测试认证依赖覆盖，只读既有科目；没有修改真实用户记忆或调用模型/Embedding/付费服务。没有浏览器、真实 JWT、多进程并发或持续 Worker 验收。本轮没有前端变更，未重复前端构建。

## 复跑与部署

在 backend 执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_memory_boundaries.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

仅本地缺失 050 或刷新函数时添加 `--apply`；脚本拒绝远端数据库。其他环境先装历史迁移依赖和 050，再部署 API 与 Worker；重启 Worker 后才加载新的提案提示。本次未重启服务，未改实际 `.env` 或用户技术指南。分类/来源字段随现有隐私导出与删除，无新增表。

## 限制与后续

词法边界不是通用语义分类器，可能误拒或遗漏改写，应继续做真实多语言评测。当前 provenance 记录本次来源，不是多来源完整历史。既有去重/容量淘汰和审批并非整体原子事务，仍需 CAS/幂等发布；尚无行为/provenance 新管理界面、模型去重质量或长期学习效果证据。下一阶段为 Dayend / LangGraph 学习状态快照与建议边界，保留既有独立评审 N/A。
