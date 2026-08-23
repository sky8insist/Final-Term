import json


SYSTEM_PROMPT = """你是一名大学课程教师和知识结构设计专家。
你的任务不是总结资料目录，而是围绕学生当前的 Focus Question，基于课程证据建立适合复习的知识结构图。
所有结论必须由给定证据支持，不允许使用证据之外的知识。严格输出 JSON，不要输出 Markdown。"""


def build_focus_question(*, mode: str, query: str | None, topic_id: str | None,
                         chapter_id: str | None) -> tuple[str, str]:
    value = (query or "").strip()
    if mode == "question":
        if not value:
            raise ValueError("请输入你想理解的问题")
        return value, value
    if mode == "topic":
        topic = value or (topic_id or "").strip()
        if not topic:
            raise ValueError("请输入或选择一个知识点")
        return topic, f"{topic}是什么？它包含哪些核心概念、类型、形成方式及相互关系？"
    chapter = value or (chapter_id or "").strip() or "当前章节"
    return chapter, f"{chapter}有哪些核心知识？这些知识之间存在什么逻辑关系？"


def expand_query(*, mode: str, subject: str, focus_question: str) -> str:
    suffix = {
        "question": "核心区别 定义 原因 结果 条件 应用 例子",
        "topic": "定义 特征 分类 层级 过程 关系 应用 易错点",
        "chapter": "核心概念 主题结构 层级 关系 考点 易错点",
    }[mode]
    return f"{subject}；{focus_question}；{suffix}"


def build_generation_prompt(*, mode: str, focus_question: str, max_depth: int,
                            max_nodes: int, citations: list[dict], feedback: str = "") -> str:
    compact_evidence = [
        {
            "id": item.get("id"),
            "source": item.get("filename"),
            "page": item.get("pageNumber"),
            "text": str(item.get("chunkText") or "")[:2800],
        }
        for item in citations
    ]
    repair = f"\n上一次结果需要修复：{feedback}\n请完整重写 JSON。" if feedback else ""
    return f"""MIND_MAP_WORKFLOW_V2
Focus Question: {focus_question}
生成模式: {mode}

请先在内部完成概念抽取、关系识别和层级规划，再一次性返回知识地图 JSON。
要求：
1. 所有节点都必须直接或间接帮助回答 Focus Question，禁止把资料标题、章节名或作者名简单平铺。
2. 同一级节点必须具有相同抽象层级；一级节点最多 5 个，每个父节点最多 6 个子节点。
3. 默认深度不超过 {max_depth}，总节点不超过 {max_nodes}；节点标签使用 2-20 字短语。
4. 必须恰好有一个 root；非根节点必须有 parentId 和至少一个有效 sourceIds。
5. 识别包含、属于、导致、影响、决定、指导、实现、依赖、对比、构成、作用于、演化为等关系。
6. 不得编造证据。资料不足时设置 evidenceInsufficient=true，并只保留有依据的节点。
7. mastery 必须为 null，掌握度由系统历史数据补充，不能由模型猜测。

严格返回：
{{
  "title": "短标题",
  "focusQuestion": "{focus_question}",
  "summary": "直接回答核心问题的简短总结",
  "mode": "{mode}",
  "evidenceInsufficient": false,
  "nodes": [{{
    "id": "root", "parentId": null, "label": "核心主题", "type": "root",
    "level": 0, "importance": 1, "examImportance": "high", "mastery": null,
    "description": "简洁解释", "sourceIds": [], "order": 0
  }}],
  "edges": [{{"source": "root", "target": "node_id", "relation": "包含"}}]
}}

可用证据：
{json.dumps(compact_evidence, ensure_ascii=False)}{repair}"""

