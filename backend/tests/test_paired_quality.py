from copy import deepcopy
from pathlib import Path
import json
import math

import pytest

from app.services.paired_quality_service import Manifest, compare, check_gate, digest
from app.services.quality_experiment_fixture import build_fixture_runs
from scripts.compare_quality_runs import main, read_json

ROOT = Path(__file__).resolve().parents[1]
INPUT = digest({'query': 'fixed independent stimulus'})


def runs(count=2):
    cases = [{'id': f'r{i}', 'kind': 'retrieval', 'inputSha256': INPUT, 'relevance': {'good': 3, 'bad': 0}, 'forbiddenIds': ['private']} for i in range(count)]
    return package(cases, [{'rankedIds': ['bad', 'good']} for _ in cases], [{'rankedIds': ['good', 'bad']} for _ in cases])


def package(cases, left, right):
    manifest = Manifest.model_validate({'schemaVersion': 1, 'datasetId': 'test', 'datasetVersion': '1',
        'datasetKind': 'synthetic-regression', 'labelProvenance': 'Test fixtures only', 'cases': cases}).model_dump(mode='json')
    arms = [{'schemaVersion': 1, 'runId': name, 'version': name, 'manifestSha256': digest(manifest),
             'outputs': [{'id': case['id'], 'kind': case['kind'], 'inputSha256': case['inputSha256'], **value} for case, value in zip(cases, outputs)]}
            for name, outputs in (('baseline', left), ('candidate', right))]
    return manifest, *arms


def evaluate(data, **kwargs): return compare(*data, bootstrap_samples=100, **kwargs)


def test_hand_calculated_ndcg_mrr_and_paired_interval():
    report = evaluate(runs())
    metric = report['metrics']['retrieval.ndcg']
    assert metric['baseline'] == pytest.approx(1/math.log2(3))
    assert metric['candidate'] == 1
    assert metric['deltaCI95'] == pytest.approx([1-1/math.log2(3)]*2)
    assert report['metrics']['retrieval.mrr']['delta'] == .5
    assert evaluate(runs()) == report


def test_single_case_has_no_interval_and_default_gate_requires_more_samples():
    report = evaluate(runs(1))
    assert report['metrics']['retrieval.ndcg']['deltaCI95'] is None
    assert check_gate(report, {'candidateMinimums': {'retrieval.ndcg': 1.0}})


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'duplicate', 'stale_hash', 'input_hash', 'kind', 'same_version', 'same_run', 'rank_duplicates'])
def test_invalid_pairing_and_artifact_revisions_are_rejected(mutation):
    data = list(deepcopy(runs()))
    candidate = data[2]
    if mutation == 'missing': candidate['outputs'].pop()
    elif mutation == 'extra': candidate['outputs'].append({**candidate['outputs'][0], 'id': 'unexpected'})
    elif mutation == 'duplicate': candidate['outputs'][1] = candidate['outputs'][0]
    elif mutation == 'stale_hash': candidate['manifestSha256'] = '0'*64
    elif mutation == 'input_hash': candidate['outputs'][0]['inputSha256'] = '0'*64
    elif mutation == 'kind': candidate['outputs'][0] = {'id': 'r0', 'kind': 'grounding', 'inputSha256': INPUT, 'evidenceAccepted': True, 'answerAccepted': False}
    elif mutation == 'same_version': candidate['version'] = data[1]['version']
    elif mutation == 'same_run': candidate['runId'] = data[1]['runId']
    elif mutation == 'rank_duplicates': candidate['outputs'][0]['rankedIds'] = ['good', 'good']
    with pytest.raises(ValueError): evaluate(data)


@pytest.mark.parametrize('value', [True, -1, 4, '3', float('nan')])
def test_relevance_labels_are_strict_bounded_integers(value):
    data = list(runs())
    data[0]['cases'][0]['relevance']['good'] = value
    with pytest.raises(ValueError): evaluate(data)


def test_foreign_source_is_detected_even_beyond_top_k():
    data = list(runs())
    data[2]['outputs'][0]['rankedIds'].append('private')
    report = evaluate(data, top_k=1)
    assert report['cases'][0]['candidate']['retrieval.isolation'] == 0
    assert report['metrics']['retrieval.isolation']['candidate'] == .5
    assert check_gate(report, {'candidateMinimums': {'retrieval.isolation': 1.0}})


def test_guard_missing_label_is_excluded_and_false_reject_direction_is_correct():
    cases = [{'id': 'g1', 'kind': 'grounding', 'inputSha256': INPUT, 'evidenceSufficient': True},
             {'id': 'g2', 'kind': 'grounding', 'inputSha256': INPUT, 'evidenceSufficient': False}]
    left = [{'evidenceAccepted': False, 'answerAccepted': True}]*2
    right = [{'evidenceAccepted': True, 'answerAccepted': True}, {'evidenceAccepted': False, 'answerAccepted': True}]
    report = evaluate(package(cases, left, right))
    assert report['metrics']['grounding.falseReject']['pairedCaseCount'] == 1
    assert report['metrics']['grounding.falseReject']['improvement'] == 1
    assert report['metrics']['grounding.supportedAnswerAccept']['candidate'] is None
    assert report['metrics']['grounding.decisionAccuracy']['candidate'] == 1


def test_unknown_guard_labels_are_not_treated_as_negative_ground_truth():
    data = list(runs())
    data[0]['cases'][0] = {'id': 'r0', 'kind': 'grounding', 'inputSha256': INPUT}
    with pytest.raises(ValueError): evaluate(data)


def plan_case():
    return {'id': 'p', 'kind': 'plan', 'inputSha256': INPUT, 'relevance': {'a': 3, 'b': 0},
            'allowedTopicIds': ['a', 'b'], 'capacityMinutes': {'2026-10-27': 60}}


