from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.services import reranker_service as service, retrieval_service


@pytest.mark.parametrize("query,intent", [("What is a matrix?", "definition"), ("求解矩阵的逆", "problem"), ("比较两种方法的区别", "comparison"), ("复习矩阵", "general")])
def test_intent(query, intent):
    assert service.classify_intent(query) == intent


def candidates():
    return [{"id": "noise", "materialId": "a", "chunkText": "general introduction", "rrfScore": 0.05},
            {"id": "answer", "materialId": "b", "chunkText": "矩阵乘法的定义和运算规则", "rrfScore": 0.01}]


def test_lexical_rerank_changes_order_without_mutating_sources():
    rows = candidates()
    assert service.rerank("矩阵乘法定义", rows, "lexical")[0]["id"] == "answer"
    assert "rerankScore" not in rows[0]
    assert service.rerank("query", rows, "none") == rows


def test_diversity_is_best_effort_and_never_underfills():
    rows = [{"id": str(i), "materialId": "a"} for i in range(6)] + [{"id": "b", "materialId": "b"}]
    result = service.select_diverse(rows, 5)
    assert len(result) == 5 and any(row["materialId"] == "b" for row in result)
    assert len({row["id"] for row in result}) == 5
    assert service.select_diverse(rows[:3], 5) == rows[:3]


def http(monkeypatch, results):
    calls = []
    class Client:
        def __init__(self, **kwargs): calls.append(kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"results": results})
    monkeypatch.setattr(service.httpx, "Client", Client)
    monkeypatch.setattr(settings, "reranker_url", "https://example.test/rerank")
    monkeypatch.setattr(settings, "reranker_api_key", "test-key")
    monkeypatch.setattr(settings, "reranker_model", "test-model")
    return calls


def test_http_uses_only_scores_and_original_sources(monkeypatch):
    calls = http(monkeypatch, [{"index": 1, "relevance_score": 0.9, "document": {"text": "forged"}}, {"index": 0, "relevance_score": 0.1}])
    result = service.rerank("query", candidates(), "http")
    assert result[0]["id"] == "answer" and result[0]["chunkText"] != "forged"
    assert calls[0]["trust_env"] is False and calls[0]["follow_redirects"] is False
    assert calls[1]["json"]["return_documents"] is False


@pytest.mark.parametrize("results", [[], [{"index": 0, "relevance_score": 0.5}] * 2,
    [{"index": 2, "relevance_score": 0.5}] * 2, [{"index": False, "relevance_score": 0.5}] * 2,
    [{"index": 0, "relevance_score": float("nan")}, {"index": 1, "relevance_score": 0.5}]])
def test_malformed_http_response_is_rejected(monkeypatch, results):
    http(monkeypatch, results)
    with pytest.raises(service.RerankerError): service.rerank("query", candidates(), "http")


def test_graph_hydration_restores_owned_canonical_content(monkeypatch):
    calls = []
    class Query:
        def select(self, *args): return self
        def eq(self, *args): calls.append(args); return self
        def in_(self, *args): return self
        def order(self, *args): return self
        def range(self, *args): return self
        def execute(self): return SimpleNamespace(data=[{"material_id": "own", "chunk_index": 0, "content": "canonical text", "materials": {"filename": "own.pdf"}}])
    markers = [{"materialId": "own", "chunkIndex": 0, "chunkText": "forged"}, {"materialId": "foreign", "chunkIndex": 0, "chunkText": "PRIVATE"}]
    result = retrieval_service._hydrate_lightrag(client=SimpleNamespace(table=lambda *_: Query()), user_id="u", subject_id="s", markers=markers)
    assert len(result) == 1 and result[0]["chunkText"] == "canonical text"
    assert ("user_id", "u") in calls and ("subject_id", "s") in calls and ("materials.user_id", "u") in calls


def setup_retrieval(monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(retrieval_service, "_get_subject_embedding_dimension", lambda **_: 2)
    monkeypatch.setattr(retrieval_service, "_subject_has_lightrag_index", lambda **_: True)
    monkeypatch.setattr(retrieval_service, "search_context", lambda **_: ("workspace", "PRIVATE unfiltered graph prose"))
    monkeypatch.setattr(retrieval_service, "_hydrate_lightrag", lambda **_: [])
    monkeypatch.setattr(retrieval_service, "_expand_page_context", lambda **_: None)
    monkeypatch.setattr(retrieval_service, "get_supabase_client", lambda: SimpleNamespace(rpc=lambda *_: SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))))
    monkeypatch.setattr(retrieval_service, "embed_texts", lambda _: [[0.1, 0.2]])
    monkeypatch.setattr(retrieval_service, "search_chunk_vectors", lambda **_: [
        {"material_id": "own", "content_block_id": "a", "content": "matrix defined", "block_type": "paragraph", "page_number": 2},
        {"material_id": "other", "content_block_id": "b", "content": "EXCLUDED", "block_type": "table", "page_number": 8}])


def test_dynamic_k_baseline_filters_and_no_raw_graph_leak(monkeypatch):
    setup_retrieval(monkeypatch)
    result = retrieval_service.search_subject_context(user_id="u", subject_id="s", question="What is matrix?", material_ids=["own"], block_types=["paragraph"], page_to=3)
    assert result["retrieval"]["topK"] == 3 and result["retrieval"]["candidateK"] == 20
    assert len(result["citations"]) == 1 and "PRIVATE" not in result["rawContext"] and "EXCLUDED" not in result["rawContext"]
    baseline = retrieval_service.search_subject_context(user_id="u", subject_id="s", question="What is matrix?", strategy="baseline")
    assert baseline["retrieval"]["topK"] == 5 and baseline["retrieval"]["reranker"] == "none"


def test_reranker_failure_preserves_rrf_evidence(monkeypatch):
    setup_retrieval(monkeypatch)
    monkeypatch.setattr(settings, "reranker_mode", "http")
    monkeypatch.setattr(settings, "reranker_url", None)
    result = retrieval_service.search_subject_context(user_id="u", subject_id="s", question="matrix", top_k=1)
    assert result["citations"][0]["blockId"] == "a" and result["retrieval"]["reranker"] == "none"
    assert "reranker_unavailable" in result["retrieval"]["warnings"]
