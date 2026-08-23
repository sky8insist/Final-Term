from __future__ import annotations

import json
import re

from app.models.assistant import DialogueDecision
from app.services.llm_service import LLMServiceError, generate_json_async


HINT_PATTERNS = ("不知道", "不会", "没思路", "给点提示", "提示一下", "下一步是什么", "怎么想")
SOLUTION_PATTERNS = ("直接告诉我", "完整答案", "查看解析", "公布答案", "讲完整", "答案是什么")
NEW_TOPIC_PATTERNS = ("换个问题", "另一个问题", "另外问", "顺便问", "不说这个", "新问题", "换一题")
CHALLENGE_PATTERNS = ("你说错", "不对吧", "有矛盾", "我不同意", "为什么你说", "资料不是")
ANSWER_PREFIXES = ("因为", "所以", "我认为", "我觉得", "答案是", "应该是", "这是因为", "由此")
FOLLOWUP_PREFIXES = ("那为什么", "为什么", "这里的", "这一步", "怎么推出", "什么意思", "如何得到")


def _decision(act: str, confidence: float, *, interaction: dict | None = None,
              retrieve: bool = False, query_source: str = "none", reason: str) -> DialogueDecision:
    return DialogueDecision(
        dialogue_act=act, confidence=confidence,
        target_interaction_id=str(interaction["id"]) if interaction and interaction.get("id") else None,
        related_knowledge_point=interaction.get("knowledge_key") if interaction else None,
        should_retrieve=retrieve, retrieval_query_source=query_source, reason_code=reason,
    )


def classify_by_rules(message: str, context: dict) -> DialogueDecision | None:
    text = message.strip()
    active = context.get("activeInteraction")
    if any(term in text for term in NEW_TOPIC_PATTERNS):
        return _decision("new_question", 0.98, interaction=active, retrieve=True,
                         query_source="current_message", reason="explicit_topic_switch")
    if any(term in text for term in HINT_PATTERNS):
        return _decision("request_hint", 0.97, interaction=active, reason="explicit_hint_request")
    if any(term in text for term in SOLUTION_PATTERNS):
        return _decision("request_full_solution", 0.97, interaction=active, reason="explicit_solution_request")
    if any(term in text for term in CHALLENGE_PATTERNS):
        return _decision("challenge_or_correction", 0.92, interaction=active, retrieve=bool(active),
                         query_source="original_question" if active else "current_message",
                         reason="explicit_challenge")
    if not context.get("hasPendingQuestion"):
        return _decision("new_question", 0.90, retrieve=True, query_source="current_message",
                         reason="no_pending_interaction")
    if re.fullmatch(r"[A-Fa-f]|对|错|正确|错误|是|不是", text):
        return _decision("answer_to_pending_question", 0.99, interaction=active,
                         reason="short_expected_answer")
    if text.startswith(ANSWER_PREFIXES) or ("？" not in text and "?" not in text and len(text) <= 180):
        return _decision("answer_to_pending_question", 0.90, interaction=active,
                         reason="declarative_response_to_pending_question")
    if text.startswith(FOLLOWUP_PREFIXES) and len(text) <= 120:
        return _decision("followup_question_same_topic", 0.84, interaction=active, retrieve=True,
                         query_source="resolved_question", reason="contextual_followup_pattern")
    return None


async def classify_dialogue_act(
    *, message: str, context: dict, mode: str, override: str | None = None,
) -> DialogueDecision:
    active = context.get("activeInteraction")
    if override:
        retrieve = override in {"followup_question_same_topic", "new_question", "challenge_or_correction"}
        return _decision(
            override, 1.0, interaction=active, retrieve=retrieve,
            query_source="resolved_question" if override == "followup_question_same_topic" else (
                "current_message" if override == "new_question" else "original_question"
            ), reason="user_override",
        )
    ruled = classify_by_rules(message, context)
    if ruled:
        return ruled
    compact_turns = [
        {"role": item.get("role"), "content": str(item.get("content", ""))[:500]}
        for item in context.get("recentTurns", [])[-6:]
    ]
    prompt = f"""判断学生当前消息与上一轮教学问题的关系，只返回JSON。
允许 dialogueAct：answer_to_pending_question, followup_question_same_topic, new_question,
request_hint, request_full_solution, confirmation, challenge_or_correction, clarification,
meta_command, ambiguous。
区分原则：回答上一问是作答；围绕同一概念提出疑问是同主题追问；明显改变知识点是新问题。
不要回答知识问题，不要调用检索。
返回字段：dialogueAct, confidence, relatedKnowledgePoint, resolvedQuestion, shouldRetrieve,
retrievalQuerySource, reasonCode。
模式：{mode}
待回答交互：{json.dumps(active or {}, ensure_ascii=False)[:4000]}
最近对话：{json.dumps(compact_turns, ensure_ascii=False)}
当前消息：{message}"""
    try:
        result = await generate_json_async(prompt)
        decision = DialogueDecision(
            dialogue_act=result.get("dialogueAct", "ambiguous"),
            confidence=float(result.get("confidence", 0.5)),
            target_interaction_id=str(active["id"]) if active and active.get("id") else None,
            related_knowledge_point=result.get("relatedKnowledgePoint") or (active or {}).get("knowledge_key"),
            resolved_question=result.get("resolvedQuestion"),
            should_retrieve=bool(result.get("shouldRetrieve", False)),
            retrieval_query_source=result.get("retrievalQuerySource", "current_message"),
            reason_code=str(result.get("reasonCode", "semantic_classifier")),
        )
        if decision.confidence < 0.60:
            decision.dialogue_act = "ambiguous"
            decision.should_retrieve = False
            decision.retrieval_query_source = "none"
        return decision
    except (LLMServiceError, ValueError, TypeError):
        return _decision("ambiguous", 0.40, interaction=active, reason="classifier_unavailable")


def build_contextual_query(message: str, decision: DialogueDecision, context: dict) -> str:
    if decision.resolved_question:
        return decision.resolved_question
    active = context.get("activeInteraction") or {}
    parts = [
        f"知识点：{active.get('knowledge_key')}" if active.get("knowledge_key") else "",
        f"上一问题：{active.get('question_text')}" if active.get("question_text") else "",
        f"当前追问：{message}",
    ]
    return "\n".join(part for part in parts if part)

