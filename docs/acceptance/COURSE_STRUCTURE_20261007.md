# Course Structure / Topic Domain 第一轮验收

日期：2026-10-07。结论：基础功能与本地数据库技术验收通过；指南完整模块验收有限通过。

## 目标与实现

建立 Subject → Unit → Topic 结构，保留既有 knowledge_key，使用 knowledge_points.id 作为稳定 Topic ID。章节、知识点分组、顺序、考试权重、改名及归档可从课程结构页面维护。归档代替硬删除，历史 Mastery/History 不修改。

新题目使用 resolve_course_topic 事务 RPC；规范化大小写与空白，命中旧别名时保留显示名称。新闪卡保存 knowledgePointId 和规范 knowledgeKey，并建立 artifact_topics 关联；新计划任务保存 knowledge_point_id，包括综合复盘任务。修改关系前校验所有者与学科，数据库复合外键防止 service role 写入跨范围关系。

## 代码与数据库

- 后端：models/course.py、api/course.py、services/course_service.py；exam_service.py、artifact_service.py、study_plan_service.py、privacy_service.py 接入。
- 前端：pages/Course/index.tsx，App、MainLayout、api/client、types 注册。
- 迁移：029_course_structure.sql；增加 knowledge_units、topic_aliases、artifact_topics，扩展 knowledge_points 与 review_tasks。三张新表开启 RLS，匿名角色不能执行解析 RPC。
- 回滚部署应先回滚调用新 RPC 的代码；数据库列/表不建议直接删除，否则会丢失新目录数据。迁移失败在事务内回滚。本地已应用，生产未部署。

## 验证证据

- pytest tests/test_course.py tests/test_exams.py tests/test_artifacts.py tests/test_study_plans.py tests/test_exam_generation.py -q：47 passed。
- npm run lint：通过。
- verify_course_structure.py --apply：029 本地安装，别名稳定 ID、用户改名保留、owner/subject 隔离、跨学科 Unit 外键拒绝、authenticated RLS 实测通过；验收数据回滚。
- 测试覆盖非法空白名称、NaN 权重、负序号、不可修改 knowledge_key、显式 null 与未传 unit_id 的区别、名称冲突、跨所有者/学科编辑零写入。

## 未完成与风险

- 未取得真实浏览器 UI 验收证据；前端构建与最终项目回归将在本轮其他 P0 模块接入后执行。
- 不自动合并历史语义同义知识点。迁移中冲突的历史别名按创建时间与 ID 确定性映射，但历史记录保留；人工合并与迁移审计后续补充。
- 真实题目绑定率 ≥95%、全部新闪卡绑定与全量计划任务绑定，需要真实模型生成样本统计；单元测试不替代 AI 质量验收。
- Heading 提案、原文 block 来源校验与自动抽取属于后续 Ingestion/Parse 模块。当前 source_refs 提供存储能力，不声明完成自动提取。
- 通用 Notes/Mind Map 等产物的完整 Topic 绑定随各产物模块完善；本轮接入闪卡。
- Syllabus 和 Exam Event 在后续独立迁移中实现，不包含在 029。
