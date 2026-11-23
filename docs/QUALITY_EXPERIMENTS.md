# 离线质量版本对照

`backend/scripts/compare_quality_runs.py` 对外部标签和预先采集的两个版本输出进行离线评分，不访问数据库、不调用模型、不发送数据。生产检索、计划和评分逻辑不因评估而修改。主实现及完整输入约束见 `backend/app/services/paired_quality_service.py`。

## 输入与版本绑定

需要三个分开的 JSON 文件：manifest、baseline、candidate。每个文件最多 10 MB，样本最多 2,000。额外字段、重复 JSON 键、非有限数字、重复 case ID、重复排名 ID、缺少任意样本或多出样本都拒绝；不能静默剔除失败样本后再报好结果。采集失败需要先修复或明确建立新的预注册样本集，不能把失败输出冒充合法答案。

manifest 包含 schemaVersion=1、datasetId、datasetVersion、datasetKind、labelProvenance 和 cases。datasetKind 只能是 synthetic-regression 或 human-labelled。后者是提交者对来源的声明，工具不认证标注者身份，也不保证标签独立、盲评或正确。

每个 case 都有 id、kind、inputSha256，标签依 kind 定义：

| kind | 标签字段 |
| --- | --- |
| retrieval | relevance 为来源 ID→0–3 整数，至少一个正标签；forbiddenIds 默认空。禁止来源不能有正相关标签 |
| grounding | evidenceSufficient、answerGrounded 分别为严格布尔或 null，至少一个有标签；null 不当负例 |
| plan | relevance 为 Topic→0–3；allowedTopicIds；capacityMinutes 为 ISO 日期→剩余分钟。正相关 Topic 必须允许 |

inputSha256 是**实际送入算法的输入快照**的规范 JSON SHA256。两个版本须使用同一问题、候选池、资料/固定回答，或同一 Topic/学习状态/考试范围/剩余容量；变了输入就须新建 case。算法运行时不应把相关度标签或期望 verdict 作为输入。哈希可以检查声明是否一致，不能证明调用方真的运行了相应输入。

baseline/candidate 包含 schemaVersion=1、runId、version、manifestSha256、outputs。两边 runId 和 version 必须不同。version 应描述真实模型/提示词/算法/配置版本，不能把人工负对照命名为旧生产版本。每个输出含相同 id/kind/inputSha256：

- retrieval：rankedIds，允许空排名，重复 ID 拒绝。
- grounding：严格布尔 evidenceAccepted、answerAccepted；未标注的维度不评分。样本必须是固定资料和固定待审回答；若两个版本生成了不同回答，需要分别取得输出级标签，不能共用本契约中的 answerGrounded 标签。
- plan：tasks，含 topicId、ISO day、1–1440 整数 minutes，taskType 默认 unspecified。禁止 Topic 或超预算是可评分的错误，不能通过过滤错误输出消除。

manifestSha256 使用 Pydantic 规范化后的标签对象，包含默认值；不是文件字节哈希。生成快照和哈希的 Python 示例：

```python
from app.services.paired_quality_service import Manifest, digest

labels = Manifest.model_validate(raw_labels).model_dump(mode="json")
manifest_hash = digest(labels)
stimulus_hash = digest(actual_input_snapshot)
```

digest 使用排序键、紧凑分隔符、UTF-8、不转义中文、拒绝 NaN 的 JSON。报告同时保存规范 manifest 和两个输出的 SHA256、来源声明、版本和评估配置。变更标签必须重新生成版本绑定，不能沿用旧输出的 manifestSha256。

## 指标和不确定性

| 指标 | 口径 |
| --- | --- |
| retrieval.ndcg | top-k，增益 2^grade−1，折扣 log2(rank+1)，按标签的理想排序归一化 |
| retrieval.mrr / recall | top-k 首个正标签倒数排名 / 所有正标签中命中比例 |
| retrieval.isolation | 完整输出中不含任何 forbiddenId 为 1；即使在 top-k 之外也检查 |
| grounding.falseReject / falseAccept | 足够证据被拒 / 不足证据被接受；各自仅以有对应标签的样本为分母 |
| grounding.supportedAnswerAccept / unsupportedAnswerAccept | 固定待审回答中，已标支持/不支持的回答被守卫接受的比例 |
| grounding.decisionAccuracy | 每 case 的已标维度 verdict 正确率，再对 case 宏平均 |
| plan.taskRelevance | 每任务外部 grade/3 后在计划内均值，再对 case 宏平均；不拿生产 priorityScore 当标签 |
| plan.topicCoverage | 覆盖的正相关 Topic 数 / 全部正相关 Topic 数，空计划为 0 |
| plan.forbiddenTaskRate | 不在 allowedTopicIds 的任务比例 |
| plan.capacityViolationRate | 输出涉及的日期中，累计分钟超出外部剩余容量的日期比例；未列日期容量视为 0 |
| plan.duplicateTaskRate | 相同 Topic/日期/taskType 的重复任务比例；重复安排不同方法不会自动算同一任务 |

