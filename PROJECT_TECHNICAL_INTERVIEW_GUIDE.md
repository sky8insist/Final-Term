# Final-Term AI 期末复习 Agent 对标 StudyFetch 优化规划

## 0. 规划目标

本规划以当前 `sky8insist/Final-Term` 仓库为基础，对照 StudyFetch 当前官方产品文档，目标不是复制 StudyFetch 的全部功能，而是回答三个问题：

1. **当前系统哪些能力已经具备，不应该重复建设？**
2. **和成熟 AI 学习产品相比，真正缺失的闭环在哪里？**
3. **怎样在现有架构上演进，让项目既更像成熟产品，又保留适合面试展示的工程深度？**

StudyFetch 当前的核心已经不是简单的“资料 → AI 问答”。其 Study Plan 会围绕 syllabus、考试时间、topic、Covered/Mastered 状态组织学习路径，并推荐下一步学习行为；Guided Chat 则会先生成计划，让学生确认，再带学生依次完成 Notes、Flashcards、Quiz、Test 等活动。

其 QuizFetch 还记录学生的**答题正确性和主观信心**，在错误过多时暂停继续答题并推荐先复习；Flashcards 支持 spaced repetition；不同学习工具之间可以通过 Turn Into 互相转换。

因此，本项目下一阶段的核心目标定义为：

> **从“拥有多个 AI 学习功能”，升级为“拥有统一 Learner State，并能根据考试目标持续计算 Next Best Action 的期末复习 Agent”。**

---

# 一、现状与 StudyFetch 差距汇总

## 1.1 当前项目已经具备的基础

当前仓库已经不是简单 Demo，而是拥有比较完整的技术底座：

| 能力 | 当前实现 |
|---|---|
| 用户与隔离 | Supabase Auth、JWT、RLS、user/subject workspace |
| 资料接入 | PDF、Office、图片、TXT、音频 |
| 文档解析 | MinerU v4 + Native Parser + Local Fallback |
| 多模态 | 图片理解、OCR、表格、公式、音频转写 |
| 内容模型 | `content_blocks` + `material_chunks` |
| 向量检索 | pgvector |
| 图/混合检索 | LightRAG + PostgreSQL + Vector + RRF |
| 引用 | source/page/block/bbox/time metadata |
| Grounding | Evidence Assessment + 证据不足拒答 |
| AI 学习室 | beginner / crash course / Socratic / examiner |
| 对话状态 | `learning_interactions` |
| 学习产物 | Outline、Mind Map、Flashcards、Formula Sheet 等 |
| 练习系统 | 多题型生成、固定答案、Rubric、主观题评分 |
| 学习状态 | `knowledge_points`、`knowledge_mastery`、`mastery_history` |
| 间隔复习基础 | `next_review_at` + correct streak |
| 学习信号 | accuracy / mastery / forgetting / dialogue confusion 等 |
| 复习计划 | Need Score + 时间预算 + 阶段化计划 |
| Memory | Hermes Memory + session snapshot |
| Agent | Router / Supervisor / Planner / Critic / Safety 等 |
| 异步任务 | Celery + Redis |
| 质量评测 | Recall@K、MRR、Citation Precision 等 |
| 可观测性 | Model Call / Operation / Trace / Cost |
| 安全隐私 | Prompt Injection Scan、数据导出、删除 |

因此，**最大的风险不是能力太少，而是能力“碎片化”。**

---

# 二、最核心的差距

## 差距 1：缺少统一 Topic Learning State

你现在已经分别有：

```text
knowledge_points
knowledge_mastery
mastery_history
grading_results
wrong_answers
learning_interactions
chat_messages
review_tasks
```

但用户看到的还不是一个统一的：

```text
Topic
├── Not Started
├── Covered
├── Practicing
├── Mastered
└── At Risk
```

StudyFetch 明确区分 Covered 和 Mastered，并通过 assessment 确认 Mastery，而不是“看过 = 掌握”。

### 优化核心

建立统一：

> **TopicState / LearnerState**

所有学习行为最终都更新同一个知识点状态。

---

## 差距 2：Study Plan 已经很好，但还不是完整 Next Best Action Engine

你当前 `study_signal_service.py` 已经计算：

```text
masteryGap          35%
practiceLoss        20%
forgetting          15%
dialogueConfusion   15%
importance          10%
dataConfidence       5%
```

这其实已经是一个不错的 Recommendation Engine 雏形。

但是目前计划主要输入：

```text
学习表现
+
exam_date
+
daily_minutes
```

还缺：

```text
Syllabus
Exam → Topics 映射
Topic prerequisite
正式的 Covered/Mastered 状态
Flashcard due date
主观 confidence mismatch
用户真实可用时间
```

---

## 差距 3：Multi-Agent 有技术结构，但用户体验上还没有真正变成 Agent

现在更像：

```text
用户问
↓
Router
↓
Retriever
↓
LLM
↓
回答
```

成熟 Agent 应该是：

```text
用户目标
↓
理解当前状态
↓
制定 Session
↓
用户确认
↓
执行 Step 1
↓
观察结果
↓
决定 Step 2
↓
更新 Learner State
↓
下一步行动
```

StudyFetch Guided Chat 的关键价值就是：

> **Regular Chat answers questions；Guided Chat runs a plan。**

