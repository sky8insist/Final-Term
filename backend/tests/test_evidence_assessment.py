from app.services.evidence_assessment_service import assess_material_evidence


def test_empty_material_evidence_is_insufficient():
    result = assess_material_evidence(question="什么是矩阵", raw_context="", citations=[])
    assert result["sufficient"] is False


def test_cited_material_is_kept_as_primary_evidence():
    result = assess_material_evidence(
        question="什么是矩阵", raw_context="矩阵是按行列排列的数表",
        citations=[{"chunkText": "矩阵是按行列排列的数表", "score": None}],
    )
    assert result["sufficient"] is True


def test_uniformly_low_scored_irrelevant_material_can_trigger_supplement():
    result = assess_material_evidence(
        question="矩阵为什么可以对角化", raw_context="数据库范式",
        citations=[{"chunkText": "数据库范式", "score": 0.01}],
    )
    assert result["sufficient"] is False

