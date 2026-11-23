# 离线质量对照与门禁验收

日期：2026-10-27。接上轮稳定 cohort/Mastery 校准，继续指南第 24 项的版本对照工具。本轮未改线上算法、API、数据库或前端，不调用外部模型。

## 交付

- `backend/app/services/paired_quality_service.py`：严格版本化 manifest/arm 模型、分离标签评分、配对聚合/区间、显式门禁。
- `backend/scripts/compare_quality_runs.py`：外部已采集输出的离线比较，退出码/覆盖保护/私有数据不回显。
- `backend/app/services/quality_experiment_fixture.py`、`backend/evals/paired_quality_cases.json`、`scripts/run_quality_experiment_fixture.py`：调用真实当前纯函数，生成 24 条合成对照 artifact。
- `backend/evals/paired_quality_gate.json`：合成规则回归阈值，已接入原 `run_quality_eval.py`；它不是生产效果/发布门禁。
- 使用契约、指标公式、空值和样本分母、外部标签导入、CLI 命令见 [QUALITY_EXPERIMENTS.md](../QUALITY_EXPERIMENTS.md)。

## 关键保护

标签和两版输出按全部 case ID/kind、逐 case inputSha256、规范 manifestSha256 绑定。缺样本、多样本、重复样本/排名、错输入/标签版本、相同 run/version、非严格布尔/整数、范围外相关度/时长、非法日期、重复 JSON 键和 NaN/Infinity 拒绝；文件限 10 MB，样本限 2,000。

每指标同时报告共享有效配对与各自所有可用样本。空计划/未标维度保留 null；绝对门禁用全部 candidate 可用样本，不能因 baseline 为空漏掉 candidate 的越界。差值/改善区间门禁使用配对样本，越低越好时反转符号。禁止来源检查覆盖全部排名，即使落在 top-k 外。

Bootstrap 默认 2,000 次、固定种子 20261027，以 case 配对重采样，95% percentile 区间；少于两对为 null。关联 case、重复文档/学习者、多重比较、小样本及退化零宽区间仍需谨慎，不是生产效果证明。

CLI 未设置 gate 记 not_requested，不自动宣称 passed。退出0表示比较有效；显式门禁失败退出1仍写报告；无效输入退出2不写新报告，既有报告保留。未知门禁指标/空阈值/冲突上下限拒绝，缺样本不通过；默认最低2样本只是保护下限。报告含配置及标签/双方输出/门禁规范哈希，不自动发布或变更应用。

## 实际运行结果

Artifact 目录：[paired_quality_20261027](paired_quality_20261027/report.json)，含 manifest.json、baseline.json、candidate.json、report.json、comparison.json、uplift_gate.json、uplift_check.json。

数据均为 **synthetic-regression / regression-only**。3 条重排使用输入 RRF 顺序 vs 当前 LexicalReranker；18 条守卫复用已有 grounding 规则标签，弱对照只检查非空引用；3 条计划使用未过滤 signals 的负对照 vs 当前 prioritize/build_schedule。输入实际相同，生产函数不接收相关度/期望 verdict 标签，但标签来源仍是仓库作者合成/规则回归，未进行独立人工盲标。

| 指标 | 对照→当前 | 限制 |
| --- | --- | --- |
| 重排 nDCG | .7584→.8770；Δ+.1186，95%区间[-.3691,+.3691] | 仅3条，含词法歧义退步，区间跨0 |
| 重排 MRR | .6667→.8333 | 不是 semantic reranker 或全检索管线对照 |
| 足够证据误拒率 | 0→0 | 仅2条正例，不说明真实拒答质量 |
| 不足证据误接收率 | 5/6→0/6 | 对照为人为弱规则 |
| 不支持的固定回答接受率 | 8/8→0/8 | 评估守卫，不是新生成回答的语义蕴含率 |
| 计划任务相关性 | 0→1 | 各2条非空计划；标签为外部合成 grade/3，空计划不伪造精度 |
| 计划 Topic 覆盖 | 0→2/3 | 含零容量样例，没有强行填满 |

普通合成回归门禁 `comparison.json` 为 **passed，CLI退出0**。额外要求 nDCG 改善区间下界≥0 的 `uplift_check.json` 为 **failed，CLI退出1**，失败指标已存档。这是预期的不通过：不能据此发布“重排提升成立”，也未删除退步例。

## 回归验证

- 新增 **37 项**后端测试：独立手算 nDCG/MRR/配对区间、种子可复跑、单样本无区间、严格标签、标签/输入/样本错配、top-k外禁用来源、空/非配对计划、超容量/重复任务、未知标签、CI符号、门禁无效/无样本、CLI退出码/覆盖保护/错误 JSON。
- 完整后端 **865 passed, 3 warnings**；Ruff F、原质量门禁加新24条合成契约、diff 检查通过。首次 pytest 临时目录被沙箱 WinError5 拒绝，按测试权限重跑37项和完整测试通过。
- 无新迁移/依赖/前端代码；没有重跑或声称新增 UI/浏览器/真实JWT/线上检索/模型/P95验收。未改实际 .env、用户指南或真实学习数据，未重启服务。

## 复跑

backend 下先运行 `scripts/run_quality_experiment_fixture.py --output-dir ../docs/acceptance/paired_quality_20261027`（使用同一 `.\.venv\Scripts\python.exe`），再执行：

```powershell
.\.venv\Scripts\python.exe scripts/compare_quality_runs.py ../docs/acceptance/paired_quality_20261027/manifest.json ../docs/acceptance/paired_quality_20261027/baseline.json ../docs/acceptance/paired_quality_20261027/candidate.json --gate evals/paired_quality_gate.json --output ../docs/acceptance/paired_quality_20261027/comparison.json
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

同一比较命令改用 artifact 目录的 uplift_gate.json，并把输出改为 uplift_check.json，将按预期退出1。无在线 token、数据库连接或模型配置要求。

## 后续

工具可导入外部真实标签/已采集结果，但 human-labelled 只是来源声明，不认证标注者或独立性。真实 semantic reranker/生成/计划采集、独立标签、答案级语义评估、同人/文档分组采样和生产效果尚待开展。可先继续本阶段可执行的指标界面、审计历史分页及预测覆盖率，再做长期样本、保留策略/P95；不将工具与合成门禁完成解释为整个指南第24项已完成。