它会读取当前学习路径、材料和过去学习情况，然后提出学习计划并实际带用户执行。

---

## 差距 4：Assessment 记录“对错”，但还没有充分记录“知道自己会不会”

StudyFetch QuizFetch 同时记录：

```text
Correctness
+
Confidence
```

并将其用于 Mastery 和后续推荐。

你的 `mastery_service.py` 已经支持：

```python
self_rating
hints
response_seconds
difficulty
correct
```

说明**底层实际上已经具备能力**。

现在缺的是：

> 前端正式采集 confidence，并把它接入 Exam → Mastery → Study Plan。

---

## 差距 5：学习工具之间没有完全统一

目前已有：

```text
Mind Map → Flashcards
Mind Map → Exam
Study Plan → Study Room
Study Plan → Exam
```

但还不是统一：

```text
任何学习对象
      ↓
Turn Into
 ├ Notes
 ├ Flashcards
 ├ Quiz
 ├ Test
 ├ Tutor
 └ Mind Map
```

StudyFetch 已经把 Notes、Quiz、Flashcards、Live Lecture、Tutor 等来源互相转换。

---

# 三、目标系统架构

最终应该从现在：

```text
Materials
↓
RAG
↓
Chat / Exam / Flashcard / Plan
```

升级为：

```text
                  ┌─────────────────┐
                  │    Exam Goal     │
                  │ date / topics    │
                  └────────┬────────┘
                           │
Syllabus ────────→ Topic Knowledge Graph
                           │
                           ▼
                 ┌──────────────────┐
                 │   Learner State   │
                 │ mastery           │
                 │ confidence        │
                 │ forgetting        │
                 │ misconception     │
                 │ covered/mastered  │
                 └─────────┬────────┘
                           │
                           ▼
                 Next Best Action
                           │
                  ┌────────┴────────┐
                  ↓                 ↓
             Study Plan       Guided Session
                  │                 │
         ┌────────┼───────┐         │
         ↓        ↓       ↓         ↓
       Notes  Flashcard  Quiz ←→ AI Tutor
         │        │       │
         └────────┴───┬───┘
                      ↓
                 Assessment
                      ↓
              Update Learner State
                      ↓
               Re-plan / Schedule
```

---

# 四、数据库基础改造

这是其他所有优化的前置任务。

当前 migration 已经到 `028`，建议从 `029` 开始。

---

## Module 0：Course Structure / Topic Domain

### 涉及已有模块

```text
knowledge_points
subjects
materials
study_plans
questions
```

### 目标

把目前比较松散的 `knowledge_key` 升级成正式课程结构：

```text
Subject
  ↓
Unit
  ↓
Topic
  ↓
Knowledge Point
```

### 建议新增

`029_course_structure.sql`

新增：

```text
knowledge_units
syllabi
exam_events
exam_topic_map
```

扩展 `knowledge_points`：

```text
unit_id
sequence_index
syllabus_weight
source_refs
```

### 优化步骤

1. 保留 `knowledge_key` 兼容现有数据。
2. 给 `knowledge_points` 增加稳定 `topic_id`/unit 关系。
3. MinerU 解析后，根据 heading 层级产生候选章节。
4. LLM 只负责“归并/命名”，不负责凭空创造结构。
5. 用户可以修改 Unit/Topic。
6. 所有 Exam、Flashcard、MindMap、StudyPlan 最终绑定 `knowledge_point_id`。

### TODO

- [ ] 新建 `knowledge_units`
- [ ] knowledge_points 添加 `unit_id`
- [ ] 添加 topic sequence
- [ ] 添加 source block references
- [ ] 添加 syllabus weight
- [ ] questions 强制优先绑定 knowledge_point_id
- [ ] artifacts 添加 topic IDs
- [ ] review_tasks 添加 knowledge_point_id
- [ ] 后端增加 Topic CRUD
- [ ] 前端增加课程结构查看/编辑

### 验收

给定一门课程：

```text
数据库中不存在两个实际相同但 knowledge_key 不同的核心知识点。
```

要求：

- 95%+ 自动生成题目能绑定 Topic。
- 所有新生成 Flashcard 能绑定 Topic。
- 所有 Study Plan Task 能定位到 Topic。
- 删除/修改显示名不破坏历史 Mastery。

---

# 五、Dashboard 模块

## 当前

`frontend/src/pages/Dashboard`

目前主要显示：

```text
今日学习分钟
完成任务
连续学习
Subject Cards
总体进度
Mastery
```

## 差距

当前 Dashboard 回答：

> “我学了多少？”

但成熟学习助手首先应该回答：

> **“现在最应该做什么？”**

### 目标

首页新增：

```text
Next Best Action
Upcoming Exam
Due Reviews
Weak Topics
Today Tasks
```

### 优化步骤

1. Dashboard 请求统一 Recommendation API。
2. 服务端根据 Study Signal 返回 Top 3。
3. 第一张卡必须是：

```text
现在建议：
复习 Self-Attention
原因：
3 天后考试
掌握度 48%
最近两次练习错误
预计 25 分钟
```

4. 一键进入 Guided Session。

### TODO

- [ ] 新增 `/recommendations/next-actions`
- [ ] Dashboard Next Best Action Card
- [ ] Upcoming Exam Card
- [ ] Due Review Card
- [ ] Weak Topic Ranking
- [ ] recommendation reason 展示
- [ ] 数据不足时明确显示 Cold Start

