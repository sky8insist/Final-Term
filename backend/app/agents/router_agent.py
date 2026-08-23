import re

from app.models.assistant import IntentDecision
from app.services.llm_service import LLMServiceError, generate_json_async

INTENTS = ["qa", "explain_concept", "summarize", "analyze_table", "explain_chart", "derive_formula",
           "compare", "generate_outline", "generate_mind_map", "generate_flashcards", "generate_practice",
           "generate_exam", "grade_answer", "analyze_practice_performance", "build_study_plan", "show_progress",
           "external_research"]


def _fallback(message: str) -> IntentDecision:
    rules = [
        (("试卷", "模拟考", "组卷"), "generate_exam"), (("思维导图", "脑图"), "generate_mind_map"),
        (("专项练习", "练几题", "出几题", "刷题"), "generate_practice"),
        (("闪卡", "卡片"), "generate_flashcards"), (("表格", "第几行", "第几列"), "analyze_table"),
        (("图表", "曲线图", "柱状图"), "explain_chart"), (("公式", "推导"), "derive_formula"),
        (("提纲", "大纲"), "generate_outline"), (("总结", "摘要"), "summarize"),
        (("练习表现", "薄弱点", "错题", "错因", "做错"), "analyze_practice_performance"), (("计划", "怎么复习", "怎么安排"), "build_study_plan"),
        (("进度", "掌握度", "掌握得", "学得怎么样"), "show_progress"), (("批改", "评分"), "grade_answer"),
        (("比较", "对比", "区别"), "compare"), (("联网", "网上查", "外部资料", "最新资料"), "external_research"),
        (("解释", "什么是", "没听懂", "讲讲"), "explain_concept"),
    ]
    matches = [intent for terms, intent in rules if any(term in message for term in terms)]
    if re.search(r"第.{0,4}(行|列)", message) and "analyze_table" not in matches:
        matches.insert(0, "analyze_table")
    if matches:
        return IntentDecision(primary_intent=matches[0], secondary_intents=list(dict.fromkeys(matches[1:])),
                              confidence=0.78, needs_retrieval=True,
                              needs_clarification=False, required_skills=list(dict.fromkeys(matches)))
    if message.strip() in {"帮我一下", "弄一下", "看看这个", "怎么搞", "来一个"}:
        return IntentDecision(primary_intent="qa", confidence=0.4, needs_retrieval=True,
                              needs_clarification=True,
                              clarification_question="你希望我针对哪部分资料完成什么复习任务？",
                              required_skills=[])
    return IntentDecision(primary_intent="qa", confidence=0.65, needs_retrieval=True,
                          needs_clarification=False, required_skills=["retrieval", "qa"])


async def route_intent(message: str) -> IntentDecision:
    prompt = f"""识别期末复习助手意图。允许意图：{', '.join(INTENTS)}。
返回 JSON：primaryIntent, secondaryIntents, confidence, needsRetrieval, needsClarification,
clarificationQuestion, requiredSkills。置信度低于0.55或缺少关键对象时 needsClarification=true。
materialScope 返回资料/章节/页码等显式范围；allowExternalKnowledge 只有用户明确要求联网时才为 true。
用户消息：{message}"""
    try:
        result = await generate_json_async(prompt)
        normalized = {
            "primary_intent": result.get("primaryIntent", "qa"),
            "secondary_intents": result.get("secondaryIntents", []),
            "confidence": result.get("confidence", 0.5),
            "needs_retrieval": result.get("needsRetrieval", True),
            "needs_clarification": result.get("needsClarification", False),
            "clarification_question": result.get("clarificationQuestion"),
            "required_skills": result.get("requiredSkills", []),
            "material_scope": result.get("materialScope", {}),
            "allow_external_knowledge": result.get("allowExternalKnowledge", False),
        }
        decision = IntentDecision(**normalized)
        if decision.confidence < 0.55:
            decision.needs_clarification = True
            decision.clarification_question = decision.clarification_question or "你希望我针对哪一部分资料完成什么复习任务？"
        return decision
    except (LLMServiceError, ValueError):
        return _fallback(message)
