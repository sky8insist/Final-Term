# Learning Foundation 与 Next Best Action 阶段验收

日期：2026-10-07。结论：**本地技术交付有限通过**。此报告不替代全指南最终验收，也不改变历史 Dayend 质量 N/A 与真实浏览器验收未完成的结论。

## 基本信息与目标

本轮模块：课程结构、统一 Learner State、Exam Event/Syllabus、Response Confidence、Next Best Action/Dashboard。目标是使学习工具围绕稳定 Topic 身份和考试目标工作，避免改名破坏历史、阅读冒充掌握、自信冒充正确、首页无法指向下一步。

变更代码保留在当前工作区，未创建提交。用户已修改的指南保留原样。

## 实现范围

| 模块 | 改动 | 验收范围 |
|---|---|---|
| Course | course models/API/service，课程页与导航；考试、新闪卡、新计划任务绑定 | 名称别名、稳定 ID、归档、所有者/学科校验 |
| Learner State | learner_state_service、topic_coverage、Mastery v2 | not_started/covered/practicing/mastered/at_risk；掌握必须有 assessment 证据 |
| Exam Goal | exam_goal models/service，course API，ExamGoals UI | 大纲快照、考试日期、Topic 范围/权重、状态、原子替换 |
| Confidence | Exam models/API/service、答题 UI、Study Signal v2 | 可选信心、上下界、持久化、四象限反馈、Mastery 与计划信号 |
| Next Action | recommendation_service/API、Dashboard、client/types | 新鲜权威状态、考试范围/日期权重、冷启动、Top 3、原因、相关工具导航 |
| Privacy | 新用户表加入导出，数据库级科目删除级联 | 新表 RLS、scope FK、用户导出接入 |

## 数据库变化与运维

迁移 029–032 已在本地 PostgreSQL 安装，生产未部署：

- 029：knowledge_units、topic_aliases、artifact_topics；知识点新增分组/顺序/考试权重/来源引用/归档；review_tasks 绑定 Topic；事务化 resolve_course_topic。
- 030：topic_coverage，重复标记保留首个时间。
- 031：exam_responses.learner_confidence；grading_results.learner_confidence/confidence_mismatch。
- 032：syllabi、syllabus_topics、exam_events、exam_topic_map；save_course_exam 与 create_course_syllabus。

新关系用 owner/subject 复合外键校验；所有新表有 RLS。RPC 作为调用者执行，检查身份，匿名角色不具备 execute 权限。考试编辑与 Topic 范围替换是单事务，非法跨范围映射导致整笔回滚。

迁移失败在事务中回滚。若要回滚版本，应先回滚调用新表/RPC 的代码，并保留数据库数据；不要直接删除已有新目录/评估记录。长期运行的无 reload 后端需要重启后提供新路由。

## Functional / Edge Cases

- 显示名修改不改变 id/knowledge_key；原别名仍指向同一 Topic。规范化名称并发生成使用数据库事务锁。
- 空白名称、非法/NaN/Inf 权重与信心、负序号、重复考试/大纲 Topic、空考试范围拒绝。
- Topic 更新区分未传 unit_id 与显式 null，且不可通过接口更改 knowledge_key。重名与跨所有者/学科 Unit 关联拒绝。
- 覆盖仅产生 covered，不写 Mastery；首次练习为 practicing。足够正确 assessment、mastery≥0.8 与置信度≥0.5 才能 mastered；到期、掌握下降、高信心错误可 at_risk。
- 新历史记录带 algorithmVersion、evidenceType、Topic ID、stateBefore/stateAfter。闪卡不增加 assessmentCount；到期状态读取时计算。
- 信心未填为 null；0 保留；确认后信心锁定。相同答题重放返回原结果，改变信心 409，不重复更新 Mastery。
- 三天后考试的弱 Topic 优先于相同其他信号的范围外 Topic；过去/归档考试不加权。已掌握且未到期 Topic 不强制安排。
- 无 Topic 返回课程目录建立建议，无伪造掌握率。已归档 Topic 排除。推荐查询带 user/subject，分页避免默认行数截断。

## 验证证据

1. `cd backend; .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`：**243 passed, 3 warnings**。警告来自现有 Starlette/Supabase 弃用项。
2. `cd frontend; npm run lint`：通过。`npm run build`：通过，最大 chunk 248.29 kB，无 >500 kB 警告。最终强调文本调整后已再次通过 lint/build；git diff --check 无空白错误。
3. `verify_course_structure.py --apply`：本地迁移成功；别名/改名保留、覆盖幂等、信心读写/上下界、Topic/exam scope 外键、失败编辑整事务回滚、authenticated RLS 通过；临时验收行全部回滚。
4. `verify_course_structure.py --api`：本地真实 Supabase 与当前新代码联调；structure/learner-state/exam-goals/next-actions 均 200，结构与推荐跨用户访问 404。该脚本覆盖认证依赖，仅验证业务与真实数据集成，不能代替实际 JWT 登录 E2E。
5. UI 机械检查：Course 与信心区域首轮无发现；首页检查提示灰色文本与蓝色背景，新增强调行已改为深蓝文本；旧压缩 JSX 行还存在检测器跨元素归类的提示，不构成真实截图验收。

## AI / Learning Quality

| 指标 | 结果 |
|---|---|
| 真实题目 Topic 绑定率≥95% | N/A，未做真实生成样本评估 |
| 新闪卡全量 Topic 绑定样本评估 | N/A，代码强制绑定，尚无真实样本统计 |
| 推荐 Top-1 hit / reason faithfulness | N/A，仅确定性案例验证 |
| 掌握状态校准 / Confidence calibration | N/A，阈值与权重待真实学习记录评估 |
| Recall@5 / MRR / Citation Precision | 本轮未改检索策略，未重新声明质量指标 |
| Guided Session completion / mastery lift | N/A，Guided Session 待实现 |

## Known Limitations 与 Follow-up

- 真实浏览器的课程编辑、答题信心、首页开始动作尚未验收；当前客户端没有可调用的本地 Browser 控制工具。
- 既有语义重复 Topic 保留，不能自动误合并历史。历史未标注 evidenceType 的 Mastery 记录不自动认定为新 assessment；需要重新评估或后续可审计回填。
- 覆盖尚需用户标记，资料阅读/Guided Session 自动事件待接入。状态到期变化实时投影，主动通知与事件历史待 Worker 模块。
- 现有 Mastery 更新仍是多个写入步骤；评分、Mastery 与历史的全链路事务、并发去重与失败补偿需事件/Worker 模块解决。顺序重放的幂等不代表并发强幂等。
- 大纲为人工目录快照；自动 Syllabus 解析、资料来源绑定、先修关系输入、真实可用时间、跨时区配置待后续。
- 推荐进入现有 Tutor/Exam 工具，尚无 Guided Session；Adaptive Quiz/Stop Policy、Formal Test 分离及 Study Plan v3 未完成。
- 闪卡编辑后的全量重新绑定、其他产物 Topic 绑定、卡片级 spaced repetition 待 Artifacts/Flashcards 模块。
- 先以 P1 Guided Session、Adaptive Quiz、Study Plan v3 完成执行与评估闭环，再推进 P2 检索/切分与推荐质量评估。完整优先级见 OPTIMIZATION_PROGRESS.md。