### 验收

对于一个已有：

```text
mastery 0.3
exam in 3 days
```

的知识点：

必须稳定出现在高优先级推荐中。

---

# 六、Materials / Ingestion 模块

## 当前模块

```text
materials.py
material_service.py
ingestion_service.py
task_service.py
worker/tasks.py
Materials/index.tsx
```

已有能力已经较强：

```text
upload
hash dedup
private storage
Celery
MinerU
embedding
LightRAG indexing
```

## StudyFetch 差距

StudyFetch 上传资料时可以直接选择生成不同深度 Notes，并控制 Chapter Splitting。

### 不建议

继续无限增加文件格式。

### 应该优化

上传动作本身变成：

```text
Upload
├ Generate Notes
├ Detect Syllabus
├ Chapter Split
└ Extract Topics
```

### TODO

- [ ] 上传增加 `materialPurpose`
- [ ] 增加 syllabus 类型
- [ ] 增加 chapter splitting
- [ ] 上传后生成 Topic proposals
- [ ] 用户 Accept / Reject Topic
- [ ] 失败阶段显示 parsing/embedding/indexing
- [ ] 增加 Retry
- [ ] 增加原文件预览
- [ ] 支持“上传后自动生成笔记”

### 验收

上传一个 100 页 PDF 后：

```text
原文件
+
章节
+
Topic
+
Blocks
+
Chunks
```

必须均能追溯。

---

# 七、MinerU / Parse / Multimodal 模块

## 当前

```text
mineru_parser.py
mineru_client.py
mineru_adapter.py
parse_service.py
multimodal_service.py
audio_service.py
```

这一块目前已经是你的项目亮点。

## 优化目标

不要简单增强 OCR。

下一步应该增强：

> **Semantic Document Structure**

### 优化步骤

### Step 1：Heading Tree

从 MinerU block：

```text
heading level
page
sequence
```

建立：

```text
Chapter
 ├ Section
 │ ├ Paragraph
 │ ├ Formula
 │ └ Table
```

### Step 2：Syllabus Parser

专门识别：

```text
课程名称
章节
考试时间
教学进度
评分方式
考试范围
```

### Step 3：Lecture

你现在已经能处理音频。

后续增加：

```text
Record
↓
Audio Segment
↓
Transcript
↓
Topic Alignment
↓
Knowledge Base
```

StudyFetch 的 Live Lecture 就是实时记录、转录，并把 lecture 转换成后续学习材料。

### TODO

- [ ] Heading hierarchy
- [ ] Figure-caption association
- [ ] Formula-context association
- [ ] Table-caption association
- [ ] syllabus parser
- [ ] transcript topic segmentation
- [ ] transcript → Topic mapping
- [ ] parser confidence telemetry

### 验收

随机抽取 30 页复杂课件：

必须分别检查：

```text
阅读顺序
标题层级
表格完整性
公式完整性
page traceability
```

---

# 八、Chunk 模块

## 当前

`chunk_service.py`

目前：

```text
每个 Block 独立切
chunk_size=800
overlap=120
```

优点是 traceability 很好。

### 问题

仍然属于：

> **Fixed-size semantic-light chunking**

### 优化目标

改成：

```text
Structure-aware Chunking
```

### 策略

优先边界：

1. heading
2. paragraph
3. semantic sentence
4. table
5. formula + surrounding explanation

### 推荐结构

```text
Parent Chunk
章节/知识点

Child Chunk
具体检索内容
```

检索 child，生成时返回 parent context。

### TODO

- [ ] 保留当前 800/120 baseline
- [ ] 新增 semantic chunker
- [ ] 增加 parent_chunk_id
- [ ] 表格不跨 cell 乱切
- [ ] 公式携带上下文
- [ ] 对比 baseline vs semantic chunk
- [ ] 加 chunk quality dataset

### 验收

在相同 Retrieval Evaluation 集上：

> 新 chunk 策略 Recall@5 不低于旧版本，并争取相对提升 ≥10%。

---

# 九、Retrieval / LightRAG 模块

## 当前

```text
retrieval_service.py
vector_store.py
lightrag_service.py
embedding_service.py
```

已有：

```text
LightRAG
Vector Search
Keyword Search
RRF
```

这是项目非常值得保留的亮点。

### 当前明显优化点

代码中 LightRAG：

```python
enable_rerank=False
```

RRF 后也没有正式 Cross Encoder。

### 目标链路

```text
Query
↓
Intent / Query Rewrite
↓
Vector + Keyword + LightRAG
↓
RRF Candidate Set
↓
Reranker
↓
Dynamic Top-K
↓
Evidence Assessment
```

### TODO

- [ ] 引入 reranker interface
- [ ] 保留 no-rerank baseline
- [ ] candidate K 例如 20
- [ ] rerank 后 Top-K
- [ ] Dynamic K
- [ ] definition/problem/comparison query 分类
- [ ] query rewrite
- [ ] parent context expansion
- [ ] source diversity constraint
- [ ] 建 RRF vs RRF+rerank 实验

### 验收指标

必须比较：

```text
Recall@5
MRR
Citation Precision
Citation Hit Rate
Latency P95
```

另外：

```text
User A 查询不得召回 User B
Subject A 不得召回 Subject B
```

