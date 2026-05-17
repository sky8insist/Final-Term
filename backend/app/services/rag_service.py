from pathlib import Path

from fastapi import HTTPException, status

from app.config.settings import settings
from app.services import memory_service
from app.services.llm_service import LLMServiceError, generate_text_async
from app.services.retrieval_service import search_subject_context

INSUFFICIENT_CONTEXT_ANSWER = "资料中未找到足够依据。请先上传并索引相关资料，或换一个更具体的问题。"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa_prompt.md"


def _load_qa_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "Answer the student's question using only the retrieved material context."


def _build_prompt(*, question: str, raw_context: str, citations: list[dict]) -> str:
    citation_lines = "\n".join(
        f"[{index + 1}] {citation['sourceName']}\n{citation['text']}"
        for index, citation in enumerate(citations)
    )
    return f"""
{_load_qa_prompt()}

回答语言：{settings.default_answer_language}

硬性规则：
- 只能依据“检索上下文”和“可引用片段”回答。
- 不要编造资料来源、文件名、页码或引用。
- 如果资料不足，请明确说“资料中未找到足够依据”。
- 回答应面向短期考试复习，优先解释重点、概念关系和易考点。

学生问题：
{question}

检索上下文：
{raw_context}

可引用片段：
{citation_lines}
""".strip()


async def answer_with_rag(*, user_id: str, subject_id: str, question: str) -> dict:
    context = search_subject_context(user_id=user_id, subject_id=subject_id, question=question)
    citations = memory_service.normalize_retrieval_citations(context["citations"])

    if not context["rawContext"].strip() or not citations:
        answer = INSUFFICIENT_CONTEXT_ANSWER
    else:
        prompt = _build_prompt(
            question=context["question"],
            raw_context=context["rawContext"],
            citations=citations,
        )
        try:
            answer = await generate_text_async(prompt, temperature=0)
        except LLMServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="LLM generation failed",
            ) from exc

    message = memory_service.record_qa_history(
        user_id=user_id,
        subject_id=subject_id,
        question=context["question"],
        answer=answer,
        citations=citations,
    )
    memory_service.increment_review_total(user_id=user_id, subject_id=subject_id)
    return {
        "answer": answer,
        "citations": citations,
        "messageId": message["id"],
    }
