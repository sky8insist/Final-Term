from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config.settings import settings
from app.services.chunk_service import build_block_chunk_records, build_structure_chunk_bundle, sentence_chunks
from app.services.parent_context_service import expand_parent_context
from app.services.memory_service import normalize_retrieval_citations
from app.services.material_service import _insert_material_chunks


def block(text, kind="paragraph", sequence=0, **extra):
    return {"id": str(uuid4()), "content_text": text, "block_type": kind, "sequence_index": sequence,
            "page_number": 1, "confidence": 0.9, **extra}


def test_sentence_boundaries_preserve_whole_answers_and_baseline():
    text = "First sentence about matrices. Another complete explanation. Final answer is eigenvalue."
    chunks = sentence_chunks(text, 60, 20)
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert all(sentence in "\n".join(chunks) for sentence in text.split(". "))
    assert build_block_chunk_records([block("abcdefghij")], 4, 2)[0]["content"] == "abcd"
    assert sentence_chunks("x" * 100, 30, 5) == ["x" * 30, "x" * 30, "x" * 30, "x" * 25]


def test_headings_nested_paths_and_parent_size():
    blocks = [block("Chapter", "heading", 0, metadata={"style": "Heading 1"}),
              block("Explanation", sequence=1), block("Subsection", "heading", 2, metadata={"style": "Heading 2"}),
              block("Details", sequence=3), block("Next", "heading", 4, structured_data={"mineru": {"text_level": 1}})]
    bundle = build_structure_chunk_bundle(blocks)
    assert len(bundle["parents"]) == 3
    assert bundle["parents"][1]["heading_path"] == ["Chapter", "Subsection"]
    assert bundle["parents"][2]["heading_path"] == ["Next"]
    assert [row["chunk_index"] for row in bundle["records"]] == list(range(5))
    assert bundle["records"][1]["content_block_id"] == blocks[1]["id"]
    assert len({row["parent_chunk_id"] for row in bundle["records"]}) == 3


def test_table_rows_repeat_headers_without_splitting_cells():
    cells = [["Term", "Description"], ["matrix", "a" * 50], ["eigenvalue", "b" * 200], ["rank", "c" * 50]]
    table = block("table", "table", structured_data={"rows": cells})
    records = build_structure_chunk_bundle([table], chunk_size=100, overlap=10, parent_size=800)["records"]
    assert len(records) == 3
    assert all("Term" in row["content"] for row in records)
    assert any("b" * 200 in row["content"] and row["metadata"]["oversized_atomic"] for row in records)
    opaque = block("<table><tr><td>" + "z" * 1000 + "</td></tr></table>", "table")
    assert build_structure_chunk_bundle([opaque])["records"][0]["content"] == opaque["content_text"]


def test_formula_keeps_neighbouring_explanation_in_parent():
    blocks = [block("解释" * 450), block("Ax = λx", "formula", 1), block("λ 表示特征值。", sequence=2)]
    bundle = build_structure_chunk_bundle(blocks, chunk_size=800, parent_size=800)
    assert len(bundle["parents"]) == 1
    assert bundle["parents"][0]["block_ids"] == [row["id"] for row in blocks]
    assert next(row for row in bundle["records"] if row["block_type"] == "formula")["content"] == "Ax = λx"


def test_parent_size_and_missing_persisted_id():
    blocks = [block("a" * 700, sequence=i) for i in range(4)]
    assert len(build_structure_chunk_bundle(blocks, parent_size=800)["parents"]) == 4
    with pytest.raises(ValueError): build_structure_chunk_bundle([{**blocks[0], "id": None}])


def context_rows():
    return [{"anchorBlockId": "anchor", "parentChunkId": "parent", "blockId": key,
             "materialId": "material", "text": text, "blockType": kind, "pageNumber": page,
             "confidence": confidence, "sequence": sequence, "startTime": None, "endTime": None}
            for key, text, kind, page, confidence, sequence in [
                ("heading", "矩阵章节", "heading", 1, 1, 0), ("anchor", "formula", "formula", 2, 0.9, 1),
                ("explain", "λ 是特征值。", "paragraph", 2, 0.9, 2), ("private", "EXCLUDED", "paragraph", 3, 0.2, 3)]]


def expand(rows, **filters):
    calls = []
    def rpc(name, values):
        calls.append((name, values)); return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))
    citation = {"id": "child", "blockId": "anchor", "materialId": "material", "filename": "notes.pdf", "chunkText": "Ax = λx", "pageNumber": 2}
    before = deepcopy(citation)
    result = expand_parent_context(client=SimpleNamespace(rpc=rpc), user_id="owner", subject_id="subject", citations=[citation], **filters)
    assert citation["chunkText"] == before["chunkText"] and citation["pageNumber"] == 2 and citation["id"] == "child"
    assert calls[0][1]["p_user_id"] == "owner" and calls[0][1]["p_subject_id"] == "subject"
    return citation, result


def test_parent_expansion_preserves_primary_and_filters_every_secondary_source():
    citation, result = expand(context_rows(), page_to=2, min_confidence=0.5)
    assert result["expandedCount"] == 1 and "λ 是特征值" in citation["contextText"]
    assert "EXCLUDED" not in citation["contextText"]
    limited, _ = expand(context_rows(), block_types=["formula"])
    assert "contextBlocks" not in limited
    normalized = normalize_retrieval_citations([citation])
    assert len(normalized) == 3 and normalized[0]["text"] == "Ax = λx"
    assert {row["pageNumber"] for row in normalized} == {1, 2}


def test_parent_expansion_rejects_other_material_and_budget_overflow(monkeypatch):
    rows = context_rows(); rows[-1]["materialId"] = "foreign"
    monkeypatch.setattr(settings, "retrieval_parent_context_chars", 110)
    citation, _ = expand(rows)
    assert "EXCLUDED" not in citation["contextText"]
    assert len(citation["contextText"]) <= 110


def test_bundle_persistence_uses_one_scoped_rpc():
    calls = []
    client = SimpleNamespace(rpc=lambda name, args: (calls.append((name, args)) or SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"id": "child"}]))))
    bundle = build_structure_chunk_bundle([block("definition")])
    result = _insert_material_chunks(client=client, user_id="u", subject_id="s", material_id="m",
        records=bundle["records"], parents=bundle["parents"], strategy="structure")
    assert result == [{"id": "child"}] and len(calls) == 1
    assert calls[0][1]["p_user_id"] == "u" and calls[0][1]["p_strategy"] == "structure"