Isolation Rate：

> **100%**

---

# 十、Evidence / RAG QA 模块

## 当前

```text
rag_service.py
evidence_assessment_service.py
answer_evaluation_service.py
```

优点：

- evidence insufficient reject
- source/page citation
- external knowledge 独立标识
- temperature=0
- injection defensive prompt

### 当前不足

Evidence Assessment 目前主要依赖：

```text
token overlap
+
retrieval score
+
text amount
```

### 优化

增加：

```text
Question Coverage
Claim Coverage
Source Diversity
Citation Entailment
```

采用两阶段：

### Stage 1

确定性：

```text
score
keyword overlap
citation count
source coverage
```

### Stage 2

仅 borderline case：

LLM / NLI 判断：

> 这些证据是否足够回答？

### TODO

- [ ] evidence score v2
- [ ] claim-citation verifier
- [ ] citation coverage
- [ ] fabricated citation = hard fail
- [ ] answer-level grounding score
- [ ] insufficient evidence benchmark
- [ ] external knowledge section强隔离

### 验收

测试集至少包括：

```text
资料存在答案
部分存在
完全不存在
诱导模型编造
跨学科污染
```

必须做到：

- invented citation = 0
- 无资料问题拒答率达到目标
- 有充分资料时避免过度拒答

---

# 十一、AI Study Room / Assistant 模块

## 当前

```text
assistant_service.py
router_agent.py
role_service.py
conversation_context_service.py
dialogue_act_service.py
learning_interaction_service.py
answer_evaluation_service.py
AIStudyRoom/index.tsx
```

这是升级 Agent 的核心。

---

## 最大优化：增加 Guided Study Session

当前：

```text
用户问一句
→ 回一句
```

目标：

```text
用户：
“3天后考试，帮我复习 Transformer”

Agent:
1. 读取 Learner State
2. 读取 Exam Goal
3. 制定 Session
4. 用户确认
5. 执行每一步
6. 每一步评价
7. 动态调整
```

StudyFetch Guided Chat 就是先提出 plan，允许学生修改，再逐步执行。

### 新增

```text
study_sessions
study_session_steps
```

建议 migration：

`031_guided_sessions.sql`

### Session Example

```text
Goal:
掌握 Self-Attention

Step 1
Review Notes
10 min

Step 2
Socratic Explanation
5 min

Step 3
Flashcards
5 cards

Step 4
Adaptive Quiz
5 questions

Step 5
Mastery Check
```

### TODO

- [ ] Guided Session API
- [ ] create session
- [ ] plan preview
- [ ] accept/edit plan
- [ ] session current step
- [ ] resume session
- [ ] skip step
- [ ] step completion
- [ ] dynamic replanning
- [ ] current context injected into assistant
- [ ] quiz 中禁止直接泄露答案
- [ ] Session summary
- [ ] session → mastery update

### 验收

一次完整 Session：

```text
Start
→ Accept Plan
→ Notes
→ Socratic
→ Quiz
→ Mastery
→ Next Recommendation
```

必须无需用户返回 Dashboard 手动寻找下一功能。

---

# 十二、Artifacts / Notes 模块

## 当前

```text
artifact_service.py
artifacts.py
```

已有：

```text
outline
mind_map
flashcards
formula_sheet
glossary
comparison
cheat_sheet
```

### StudyFetch 差距

StudyFetch Notes 是独立且可编辑的学习材料，并支持：

- 不同详细程度
- source citations
- version history
- Turn Into
- AI 局部编辑


### 建议

新增：

```text
artifact_type = notes
```

### Notes Mode

```text
summary
standard
comprehensive
exam_focus
```

### TODO

- [ ] artifact constraint 增加 notes
- [ ] Notes generation
- [ ] Notes → citations
- [ ] Notes editor
- [ ] version history
- [ ] user edited 标记
- [ ] selected text AI rewrite
- [ ] Notes → Flashcards
- [ ] Notes → Quiz
- [ ] Notes → MindMap

### 验收

生成 Notes 后：

任何主要观点都应能追溯到 source/page。

---

# 十三、Mind Map 模块

## 当前

已经支持：

```text
Knowledge View
Exam Importance View
Citation validation
Node → Flashcards
Node → Exam
```

这实际上已经不错。

### 优化重点

让 MindMap 不只是 Artifact，而成为 Topic Graph 的可视化。

### TODO

- [ ] node 绑定 knowledge_point_id
- [ ] mastery overlay
- [ ] Covered/Mastered 状态颜色
- [ ] prerequisite edge
- [ ] misconception indicator
- [ ] due-review indicator
- [ ] node → Guided Session
- [ ] node → Study Plan
- [ ] 新材料加入后提示 graph diff

### 验收

点任意知识节点：

应看到：

```text
Mastery
Confidence
Last Review
Next Review
Exam Relevance
Sources
Actions
```

---

# 十四、Flashcards 模块

## 当前

已经有：

```text
again
hard
good
```

并且会：

```text
rating
↓
record_performance
↓
Mastery
↓
next_review_at
```

所以不要重新做“间隔复习”。

### 真正需要升级

目前是**知识点层面的间隔复习**，还不是完整：

> Card-level Scheduler

StudyFetch Flashcards 明确提供 Spaced Repetition。

### 建议新增

`032_flashcard_scheduler.sql`

