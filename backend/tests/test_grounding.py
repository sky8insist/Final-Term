import asyncio
import json
from pathlib import Path

import pytest

from app.config.settings import settings
from app.services import evidence_assessment_service as evidence, rag_service
from app.services.grounding_service import verify_answer
from app.services.grounding_eval_service import evaluate_grounding_cases

DATA = json.loads((Path(__file__).resolve().parents[1] / 'evals/grounding_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', DATA['evidenceCases'], ids=lambda row: row['id'])
def test_labelled_evidence_boundary(case):
    result = evidence.assess_material_evidence(question=case['question'], raw_context=case['text'],
        citations=[{'id': 'c1', 'materialId': 'm1', 'text': case['text']}])
    assert result['sufficient'] == case['sufficient']
    assert result['version'] == 'evidence-v2'


@pytest.mark.parametrize('case', DATA['answerCases'], ids=lambda row: row['id'])
def test_labelled_claim_boundary(case):
    result = verify_answer(answer=case['answer'], citations=[{'id': f'c{index}', 'text': text} for index, text in enumerate(case['sources'], 1)])
    assert result['passed'] == case['passed']


def test_offline_gate_has_no_mislabeled_rule_cases():
    report = evaluate_grounding_cases(DATA)
    assert not report['failures'] and report['insufficientRejectionRate'] == 1
    assert report['sufficientAcceptanceRate'] == 1 and report['unsupportedAnswerRejectionRate'] == 1


def test_source_diversity_counts_materials_not_duplicate_chunks():
    rows = [{'id': 'one', 'materialId': 'm', 'text': 'Matrix definition'},
            {'id': 'two', 'materialId': 'm', 'text': 'Matrix array'}]
    report = evidence.assess_material_evidence(question='Define matrix', raw_context='Matrix definition', citations=rows)
    assert report['sourceCount'] == 1 and report['citationCount'] == 2


@pytest.mark.parametrize('score', [True, 'bad', float('nan'), float('inf'), 10**400])
def test_invalid_retrieval_scores_never_crash_or_fake_semantic_support(score):
    report = evidence.assess_material_evidence(question='photosynthesis', raw_context='Matrix', citations=[{'text': 'Matrix', 'score': score}])
    assert not report['sufficient']


def test_external_sources_cannot_make_course_evidence_sufficient():
    report = evidence.assess_material_evidence(question='matrix', raw_context='Matrix', citations=[{'id': 'external:x', 'text': 'Matrix', 'sourceType': 'external'}])
    assert not report['sufficient'] and report['citationCount'] == 0


def test_citation_after_period_and_socratic_question():
    report = verify_answer(answer='矩阵是数表。 [1]', citations=[{'id': 'c1', 'text': '矩阵是数表。'}])
    assert report['passed'] and report['claimCount'] == 1
    question = verify_answer(answer='你能先写出矩阵的定义吗？', citations=[])
    assert question['passed'] and question['claimCount'] == 0


def test_fact_heading_is_not_a_verifier_bypass():
    report = verify_answer(answer='# Photosynthesis uses sunlight\nMatrix is an array[1].', citations=[{'id': 'c1', 'text': 'Matrix is an array.'}])
    assert not report['passed'] and report['claimCount'] == 2


@pytest.mark.parametrize('question', ['???', 'What is?', 'Explain x'])
def test_grammar_and_empty_tokens_cannot_make_irrelevant_evidence_sufficient(question):
    report = evidence.assess_material_evidence(question=question, raw_context='A matrix is an array', citations=[{'text': 'A matrix is an array'}])
    assert not report['sufficient']


def test_shared_grammar_is_not_claim_support():
    result = verify_answer(answer='Photosynthesis is a process[1].', citations=[{'id': 'c1', 'text': 'A matrix is an array.'}])
    assert not result['passed']


@pytest.mark.parametrize('marker', ['[citation:invented]', '[c99]', '[' + '9' * 5000 + ']'])
def test_extra_unknown_or_oversized_citation_cannot_bypass_allowlist(marker):
    report = verify_answer(answer=f'Matrix is an array[1] {marker}.', citations=[{'id': 'c1', 'text': 'Matrix is an array.'}])
    assert not report['passed'] and report['reason'] == 'fabricated_citation'


@pytest.mark.parametrize('mode', ['disabled', 'invalid_quote', 'valid_quote', 'unavailable'])
def test_borderline_judge_is_optional_and_requires_canonical_quote(monkeypatch, mode):
    from app.services import llm_service
    monkeypatch.setattr(settings, 'enable_evidence_judge', mode != 'disabled')
    calls = []
    async def judge(*_, **kw):
        calls.append(kw)
        if mode == 'unavailable': raise llm_service.LLMServiceError('unavailable')
        return {'sufficient': True, 'supports': [{'id': 'c1', 'quote': 'A rectangular array' if mode == 'valid_quote' else 'invented quotation'}]}
    monkeypatch.setattr(llm_service, 'generate_json_async', judge)
    source = [{'id': 'c1', 'text': 'A rectangular array', 'sourceType': 'material'}]
    report = evidence.assess_material_evidence(question='Define matrix', raw_context='A rectangular array', citations=source)
    assert report['decision'] == 'borderline'
    result = asyncio.run(evidence.resolve_borderline(question='Define matrix', citations=source, assessment=report))
    assert result['sufficient'] == (mode == 'valid_quote')
    assert len(calls) == (0 if mode == 'disabled' else 1)


def test_judge_never_runs_for_obvious_insufficiency(monkeypatch):
    from app.services import llm_service
    monkeypatch.setattr(settings, 'enable_evidence_judge', True)
    async def forbidden(*_, **kw): pytest.fail('empty evidence must not call the judge')
    monkeypatch.setattr(llm_service, 'generate_json_async', forbidden)
    report = evidence.assess_material_evidence(question='matrix', raw_context='', citations=[])
    assert not asyncio.run(evidence.resolve_borderline(question='matrix', citations=[], assessment=report))['sufficient']


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(settings, 'mock_external_apis', False)
    monkeypatch.setattr(settings, 'enable_evidence_judge', False)
    monkeypatch.setattr(settings, 'enable_hermes_memory', False)
    history = []
    monkeypatch.setattr(rag_service.memory_service, 'record_qa_history', lambda **kw: history.append(kw) or {'id': 'msg'})
    monkeypatch.setattr(rag_service.memory_service, 'increment_review_total', lambda **_: {})
    return history


@pytest.mark.parametrize('answer', ['Matrix is an array[99].', 'Matrix has 20 rows[1].', 'Matrix is an array.', '# Unsupported biology\nMatrix is an array[1].'])
def test_rejected_answer_is_never_saved_or_exposed(runtime, monkeypatch, answer):
    async def generate(*_, **kw): return answer
    monkeypatch.setattr(rag_service, 'generate_text_async', generate)
    result = asyncio.run(rag_service.answer_with_rag(user_id='u', subject_id='s', question='matrix', context_override={
        'question': 'matrix', 'rawContext': 'Matrix is an array', 'citations': [{'id': 'c1', 'text': 'Matrix is an array', 'materialId': 'm'}]}))
    assert result['answer'] == rag_service.INSUFFICIENT_CONTEXT_ANSWER and not result['citations']
    assert not result['generation']['grounded']
    assert runtime[0]['answer'] == result['answer'] and runtime[0]['citations'] == []
    assert not runtime[0]['assistant_metadata']['grounding']['passed']


def test_partial_question_refuses_before_answer_model(runtime, monkeypatch):
    async def forbidden(*_, **kw): pytest.fail('missing subquestion must not generate an answer')
    monkeypatch.setattr(rag_service, 'generate_text_async', forbidden)
    result = asyncio.run(rag_service.answer_with_rag(user_id='u', subject_id='s', question='matrix and determinant', context_override={
        'question': 'matrix and determinant', 'rawContext': 'Matrix definition', 'citations': [{'id': 'c1', 'text': 'Matrix definition'}]}))
    assert not result['generation']['grounded'] and result['generation']['evidenceAssessment']['questionCoverage'] == .5


def test_external_fallback_has_server_owned_sections_and_no_course_prompt(runtime, monkeypatch):
    monkeypatch.setattr(settings, 'enable_external_knowledge', True)
    async def search(_):
        return [{'url': 'https://example.edu/p', 'title': 'Reference', 'content': 'Photosynthesis uses sunlight', 'accessedAt': '2026-10-22', 'trustLevel': 'high'}]
    async def generate(prompt, **kw):
        assert 'PRIVATE_COURSE_TEXT' not in prompt
        return 'Photosynthesis uses sunlight[1].'
    monkeypatch.setattr(rag_service, 'search_public_knowledge_async', search)
    monkeypatch.setattr(rag_service, 'generate_text_async', generate)
    result = asyncio.run(rag_service.answer_with_rag(user_id='u', subject_id='s', question='photosynthesis', allow_external_knowledge=True, context_override={
        'question': 'photosynthesis', 'rawContext': 'PRIVATE_COURSE_TEXT', 'citations': [{'id': 'course', 'text': 'PRIVATE_COURSE_TEXT', 'sourceType': 'material'}]}))
    assert result['answer'].startswith('课程资料依据\n') and '\n外部补充知识\n' in result['answer']
    assert all(row['sourceType'] == 'external' for row in result['citations'])
    assert result['generation']['groundingScope'] == 'external'
