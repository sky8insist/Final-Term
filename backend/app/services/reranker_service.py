"""Rerank trusted candidates only; providers cannot replace source text or IDs."""
import math
import re
from typing import Protocol
from time import perf_counter

import httpx

from app.config.settings import settings
from app.services.observability_service import ensure_model_budget, record_model_call


class RerankerError(Exception):
    pass


class Reranker(Protocol):
    def rank(self, question: str, candidates: list[dict]) -> list[dict]: ...


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.casefold()))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(phrase[i:i + 2] for i in range(max(1, len(phrase) - 1)))
    return words - {"what", "is", "are", "the", "a", "an", "and", "of", "how", "does", "define"}


class LexicalReranker:
    """Deterministic development comparator, not a semantic cross encoder."""
    def rank(self, question: str, candidates: list[dict]) -> list[dict]:
        tokens = _tokens(question)
        maximum = max((item.get("rrfScore", 0) for item in candidates), default=1) or 1
        ranked = []
        for item in candidates:
            text = str(item.get("chunkText") or "")
            coverage = len(tokens & _tokens(text)) / max(len(tokens), 1)
            score = 0.85 * coverage + 0.1 * int(question.casefold() in text.casefold()) + 0.05 * item.get("rrfScore", 0) / maximum
            ranked.append({**item, "rerankScore": round(score, 6)})
        return sorted(ranked, key=lambda item: item["rerankScore"], reverse=True)


class HttpReranker:
    """SiliconFlow-compatible /rerank contract, explicitly configured endpoint."""
    def rank(self, question: str, candidates: list[dict]) -> list[dict]:
        if not settings.reranker_url or not settings.reranker_api_key or not settings.reranker_model:
            raise RerankerError("Reranker is not configured")
        ensure_model_budget()
        started = perf_counter()
        try:
            with httpx.Client(timeout=settings.reranker_timeout_seconds, trust_env=False, follow_redirects=False) as client:
                response = client.post(settings.reranker_url, headers={"Authorization": f"Bearer {settings.reranker_api_key}"},
                    json={"model": settings.reranker_model, "query": question,
                          "documents": [str(item.get("chunkText") or "")[:6000] for item in candidates],
                          "top_n": len(candidates), "return_documents": False})
                response.raise_for_status()
                payload = response.json(); results = payload["results"]
            # Require a complete permutation. Malformed/partial responses fall back
            # to the untouched RRF list rather than silently losing evidence.
            if not isinstance(results, list) or len(results) != len(candidates): raise ValueError("Incomplete result")
            indices = set(); scored = []
            for result in results:
                index = result["index"]; value = result["relevance_score"]
                if type(index) is not int or not 0 <= index < len(candidates) or index in indices: raise ValueError("Invalid index")
                if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1: raise ValueError("Invalid score")
                indices.add(index); scored.append({**candidates[index], "rerankScore": value})
            tokens = ((payload.get("meta") or {}).get("tokens") or {}).get("input_tokens")
            if type(tokens) is not int or tokens < 0:
                tokens = sum(max(len(str(item.get("chunkText") or "")[:6000]) // 4, 1) for item in candidates) + max(len(question) // 4, 1)
            record_model_call(capability="rerank", model_name=settings.reranker_model, status="succeeded", started_at=started,
                usage={"prompt_tokens": tokens}, estimated_cost_usd=tokens * settings.reranker_cost_per_million / 1_000_000,
                metadata={"candidateCount": len(candidates), "configuredCostPerMillion": settings.reranker_cost_per_million})
            return sorted(scored, key=lambda item: item["rerankScore"], reverse=True)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            record_model_call(capability="rerank", model_name=settings.reranker_model, status="failed", started_at=started, error_code="reranker_unavailable")
            raise RerankerError("Reranker unavailable or invalid response") from exc


def rerank(question: str, candidates: list[dict], mode: str) -> list[dict]:
    if not candidates or mode == "none": return candidates
    if mode == "lexical": return LexicalReranker().rank(question, candidates)
    if mode == "http": return HttpReranker().rank(question, candidates)
    raise RerankerError("Unknown reranker mode")


def classify_intent(question: str) -> str:
    if re.search(r"\b(compare|comparison|versus|vs|difference)\b|比较|对比|区别|异同", question, re.I): return "comparison"
    if re.search(r"\b(calculate|solve|compute|derive|prove)\b|计算|求解|证明|推导", question, re.I): return "problem"
    if re.search(r"\b(define|definition|what is|what are|mean)\b|什么是|是什么|定义", question, re.I): return "definition"
    return "general"


def select_diverse(candidates: list[dict], top_k: int) -> list[dict]:
    if len({item.get("materialId") for item in candidates}) < 2: return candidates[:top_k]
    cap = max(1, math.ceil(top_k / 2)); counts = {}; selected = []; deferred = []
    for item in candidates:
        source = item.get("materialId")
        if counts.get(source, 0) >= cap: deferred.append(item); continue
        counts[source] = counts.get(source, 0) + 1; selected.append(item)
        if len(selected) == top_k: break
    return (selected + deferred)[:top_k]