```text
flashcard_review_state

card_id
difficulty
stability
last_review
next_review
review_count
lapse_count
```

### Rating

升级：

```text
Again
Hard
Good
Easy
```

### TODO

- [ ] 增加 Easy
- [ ] 每张 Card 独立 schedule
- [ ] due queue
- [ ] 今日待复习
- [ ] overdue
- [ ] Card review history
- [ ] Card → Topic mastery
- [ ] Topic mastery → Study Plan
- [ ] 后期评估 FSRS

### 验收

同一个 Card：

```text
Again
```

后 next review 必须比：

```text
Easy
```

更早。

且刷新页面后状态保持。

---

# 十五、Exam / Assessment 模块

## 当前优势

这一模块实际上已经比较成熟：

```text
question blueprint
multi question types
duplicate validation
citation binding
fixed rubric
objective grading
subjective grading
wrong answer
mastery update
async generation
```

不要推倒重来。

---

## 优化 1：Formal Exam 和 Adaptive Quiz 分离

现在 Exams 同时承担：

```text
考试
+
练习
```

建议正式区分：

```text
Formal Test
Adaptive Quiz
```

### Formal Test

强调：

```text
题型
分数
限时
完整提交
```

### Adaptive Quiz

强调：

```text
Topic
Confidence
Feedback
Mastery
Stop/Continue Policy
```

---

## 优化 2：Confidence Rating

扩展 `exam_responses`：

```text
self_confidence
response_seconds
hint_count
```

### 四象限

```text
正确 + 高信心
→ Strong

正确 + 低信心
→ Unstable

错误 + 低信心
→ Weak

错误 + 高信心
→ Misconception
```

这是极有价值的学习信号。

---

## 优化 3：Adaptive Stop Policy

StudyFetch 在错误过多时会暂停 Quiz，并建议回去学习。

你的规则可以自己定义：

```text
连续错误 >= 3
OR
Topic recent accuracy < 40%
OR
high-confidence wrong >= 2
↓
Pause Quiz
↓
Recommend Tutor / Notes
```

### TODO

- [ ] assessment_mode
- [ ] response confidence
- [ ] response seconds
- [ ] hint count
- [ ] misconception classification
- [ ] adaptive stop
- [ ] remediation route
- [ ] quiz resume
- [ ] per-question mastery progress
- [ ] question history
- [ ] retake logic

### 验收

构造：

```text
连续 3 题错误
```

系统必须：

```text
停止继续刷题
→ 推荐复习
→ 完成复习后允许继续
```

---

# 十六、Mastery 模块

## 当前

`mastery_service.py`

已有：

```text
previous mastery
correct
difficulty
hint
response seconds
self rating
Bayesian-style smoothing
confidence
correct streak
next review
```

底子非常好。

### 最大问题

目前：

```text
confidence
```

更多是：

> 数据量置信度

而用户自己的：

> “我有多确定”

是 `self_rating`。

这两个概念一定要严格分开。

### 建议变量

```text
mastery_score
mastery_confidence
learner_confidence
retention_risk
misconception_risk
state
```

### State Machine

```text
NOT_STARTED

↓ 第一次有效学习

COVERED

↓ 有练习证据

PRACTICING

↓ mastery >= threshold
+ sufficient evidence

MASTERED

↓ 到期 / 表现下降

AT_RISK
```

### TODO

- [ ] 明确变量语义
- [ ] Covered 状态
- [ ] Practicing 状态
- [ ] Mastered 条件
- [ ] At Risk 条件
- [ ] misconception risk
- [ ] confidence mismatch
- [ ] state transition history
- [ ] mastery versioning
- [ ] calibration evaluation

### 验收

不能出现：

> 只阅读一次资料 → Mastered。

Mastered 必须有 assessment evidence。

---

# 十七、Study Signal 模块

## 当前

这是系统真正很有潜力的一块。

目前 Need Score 已有：

```text
masteryGap
practiceLoss
forgetting
dialogueConfusion
importance
dataConfidence
```

### 建议 v2

增加：

```text
examUrgency
syllabusWeight
reviewDue
confidenceMismatch
misconceptionRisk
prerequisiteImpact
```

变成：

```text
NeedScore =
masteryGap
+ practiceLoss
+ forgetting
+ confusion
+ misconception
+ examUrgency
+ importance
+ prerequisite
```

### 注意

不要让 LLM 直接计算分数。

LLM 只负责：

> 解释为什么推荐。

### TODO

- [ ] `study-signal-v2`
- [ ] exam urgency
- [ ] syllabus weight
- [ ] review due
- [ ] confidence mismatch
- [ ] misconception risk
- [ ] prerequisite propagation
- [ ] reason codes
- [ ] explain recommendation
- [ ] v1/v2 offline comparison

### 验收

固定输入必须产生固定 Score。

Recommendation 可解释：

```text
为什么今天推荐这个？
```

必须返回具体信号，而不是：

> AI 认为适合。

---

# 十八、Study Plan / Review 模块

## 当前

当前已经比一般学生项目复杂很多：

```text
days remaining
daily minutes
weekend capacity
phase
need score
repeat spacing
final mock
```

不要重写。

---

## 优化为真正的 Exam-Aware Plan

StudyFetch Study Plan 的关键是 syllabus + exams + topics + mastery。

