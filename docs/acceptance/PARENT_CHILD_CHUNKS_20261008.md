# Parent-child Chunk 验收（2026-10-08）

## 实现范围

- 原 `chunk_text / build_block_chunk_records` 的 800 字符 / overlap 120 行为保留。新的 `build_structure_chunk_bundle` 为结构与句子边界算法，版本 structure-v1；不是模型学习的语义分割。
- 标题切换父组，DOCX Heading N / 中文标题 N、MinerU text_level 保留层级路径。父组目标 4000 字符，标题/块边界优先；独立超长块与公式相邻解释组允许超过目标，避免强行截断原子证据。
- 普通文本先按句子/行切分并组合到 800 字符，完整短句承担至多 120 字符的尽力 overlap；超长无边界单句才使用原固定窗口。不会拆坏 3.14 等小数。
- 结构化 rows 表格按完整行打包并重复表头；不拆单元格。超过目标的行和没有可信 rows 的 HTML 表格保持原子并标记 oversized_atomic，不能声称所有 chunk 都满足硬长度上限。
- 公式本身保持原子 source child；生成时通过父组带上同组相邻解释，各块保留自己的来源位置，不把邻近解释伪标为公式所在页。
- 040：父组、父组成员、child parent_chunk_id、复合 owner/subject/material/成员外键及 owner SELECT RLS；原材料默认 baseline。父子 bundle 单事务替换，包括删除旧尾部 chunk，任何无效成员/child 写入错误均回滚到旧 bundle。替换后材料状态 parsing，完成 embedding/索引后才恢复 ready。
- 041：child 全文索引；baseline 资料仍检索原 block，structure 资料关键词检索当前 child。整块 structured JSON 不参与 child 匹配，避免一行的词使所有 table fragments 命中；关键词、向量与 Graph 对齐 chunk ID 进行融合，同时保留 source block ID。
- 新摄取 `CHUNK_STRATEGY=structure`，可配置 baseline；仅 child 参与 embedding / 图谱索引。此次没有全量重切、重建历史索引或调用付费模型。
- 父上下文 RPC 只返回本人同科目 ready 材料的 canonical blocks，缓存 parent content 不作为当前事实依据。客户端再逐块套用原类型/页码/时段/信心约束，按靠近 anchor 的顺序选完整块，默认附加总文本预算 6000 字符（含位置标记）。命中 child 不被截断；超长原子 child 本身可能超过此预算，补充内容则为空。
- adaptive 的历史 baseline 文件可退回具有真实 ID/页码的页内成员补充。显式 retrieval baseline 保留旧页内生成上下文作对照，但同样不覆盖 primary chunkText/坐标。没有父关系/无可用补充时保留命中片段，RPC 失败记录 warning。
- RAG 规范化引用时把每个补充 block 作为独立引用，保存到聊天历史，并纳入证据充分性判断；用户既有引用组件可显示各自页码。三张新/相关表纳入用户导出，科目/资料删除级联。

## 技术验证

- 全量 `python -m pytest tests -q -p no:cacheprovider`：**327 passed, 3 warnings**。包含 sentence/table/formula/heading 结构、decimal 与 oversized、来源保留/父成员过滤/预算、引用独立位置，以及同步上传 baseline/structure 两种策略。已有上传测试的 fake client 已同步新的 RPC 合同；嵌入失败和图谱失败降级回归通过。
- `python -m ruff check app tests scripts --select F`、`git diff --check` 通过。本轮未改前端，没有重复执行前端构建或声称浏览器验收。
- `scripts/verify_parent_child_chunks.py --apply --api`：040/041 已安装本地。真实 PostgreSQL 验证父子关系、写入中途失败后的旧 child ID/数量保持、多页 parent 原文/位置、child 关键词字段、跨用户/科目空结果、owner 只读 RLS/浏览器禁用 RPC、切回 baseline 清除旧父记录/尾部 child；临时记录全部回滚。
- 实际 Supabase 父上下文 RPC 读取/跨用户空结果，TestClient 关键词 baseline/adaptive API 200 / 跨用户 404。JWT 使用认证依赖覆盖；向量、图谱和外部模型显式禁用。因此不替代真实上传→解析→embedding→图谱→答案生成 E2E。

## 离线质量对照

`backend/evals/chunk_quality_cases.json` 包含 8 个带完整证据短语的回归用例：中/英文定义、公式解释、表格行、长定义边界、多标题、小数、HTML 表格。两种 chunker 使用同一个本地词法排序器和 Top 5。

| 指标 | baseline | structure |
|---|---:|---:|
| 完整证据 Hit@5 | 0.875 | 1.0 |
| 完整证据 MRR | 0.71875 | 0.84375 |

生成脚本：`scripts/evaluate_chunk_strategies.py --output ../docs/acceptance/CHUNK_COMPARISON_20261008.json`。指标定义为 Top 5 内是否存在同时包含该用例所有 requiredPhrases 的完整证据单位；边界用例有意测试定义被窗口拆开的情况。报告标记为 offline-chunk-regression，不能将上述数字称为生产 Recall@5、完整 RAG 质量提升或 P95。

## 后续验收与运行

- 指南要求的真实 Recall@5 不低于旧版、争取相对提升 10% 尚待验收：需要相同原始资料、人工 gold source block、分别建立 baseline/structure 两套索引，固定检索/reranker 参数后比较。在线评测脚本现按 source block ID 计分，保留 chunkId，避免策略切换产生新 child UUID 后标签失配。
- 长表格与超长单句仍需实际模型 token 限制/质量校准；父组大小为软目标，不透明表格暂不做 cell/row 结构推断。多页、音频连续段和 parser 内容提案的质量需真实资料验收。
- 新迁移不主动重建旧数据。其他环境先安装 040、041，再重启 API/Worker 加载新代码；配置在 `.env.example`，实际 `.env` 未修改。保持 baseline 的运行方式为 CHUNK_STRATEGY=baseline（后续摄取采用该策略）。
- 本模块完成首轮代码与技术验收；下一模块 Recommendation Evaluation，真实模型/浏览器/持续 Worker E2E 仍按进度表保留。
