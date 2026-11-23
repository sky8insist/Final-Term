# 解析结构与置信度验收

日期：2026-10-22。依据技术指南第七模块及上一阶段 HANDOFF.md 的下一步。

## 实现范围

新增统一结构标注步骤，在新摄取的 parsed blocks 写入 content_blocks 前执行。`metadata.documentStructure` 版本 document-structure-v1 包含标题路径、父标题来源引用、层级来源、caption 和公式上下文。标注中的来源使用 sourceHash/sequenceIndex/blockType/pageNumber；原文与引用身份保持为原解析块，不将推测关系写进原文。

标题只处理已有 heading 类型。层级来自明确字段、Word 样式或已识别标题的编号规则；无法判断时一级默认并计数。已有章节拆分和 Chunk 共用同一层级函数，避免前后端业务采用不同层级规则。

内嵌 MinerU caption 标记 provider_field。独立编号说明仅在紧邻、同页（或双方无页码）、目标唯一时双向关联；两个相邻目标同样可能匹配时明确标记 ambiguous，不选择一侧。跨页、无目标则不建立关联。公式只关联同页相邻非 caption 普通段落，方法标为 adjacent_candidate；规则邻接不等于语义正确性或事实蕴含。

Word 原生 fallback 按 XML 中段落/表格顺序输出，保留 Heading 样式。source_hash 仍按旧段落优先的身份规则计算，修复 sequence_index 而不新增一批仅因顺序变化产生的来源身份。其他结构标注步骤保留输入的 source_hash 和文本。

MinerU/原生抽取没有提供置信度时保存 null；有效数值保留，布尔/字符串/越界/非有限值视为未知。视觉缺失分数不再被伪造为 0；MinerU JSON 非有限常量转为 null，支持 JSONB 持久化。上游分数的统计不构成校准准确率。

结构 Chunk 改为 structure-v2：说明与对象可在父块目标大小边界上保持邻接，结构标注进入 child metadata；跨页公式不强制共用一个父块。不会在 child 原文中附加模型推测文本，引用仍是单个 canonical 内容块；超目标大小的父块继续受已有上下文展开预算限制。baseline 分块行为不改。

新增 document_structure 操作计数，覆盖块/标题/默认层级、内嵌/邻接/歧义/未匹配 caption、公式上下文与未知/上报/低分置信度。计数 metadata 不含原文、标题、文件名，使用既有 operation_metrics 的尽力记录机制。没有新表、新迁移、新模型或外部格式依赖。

## 验证

| 检查 | 结果 |
|---|---|
| 新增回归 | 38 项：37 项结构解析，1 项摄取/遥测集成 |
| 完整后端 pytest | 636 passed, 3 warnings（既有依赖弃用提示） |
| Ruff F / 离线 quality gate / diff | 通过 |
| 既有 8 条词法 Chunk 对照 | 未回退；baseline 完整证据 Hit@5 0.875，structure 1.0 |
| 真实本地 PostgreSQL | 元数据/父子结构/来源/RLS 验证通过，fixture 全回滚 |

回归覆盖置信度缺失/布尔/字符串/非有限/超大数/越界、有效零分保留、样式与编号层级、无效层级防护、标题父路径、纯函数不改输入及重复执行稳定性、图/表/chart caption 双向引用、歧义和跨页不猜测、公式排除标题/说明、内嵌 caption、父块边界和 child 标注、真实 MinerU Zip 字节及真实 DOCX 字节、旧 fallback hash 兼容、缺失视觉置信度，以及端到端摄取保存标注和仅计数遥测。

数据库脚本通过现有 replace_material_chunk_bundle 验证 caption 父块及 structure-v2，检查 material_chunks 标注、null 置信度、资料恢复 ready 后的 canonical 来源，以及 owner/foreign RLS。没有真实用户资料写入、模型调用或远端解析调用。

复跑：

```powershell
cd C:\Users\xingk\Desktop\Final-Term-main\backend
.\.venv\Scripts\python.exe scripts/verify_document_structure.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
.\.venv\Scripts\python.exe scripts/evaluate_chunk_strategies.py
```

数据库验收限制本地环境，依赖既有 040/042 等历史表及函数，不安装新迁移。本轮没有改前端页面，因此没有新增前端 UI 或浏览器验收；未重启 API/Worker、未改实际 `.env` 或用户技术指南。

## 保留范围

- 不支持跨栏/跨页版面匹配、没有编号的自由 caption、从正文自动识别标题、公式语义蕴含或自动转录分题。没有匹配对象的纯图片仍受原适配器可用文本条件限制，未新增图片资产提取。
- 指南要求随机抽取 30 页真实复杂课件分别检查阅读顺序/标题/表格/公式/page traceability，目前未执行。真实 MinerU/视觉/ASR 质量与置信度校准保持待验收。
- 仅新摄取或显式重解析使用新标注；没有重建历史内容、修改旧置信度/索引、自动刷新已确认 Topic 提案或迁移历史来源。native DOCX 的身份兼容不等于所有历史重解析清理问题均已解决。
- 计数日志不等于产品可视化报表；上游分数不等于正确率。结构关系当前用于元数据及父块保留，尚未扩展成跨块引用闭包或新的语义检索分支。
- 下一阶段按指南进入 Evidence / RAG QA：问题覆盖、claim/citation 核验和边界案例。其他解析/材料可靠性/音频运行链路与浏览器/持续 Worker E2E 待办保留。