### 新输入

```text
Exam Event
Covered Topics
Syllabus
Mastery
Due Review
Available Time
```

### 增加三种 Mode

```text
CRAM
STANDARD
COMPREHENSIVE
```

和 StudyFetch 类似的思想，但使用你自己的算法。

### CRAM

优先：

```text
high exam weight
low mastery
high misconception
```

### STANDARD

平衡：

```text
coverage
mastery
spacing
```

### COMPREHENSIVE

增加：

```text
prerequisites
transfer
long-term retention
```

### 动态 Re-plan Trigger

以下事件触发：

```text
新材料
新考试
考试时间变化
完成 Quiz
Mastery 显著变化
任务 missed
```

### TODO

- [ ] exam_events
- [ ] syllabus integration
- [ ] Topic grouping
- [ ] Cram
- [ ] Standard
- [ ] Comprehensive
- [ ] pre-assessment
- [ ] mastery checkpoint
- [ ] dynamic replanning
- [ ] missed task recovery
- [ ] plan version
- [ ] reason per task
- [ ] user lock task
- [ ] manual reorder

### 验收

将某知识点：

```text
mastery 0.8 → 0.3
```

并距离考试 2 天：

重新规划后其优先级必须显著提高。

---

# 十九、Syllabus + Exam Calendar：新增核心模块

这是目前最值得新增的产品模块之一。

StudyFetch 当前 Calendar 可以读取 syllabus，识别课程和考试，并根据考试范围和掌握情况安排 Study Session。

### 新模块

```text
syllabus_service.py
exam_event_service.py
calendar_service.py
```

### 数据

```text
ExamEvent
├ date
├ name
├ subject
├ topics
├ importance
└ target_score
```

### TODO

- [ ] syllabus upload
- [ ] syllabus parse
- [ ] proposed exam extraction
- [ ] 用户确认考试日期
- [ ] exam → topics
- [ ] Calendar UI
- [ ] study sessions
- [ ] conflict detection
- [ ] available time
- [ ] reschedule missed tasks

### 验收

上传包含：

```text
Final Exam: 2026-12-20
Chapter 1-6
```

的 syllabus：

系统必须提出候选 Exam，用户确认后进入 Study Plan。

---

# 二十、Memory / Learner Profile 模块

## 当前

已有：

```text
Hermes memory
write approval
semantic dedupe
snapshot
learner profile
```

这是好设计。

### 不应该做

不要把：

```text
Mastery
Exam Result
Due Review
```

复制进长期 Memory。

这些应该由数据库状态负责。

### Memory 负责

```text
偏好的讲解方式
学习习惯
常见困难
表达偏好
长期目标
```

### Learner State 负责

```text
mastery
accuracy
confidence
forgetting
exam goal
```

### TODO

- [ ] 明确 Memory / State 边界
- [ ] Preference Memory
- [ ] Study Behavior Summary
- [ ] Teaching Role preference
- [ ] Session snapshot
- [ ] 禁止把临时考试状态写长期 Memory
- [ ] Memory provenance

### 验收

删除一个 Study Plan：

不应删除稳定学习偏好。

删除 Memory：

不能导致 Mastery 消失。

---

# 二十一、Dayend / LangGraph 模块

## 当前

```text
supervisor
closure
planning
critic
emotion
safety
human confirmation
persistence
```

这一模块和核心“期末复习”存在一定产品割裂。

### 建议

不要继续横向增加 Agent。

将其定位为：

> **Session Closure / Daily Review Agent**

### 输入

```text
今天完成了什么
哪些知识点变化
哪里仍然薄弱
明天考试压力
```

### 输出

```text
Today Summary
Mastery Changes
Unresolved Problems
Tomorrow Recommendation
```

### TODO

- [ ] Dayend 与学习事件打通
- [ ] 移除与核心复习无关分支
- [ ] closure 读取 mastery delta
- [ ] planner 读取 tomorrow tasks
- [ ] critic 检查 plan feasibility
- [ ] human confirmation 只用于重大计划调整
- [ ] 输出写回 Study Plan

### 验收

今日完成 Quiz 后：

Dayend 必须能明确指出：

```text
Self-Attention mastery +12%
Position Encoding 仍薄弱
明日优先 Position Encoding
```

---

# 二十二、Worker / Async Task 模块

## 当前

Celery + Redis 已经正确。

### 下一阶段重点

从：

> 异步处理文件

扩展到：

> Event-driven Learning System

### Events

```text
material.indexed
exam.completed
mastery.changed
flashcard.reviewed
exam.updated
task.missed
```

### Actions

```text
recompute signals
replan
refresh recommendations
```

### TODO

- [ ] domain event schema
- [ ] idempotency
- [ ] retry
- [ ] dead-letter handling
- [ ] mastery update event
- [ ] plan recompute debounce
- [ ] duplicate event prevention

### 验收

同一事件重复消费 3 次：

最终数据库状态必须一致。

---

# 二十三、Workspace Cache 模块

## 当前

Redis TTL：

```text
dashboard
subjects
chat
mind-map
exams
plan
workspace
```

### 风险

引入动态 Learner State 后，缓存更容易 stale。

### TODO

- [ ] mastery changed → invalidate dashboard
- [ ] mastery changed → invalidate plan
- [ ] material indexed → invalidate mind-map
- [ ] exam completed → invalidate recommendation
- [ ] versioned cache
- [ ] stale UI 标识