空计划的任务精度、约束比例为 null，不把“未安排任何任务”解释成通过安全门禁。不同样本的指标是宏平均，不是全部任务加权平均；不能拿一个大计划压过其他样本。

每个指标都有 baselineAvailable/candidateAvailable、各自全体可用均值，以及两边都有效的 pairedCaseCount/baseline/candidate/delta。delta 为 candidate−baseline；improvement 对越低越好的指标反转符号。完整空值和可用数可检查计划为空造成的选择效应。

默认用固定种子 20261027、2,000 次配对 case 重采样，输出 raw delta 的 95% percentile bootstrap 区间。少于两个有效配对区间为 null；相同差值或极少样本可能产生零宽区间，不证明效果确定。方法假设 case 独立；同一资料/学习者的多题存在相关性时，应先按组采集并补分组重采样。当前没有多重比较校正或跨组聚类置信区间。

## 运行与门禁

在 backend 目录：

```powershell
.\.venv\Scripts\python.exe scripts/compare_quality_runs.py manifest.json baseline.json candidate.json --output comparison.json
```

默认 top-k=5、bootstrap-samples=2000；可选 `--top-k 1..100`、`--bootstrap-samples 100..10000`、`--seed 0..4294967295`。评估不会发起在线调用；外部模型采集、真实标签管理、匿名化和版本真实性由调用方负责。

`--gate gate.json` 可明确指定：

```json
{
  "minimumCaseCount": 2,
  "candidateMinimums": {"retrieval.isolation": 1.0},
  "candidateMaximums": {"grounding.falseReject": 0.1},
  "minimumImprovements": {"retrieval.ndcg": 0.0},
  "minimumImprovementCI95LowerBounds": {"retrieval.ndcg": 0.0}
}
```

绝对门禁使用所有 candidate 可用样本，不因 baseline 为空而漏掉 candidate 的错误；差值和区间门禁用配对样本。最低样本数默认 2，是输入保护下限，不是充分统计功效。区间门禁在越低越好时用 raw delta 上界反号计算改善下界。未知指标、空门禁、冲突阈值或非有限数拒绝，缺样本/空值不会自动通过。

- 退出 0：比较成功。没传 gate 时为 not_requested，不能解释为门禁通过；有 gate 且全部满足才为 passed。
- 退出 1：门禁 failed，完整结果仍保存，供复核失败样本。
- 退出 2：标签/输出/配置无效，不写新报告，既有报告保留。标准错误不回显私有样本内容。

报告输出不能覆盖任何输入或 gate 文件。门禁配置和 SHA256 一并存档；门禁通过仅说明所设条件满足，不触发生产发布，也不证明线上因果改善。报告不包含输入正文，但 ID 和来源声明仍可能含调用方提供的信息，真实数据应使用匿名 ID。

## 可复跑的合成验收

```powershell
.\.venv\Scripts\python.exe scripts/run_quality_experiment_fixture.py --output-dir ../docs/acceptance/paired_quality_20261027
.\.venv\Scripts\python.exe scripts/compare_quality_runs.py ../docs/acceptance/paired_quality_20261027/manifest.json ../docs/acceptance/paired_quality_20261027/baseline.json ../docs/acceptance/paired_quality_20261027/candidate.json --gate evals/paired_quality_gate.json --output ../docs/acceptance/paired_quality_20261027/comparison.json
```

共 24 条：3 重排、18 守卫、3 计划。实际执行当前 LexicalReranker、evidence-v2/claim-citation-v1、prioritize/build_schedule；对照分别为输入 RRF 顺序、仅检查非空引用的弱负对照、未过滤的计划负对照，均明确命名，不冒充历史生产版本。生产函数只接收输入快照，独立评分器消费分开的标签和输出，但**标签本身仍是仓库作者合成/规则回归，不是独立人工盲标**。

词法歧义反例会退步；总体 nDCG 差值区间跨 0。更强 `uplift_gate.json` 会失败，结果应保留。既有 quality gate 加入这组 synthetic contract 检查，不将其当真实语义 reranker、真实模型生成或真实用户计划效果。后续需固定真实候选池/输出、独立标注与分组采样后，再使用相同对照流程。
