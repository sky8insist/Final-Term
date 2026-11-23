# 检索管线 v2 验收（2026-10-08）

## 本轮交付

- 三路召回后 RRF 候选默认 20（配置 20–80），关键词每次最多 2K / 160；再进行可选 rerank 与最终 Top-K。保留定义和简洁关键词改写，返回实际 intent、queryRewrites、candidateCount、requested/actual reranker 与版本信息。
- 默认 adaptive 意图 Top-K 为定义 3、计算/证明 6、比较 8、通用 5；显式 topK 仍优先。`strategy=baseline` 使用相同候选上的 RRF、不调用 reranker/不加来源多样性，缺省 K=5。
- `Reranker` 接口支持 none、lexical 开发对照、HTTP 语义模型服务。lexical 为字词覆盖启发式，不是 Cross Encoder。HTTP 完整验证所有候选索引和 [0,1] 有限得分，只重排可信原片段；畸形/部分响应和 HTTP 错误回退 RRF 并记录原因。
- default none，不修改本地实际 .env，不新增外部收费调用。HTTP 采用独立 URL/key/model，超时默认 6 秒，关闭代理继承与重定向；接入已有预算预检、模型调用记录和配置成本。RERANKER_COST_PER_MILLION 默认 0，应按所选模型真实价格设置，未配置时成本统计不能视为完整。
- HTTP 数据合同依据 [SiliconFlow 官方 rerank 文档](https://docs.siliconflow.cn/docs/api/rerank-post)：query/documents、model、top_n、return_documents；响应使用 index/relevance_score。只发送核验后的候选，单篇最多 6000 字符。
- 所有来源统一筛选 material/type/page/time/confidence。LightRAG prose 不直接进入回答上下文：marker 先定位本人、同科目、ready 资料的 canonical chunk；无法核验时整路舍弃并记录 warning。rawContext 只包含最终选中证据。
- 039 与向量 SQL 检查资料自身归属，拒绝“本人内容块引用他人资料”这类历史松散外键关联。Graph 同时过滤 chunks 和 materials 的 owner/subject/status。
- 多资料采用每个来源约一半 K 的尽力约束；候选不足时回填，单来源不强制减少结果。页内上下文扩展仅在不违反 type/confidence/time 筛选时运行；结构化 parent-child 切分留待下一模块。

## 验证

- 后端 `python -m pytest tests -q -p no:cacheprovider`：**318 passed, 3 warnings**。覆盖四类意图、K 默认/显式与基线、词法次序、HTTP 原文本保留、索引重复/越界/布尔值/非有限得分/部分响应、失败回退、多样性不重复/不欠填、Graph DB owner 过滤/原文替换与未筛选上下文排除。
- `python -m ruff check app tests scripts --select F`、`git diff --check` 通过。
- `scripts/verify_retrieval_v2.py --apply --api` 已安装本地 039。真实 SQL owner/subject/material 限定、伪造 owned block 的外部资料关联排除、authenticated 跨用户 RLS 均通过；全部临时行回滚。
- 实际 Supabase + TestClient 关键词 baseline/adaptive API 200（定义缺省 K=5/3），跨用户科目 404。认证使用依赖覆盖，向量/Graph/模型路径显式禁用，不能替代完整在线检索验收。
- 此模块未修改前端；上一卡片模块的 lint/build 已通过，最大 chunk 250.65 kB。新增闪卡页面/组件与 Guided 的 impeccable 静态扫描无发现，真实浏览器仍 N/A。

## 对照实验入口与待办

使用真实人工标注 query / relevantIds / forbiddenIds 清单，启动加载新代码的后端，配置 HTTP reranker 后运行：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/evaluate_live_retrieval.py <manifest.json> --api-url http://localhost:8000 --subject-id <subject-uuid> --top-k 10 --compare --output <report.json>
```

令牌读取 `EXAMAI_EVAL_TOKEN`。脚本输出 Recall@5、MRR、Citation Precision、Citation Hit Rate、Isolation Rate、Latency P95，保存实际 pipeline/fallback 和逐条命中。baseline 与 adaptive 共用同一清单；当前顺序先 baseline 后 adaptive，正式 P95 需冷/热启动分组、轮换顺序和多次重复，避免缓存/网络偏差。未标注 forbiddenIds 的清单不能证明实际隔离率。

尚未执行真实 HTTP reranker 调用、代表性检索指标对照及 P95 实验，因此没有宣称质量提升。默认 none 时 adaptive 对照只验证动态 K / 来源多样性，不能称为 RRF+Cross Encoder 对照。真实 API 隔离、各模态 Recall、Graph/Vector 全链路、结构 parent-child 与语义模型校准仍待后续验收。