### 验收

考试提交后立即刷新 Dashboard：

不得继续展示考试前 Mastery。

---

# 二十四、Observability / Quality Evaluation

## 当前

这一块是你和很多学生项目明显拉开差距的地方：

```text
Recall@K
MRR
Citation Precision
Isolation Rate
model logs
cost
operation metrics
trace
```

应该继续加强。

### 新增 Product Metrics

```text
Guided Session Completion
Quiz Remediation Rate
Mastery Gain
Recommendation Acceptance
Plan Completion
Due Review Completion
```

### 新增 AI Metrics

```text
Reranker uplift
Answer grounding
False reject rate
Mastery calibration
Plan relevance
```

### TODO

- [ ] recommendation impression log
- [ ] recommendation click
- [ ] study step complete
- [ ] before/after mastery
- [ ] plan replan count
- [ ] adaptive stop count
- [ ] confidence calibration
- [ ] version every algorithm

### 验收

任意推荐必须能回答：

```text
algorithm version?
input signals?
score?
why?
user followed it?
result?
```

---

# 二十五、安全 / Privacy 模块

现有：

```text
JWT
RLS
prompt injection scan
private storage
data export
delete
```

保持。

加入 Live Lecture / Syllabus 后需要新增：

### TODO

- [ ] audio retention policy
- [ ] transcript deletion
- [ ] syllabus privacy
- [ ] calendar privacy
- [ ] no cross-user recommendation data
- [ ] external knowledge provenance
- [ ] tool permission boundaries

### 验收

User A：

不能：

```text
读取
搜索
引用
推荐
```

任何 User B 数据。

---

# 二十六、前端整体信息架构

当前导航主要是：

```text
Dashboard
Study Room
Materials
Mind Map
Exams
Plan
```

### 推荐演进

```text
Home
Study Plan
Study
Materials
Practice
Progress
```

其中：

### Home

Next Best Action

### Study Plan

考试驱动路线

### Study

Guided Session + Tutor

### Materials

资料 / Notes / Lecture

### Practice

Quiz / Test / Flashcards

### Progress

Topic Mastery / Trends / Wrong Answers

---

# 二十七、统一 Turn Into 机制

这是很值得学习 StudyFetch 的产品设计，但不用照搬 UI。

所有学习对象统一暴露：

```text
Learn This Another Way
```

例如：

```text
Material
↓
Notes
Flashcards
Mind Map
Quiz

Mind Map Node
↓
Tutor
Flashcards
Quiz

Wrong Answer
↓
Tutor
Notes
Flashcards

Quiz Result
↓
Tutor
Flashcards
Study Plan
```

### TODO

- [ ] source abstraction
- [ ] conversion API
- [ ] provenance inheritance
- [ ] citation inheritance
- [ ] unified action component
- [ ] current context preservation

### 验收

从：

```text
一道错题
```

进入 Tutor 后：

Tutor 必须自动知道：

```text
哪道题
用户答案
正确答案
错误类型
知识点
证据
```

用户不需要重新描述。

---

# 二十八、实施优先级

## P0：先做，不做这些后面都会重复返工

### 1. Topic Domain Model

```text
Unit
Topic
Knowledge Point
```

### 2. Learner State

```text
Covered
Practicing
Mastered
At Risk
```

### 3. Exam Event + Syllabus

### 4. Response Confidence

---

## P1：形成真正闭环

### 5. Guided Study Session

### 6. Adaptive Quiz

### 7. Next Best Action

### 8. Study Plan v3

---

## P2：改善学习效果

### 9. Card-level Spaced Repetition

### 10. Reranker

### 11. Semantic / Parent-child Chunking

### 12. Recommendation Evaluation

---

## P3：产品体验

### 13. Notes

### 14. Unified Turn Into

### 15. Calendar

### 16. Live Lecture

---

## P4：后续再考虑

暂时不建议优先复制 StudyFetch：

```text
Arcade
Mini Apps
Share Camera
复杂游戏化
社交分享
Video Explainers
Audio Recap
```

这些能够增加产品丰富度，但对你当前“AI 应用工程 + 期末复习 Agent”的面试价值远低于 Learner State 和 Agent Loop。

---

# 二十九、完整核心闭环验收

最终必须完成一条真实 E2E Journey：

## Case

用户上传：

```text
Transformer.pdf
```

并设置：

```text
考试：
7 天后

范围：
Chapter 1-5

每日：
60 min
```

### System 应执行

```text
1. MinerU 解析
2. 建立 Chapters
3. 建立 Topics
4. 建索引
5. Pre-assessment
6. 初始化 Mastery
7. 生成 Study Plan
8. 推荐 Next Best Action
9. 开始 Guided Session
10. 阅读 Notes
11. Socratic Check
12. Flashcard
13. Adaptive Quiz
14. 用户填写 Confidence
15. 更新 Mastery
16. 检测 Misconception
17. 更新 next_review_at
18. 动态调整 Study Plan
19. Dashboard 推荐下一 Topic
20. Dayend 总结
```

这 20 步全部成功，才能认为：

> **“AI 期末复习 Agent 闭环完成。”**

---

# 三十、验收体系

不能只验收：

```text
页面能打开
API 200
```

必须分五层。