def test_plan_relevance_duplicate_and_capacity_are_external_labels_not_priority_scores():
    task = {'topicId': 'a', 'day': '2026-10-27', 'minutes': 25}
    output = {'tasks': [task, task, {**task, 'topicId': 'b'}]}
    report = evaluate(package([plan_case()], [output], [output]))
    metrics = report['metrics']
    assert metrics['plan.taskRelevance']['candidate'] == pytest.approx(2/3)
    assert metrics['plan.duplicateTaskRate']['candidate'] == pytest.approx(1/3)
    assert metrics['plan.capacityViolationRate']['candidate'] == 1
    assert metrics['plan.topicCoverage']['candidate'] == 1


def test_empty_plan_has_null_precision_but_zero_coverage_and_no_fake_safety_pass():
    report = evaluate(package([plan_case()], [{'tasks': []}], [{'tasks': []}]))
    assert report['metrics']['plan.topicCoverage']['candidate'] == 0
    assert report['metrics']['plan.taskRelevance']['candidate'] is None
    assert check_gate(report, {'minimumCaseCount': 1, 'candidateMaximums': {'plan.forbiddenTaskRate': 0.0}})


def test_absolute_gate_includes_unpaired_candidate_errors():
    case = plan_case()
    cases = [case, {**case, 'id': 'p2'}]
    task = {'topicId': 'foreign', 'day': '2026-10-27', 'minutes': 20}
    report = evaluate(package(cases, [{'tasks': []}]*2, [{'tasks': [task]}]*2))
    metric = report['metrics']['plan.forbiddenTaskRate']
    assert metric['pairedCaseCount'] == 0 and metric['candidateAllAvailableMean'] == 1
    assert check_gate(report, {'candidateMaximums': {'plan.forbiddenTaskRate': 0.0}})


@pytest.mark.parametrize('day', [0, '20261027', '2026-02-30', '2026-10-27T00:00:00'])
def test_plan_dates_cannot_be_implicitly_coerced(day):
    output = {'tasks': [{'topicId': 'a', 'day': day, 'minutes': 25}]}
    with pytest.raises(ValueError): evaluate(package([plan_case()], [output], [output]))


@pytest.mark.parametrize('spec', [{}, {'candidateMinimums': {'typo': 1.0}}, {'candidateMaximums': {'retrieval.mrr': float('nan')}},
                                 {'candidateMinimums': {'retrieval.mrr': .9}, 'candidateMaximums': {'retrieval.mrr': .1}}])
def test_invalid_gate_cannot_silently_pass(spec):
    with pytest.raises(ValueError): check_gate(evaluate(runs()), spec)


def test_ci_gate_uses_improvement_sign_for_lower_is_better():
    cases = [{'id': f'g{i}', 'kind': 'grounding', 'inputSha256': INPUT, 'evidenceSufficient': False} for i in range(2)]
    report = evaluate(package(cases, [{'evidenceAccepted': True, 'answerAccepted': False}]*2,
                             [{'evidenceAccepted': False, 'answerAccepted': False}]*2))
    assert not check_gate(report, {'minimumImprovementCI95LowerBounds': {'grounding.falseAccept': .9}})


def test_real_pure_functions_keep_lexical_regression_visible_and_do_not_claim_live_results():
    report = evaluate(build_fixture_runs(ROOT))
    assert report['caseCount'] == 24 and report['datasetKind'] == 'synthetic-regression'
    negative = next(row for row in report['cases'] if row['id'] == 'rank-lexical-ambiguity')
    assert negative['candidate']['retrieval.ndcg'] < negative['baseline']['retrieval.ndcg']
    assert report['metrics']['retrieval.ndcg']['deltaCI95'][0] < 0
    assert check_gate(report, {'minimumImprovementCI95LowerBounds': {'retrieval.ndcg': 0.0}})
    assert not check_gate(report, json.loads((ROOT/'evals/paired_quality_gate.json').read_text(encoding='utf-8')))
    assert 'Flowers' not in json.dumps(report)


def test_cli_writes_reproducible_report_and_meaningful_exit_codes(tmp_path):
    paths = [tmp_path/f'{name}.json' for name in ('labels', 'left', 'right')]
    for path, value in zip(paths, runs()): path.write_text(json.dumps(value), encoding='utf-8')
    output = tmp_path/'report.json'
    gate = tmp_path/'gate.json'
    gate.write_text(json.dumps({'candidateMaximums': {'retrieval.mrr': 0.0}}), encoding='utf-8')
    args = [*(str(path) for path in paths), '--output', str(output), '--bootstrap-samples', '100']
    assert main(args) == 0
    assert read_json(output)['gate']['status'] == 'not_requested'
    assert main([*args, '--gate', str(gate)]) == 1
    assert read_json(output)['gate']['status'] == 'failed'
    assert read_json(output)['gate']['specSha256']
    bad = read_json(paths[2]); bad['manifestSha256'] = '0'*64
    paths[2].write_text(json.dumps(bad), encoding='utf-8')
    assert main(args) == 2


def test_cli_refuses_overwriting_labels(tmp_path):
    paths = [tmp_path/f'{i}.json' for i in range(3)]
    for path, value in zip(paths, runs()): path.write_text(json.dumps(value), encoding='utf-8')
    before = paths[0].read_bytes()
    with pytest.raises(SystemExit): main([*(str(path) for path in paths), '--output', str(paths[0])])
    assert paths[0].read_bytes() == before


@pytest.mark.parametrize('text', ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_json_reader_rejects_ambiguous_or_nonfinite_artifacts(tmp_path, text):
    path = tmp_path/'bad.json'; path.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError): read_json(path)
