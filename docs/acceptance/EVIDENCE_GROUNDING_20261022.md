# Evidence / RAG QA 首轮验收

日期：2026-10-22。依据技术指南第十模块和交接文档上一阶段入口。

## 交付

evidence-v2 在原文和引用存在之外，检查问题词法相关性及分项覆盖，记录引用数量和不同资料来源数。`coverage` 改为问题分项覆盖率；独立检索 score 不视为可比较的语义概率。外部引用不参与课程充分性，明确缺失的子问题、空证据不能被其他资料文字数量掩盖。

可选 `ENABLE_EVIDENCE_JUDGE=false` 默认关闭。启用后仅 borderline 调用现有模型预算通道，20 秒超时，要求引用 ID 和逐字原文 quote；不在 canonical 引用中的 ID/quote 不能把证据升级为充分。显然不足的证据不调用 judge。有效 quote 只是模型判断的可追溯依据，不等于客观蕴含证明。

生成契约新增事实句 `[n]` 编号。回答生成后逐句核验：

- 编号须在实际检索片段范围内；显式未知引用格式、超长编号或新 URL 硬失败。
- 事实句必须有引用；关联引用至少提供词法支持，不能附带完全无关的引用。
- 明显数值不在引用中或否定方向不一致时拒绝发布。
- 事实标题仍须核验，不能通过 Markdown 标题绕过；非事实追问可无编号，但不计为 grounded 事实。

失败结果替换为既有不足依据答复，输出和历史 citations 清空，不返回/保存被拒绝的原回答。generation.grounded 需要核验通过且有事实句。规则版本、逐句支持标志、citationCoverage、groundingScore、有效引用 ID 和失败原因写入 assistant_metadata；报告不保存被拒绝的回答全文。

外部 fallback 仅向生成阶段提供外部引用及外部上下文，不混入不足的课程 rawContext 或冻结记忆。服务端添加课程不足说明和“外部补充知识”章节。外部输出未通过核验时不置 externalUsed；课程证据足够时不搜索外部。

## 验证证据

| 检查 | 结果 |
|---|---|
| 新增 `test_grounding.py` | 46 项回归 |
| 完整后端 pytest | 682 passed, 3 warnings（既有依赖弃用提示） |
| Ruff F / quality gate / diff | 通过 |
| 18 条离线标签 | 8 条证据、10 条回答，全部符合预期 |
| 不足拒答 / 充分接受 / 不支持回答拦截 | 标签样本下均为 1.0，不能外推线上指标 |
| 本地 PostgreSQL 审计存储/RLS | 通过，fixture 全回滚 |

测试覆盖有答案/部分答案/无答案/诱导编造/跨学科干扰、语法词伪支持、无意义或符号问题、不可靠检索分数、source diversity 去重、课程/外部证据边界、事实标题与逐句引用、引用范围/格式/超长编号/链接、数值/否定修改、judge 默认关闭/异常/错误 quote/可核对 quote、拒绝回答不进入历史、分项缺失不调用生成模型，以及外部 fallback 的服务端章节和空课程提示上下文。

原 RAG 和外部搜索测试夹具改为带有效编号的生成文本；原来的主资料优先、记录历史、无引用不调用模型、外部 fallback 等断言保留。没有通过跳过新核验来维持旧无引用输出。

`verify_grounding.py --db` 使用真实 PostgreSQL 存储拒答、空 citations 和 claim-citation 报告，并验证本人可读/跨用户不可读；临时行全部回滚。此验证证明 JSON 审计兼容及聊天 RLS，不代替真实检索来源归属或真实模型回答质量。来源归属继续依赖既有 scoped retrieval；没有新增数据库授权路径。

复跑：

```powershell
cd C:\Users\xingk\Desktop\Final-Term-main\backend
.\.venv\Scripts\python.exe scripts/verify_grounding.py --db --output ../docs/acceptance/GROUNDING_EVAL_20261022.json
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

无新增表/迁移。审计使用既有聊天 metadata（026）；旧库未安装该历史迁移时仍有原先的兼容降级，不能宣称审计持久化完整。`.env.example` 增加默认关闭的 judge 开关，实际 `.env` 不变；部署需加载新 API 代码和提示。本轮未改前端、未重启既有服务、未真实调用模型/NLI/外部搜索、未执行浏览器/JWT E2E。

## 限制与后续

这是确定性引用规则和可选边界证据模型判断的第一轮。词法支持、原文 quote、数字子集及否定模式都不构成完整语义蕴含；复杂同义转述、跨语言、数学推导可能过度拒答，共享关键词也可能误判支持。groundingScore 表示被规则支持的句子比例，不是事实正确概率。并未验证所有文件名/页码主张或所有可能的伪引用写法。

质量门禁是人工定义的小型离线回归集，不是独立真实用户测试集；不宣称线上伪引用为零或实际无资料拒答率 100%。真实模型/NLI 校准、复杂问题覆盖、完整语义 claim verifier、过度拒答率与真实检索/生成对照继续待办。核验失败与证据不足当前共用提示，审计报告保留不同原因。

下一阶段建议补齐 Mind Map 的稳定 Topic 权威、状态联动与工具入口；本模块真实质量和持续服务验收保留，不覆盖旧的独立评审 N/A 结论。