---

## Level 1：功能验收

检查：

```text
功能是否真的完成
```

例如：

- Quiz 能否保存 Confidence
- Study Session 能否 Resume
- Plan 能否 Replan

---

## Level 2：数据验收

检查：

```text
前后状态是否正确
```

例如：

```text
考试前 mastery = 0.42
考试后 mastery = 0.57
```

必须有 Mastery History。

---

## Level 3：算法验收

例如 Retrieval：

```text
Baseline
RRF

Candidate
RRF + Reranker
```

必须跑同一个 Dataset。

不能：

> “感觉效果更好。”

---

## Level 4：E2E 验收

必须从用户入口完成整个 Journey。

---

## Level 5：回归验收

新版本不能破坏：

```text
Auth
RLS
Material isolation
Citation
Task retry
Existing exams
Existing study plan
```

---

# 三十一、统一模块验收模板

每完成一个模块，都填写下面模板。

---

## Feature Acceptance Report

### 1. 基本信息

```text
模块名称：
版本：
负责人：
验收日期：
Algorithm Version：
Git Commit：
Environment：
```

### 2. 优化目标

```text
原问题：

期望结果：

对标能力：

本次不解决：
```

### 3. 代码范围

```text
Frontend：

Backend：

Database：

Worker：

Prompt：

Tests：
```

### 4. 数据库变化

```text
Migration：

新增表：

新增字段：

索引：

RLS：

Rollback：
```

### 5. Functional Cases

| ID | Case | Input | Expected | Actual | Pass |
|---|---|---|---|---|---|
| F01 | 正常流程 |  |  |  | ☐ |
| F02 | 空数据 |  |  |  | ☐ |
| F03 | 非法参数 |  |  |  | ☐ |
| F04 | 重试 |  |  |  | ☐ |
| F05 | 用户隔离 |  |  |  | ☐ |

### 6. AI Quality

```text
Dataset：

Baseline：

Candidate：
```

| Metric | Baseline | Candidate | Requirement |
|---|---:|---:|---:|
| Recall@K | | | |
| MRR | | | |
| Citation Precision | | | |
| Grounding | | | |
| Latency P50 | | | |
| Latency P95 | | | |
| Cost / Request | | | |

### 7. Learning Quality

适用于 Mastery / Plan / Quiz：

| Metric | Before | After |
|---|---:|---:|
| Accuracy | | |
| Mastery | | |
| Confidence Calibration | | |
| Recommendation Acceptance | | |
| Completion Rate | | |

### 8. Edge Cases

```text
☐ 无资料
☐ 资料不足
☐ 重复资料
☐ 长资料
☐ 多栏 PDF
☐ 表格
☐ 公式
☐ 跨用户
☐ 跨学科
☐ 外部模型失败
☐ Redis unavailable
☐ MinerU unavailable
☐ Worker retry
```

### 9. Regression

```text
pytest：

Frontend build：

E2E：

DB invariant：

Security：
```

### 10. Acceptance Decision

```text
[ ] PASS

[ ] PASS WITH KNOWN LIMITATIONS

[ ] FAIL
```

### Known Limitations

```text

```

### Follow-up

```text

```

---

# 三十二、整个项目最终验收 Dashboard

最终建议做一个总验收表：

| Dimension | Target |
|---|---|
| Topic Coverage | ≥95% 核心学习行为可映射 Topic |
| User Isolation | 100% |
| Citation Fabrication | 0 |
| Retrieval | 相对当前 baseline 明显提升 |
| Guided Session | 全链路可执行/暂停/恢复 |
| Mastery | 有完整 evidence history |
| Plan | Exam-aware + Mastery-aware |
| Flashcards | Card-level due scheduling |
| Quiz | Confidence + adaptive remediation |
| Recommendation | 每条可解释 |
| Re-plan | 状态变化自动触发 |
| Observability | 每次 AI 调用可追踪 |
| Cost | 可统计 |
| Privacy | 用户可完整导出/删除 |

---

# 三十三、最终项目定位

优化完成以后，不建议再把它介绍成：

> “一个用了 Multi-Agent 和 RAG 的期末复习系统。”

更准确的表达应该变成：

> **“这是一个面向大学生期末复习的状态驱动型 AI Learning Agent。系统首先将课程资料解析为可追溯的知识结构，然后通过练习、问答、Flashcard 和考试持续维护每个知识点的 Learner State；基于考试时间、掌握度、遗忘风险、错误认知和课程重要度计算 Next Best Action，再由 Guided Study Agent 执行学习任务，并根据结果动态更新后续复习计划。”**

对应技术主链：

```text
MinerU
↓
Structured Knowledge
↓
Hybrid RAG
↓
Topic Graph
↓
Learner State
↓
Need Score
↓
Next Best Action
↓
Guided Agent
↓
Assessment
↓
Mastery Update
↓
Dynamic Replanning
```

这时你和 StudyFetch 的关系就非常清楚：

> **StudyFetch 是成熟的通用 AI 学习平台；你的项目则把“期末复习的下一步学习决策”作为核心问题，并且整个 Retrieval、Evidence、Learner State 和 Recommendation Pipeline 都是可解释、可控制、可评测的。**

这会比继续增加几个 AI 功能，更能提升这个项目在 AI 应用开发 / AI 全栈面试中的技术含金量。