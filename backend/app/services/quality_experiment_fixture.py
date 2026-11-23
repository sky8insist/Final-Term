"""Explicit synthetic controls using real pure functions; never an independent human evaluation."""
import json
from datetime import date
from pathlib import Path

from app.services.evidence_assessment_service import assess_material_evidence
from app.services.grounding_service import verify_answer
from app.services.paired_quality_service import Manifest, digest
from app.services.reranker_service import LexicalReranker
from app.services.study_plan_service import build_schedule
from app.services.study_plan_v3_service import prioritize


def build_fixture_runs(root: Path):
    suite = json.loads((root/'evals/paired_quality_cases.json').read_text(encoding='utf-8'))
    ground = json.loads((root/'evals/grounding_cases.json').read_text(encoding='utf-8'))
    labels, inputs = [], []
    for case in suite['retrieval']:
        labels.append({key: value for key, value in case.items() if key != 'input'} | {'kind': 'retrieval', 'inputSha256': digest(case['input'])})
        inputs.append((case['id'], 'retrieval', case['input']))
    for case in suite['plans']:
        labels.append({key: value for key, value in case.items() if key != 'input'} | {'kind': 'plan', 'inputSha256': digest(case['input'])})
        inputs.append((case['id'], 'plan', case['input']))
    for case in ground['evidenceCases']:
        stimulus = {'question': case['question'], 'text': case['text'], 'answer': '', 'sources': [case['text']] if case['text'] else []}
        labels.append({'id': 'evidence-'+case['id'], 'kind': 'grounding', 'inputSha256': digest(stimulus), 'evidenceSufficient': case['sufficient']})
        inputs.append(('evidence-'+case['id'], 'grounding', stimulus))
    for case in ground['answerCases']:
        stimulus = {'question': '', 'text': '\n'.join(case['sources']), 'answer': case['answer'], 'sources': case['sources']}
        labels.append({'id': 'answer-'+case['id'], 'kind': 'grounding', 'inputSha256': digest(stimulus), 'answerGrounded': case['passed']})
        inputs.append(('answer-'+case['id'], 'grounding', stimulus))
    manifest = Manifest.model_validate({'schemaVersion': 1, 'datasetId': 'paired-controls', 'datasetVersion': '1',
        'datasetKind': 'synthetic-regression', 'labelProvenance': 'Repository-authored synthetic controls; grounding labels reused from labelled-rule-regression; not independent human labels.', 'cases': labels}).model_dump(mode='json')
    outputs = [[], []]
    # Executable paths receive input snapshots only; external relevance/guard labels are not scorer inputs.
    for case_id, kind, stimulus in inputs:
        predictions = []
        if kind == 'retrieval':
            predictions = [{'rankedIds': [row['id'] for row in rows]} for rows in
                           (stimulus['candidates'], LexicalReranker().rank(stimulus['query'], stimulus['candidates']))]
        elif kind == 'grounding':
            citations = [{'id': f'c{index}', 'text': text} for index, text in enumerate(stimulus['sources'], 1)]
            evidence = assess_material_evidence(question=stimulus['question'], raw_context=stimulus['text'], citations=citations)
            answer = verify_answer(answer=stimulus['answer'], citations=citations)
            predictions = [{'evidenceAccepted': bool(citations), 'answerAccepted': bool(citations and stimulus['answer'])},
                           {'evidenceAccepted': evidence['sufficient'], 'answerAccepted': answer['passed']}]
        else:
            current = prioritize(stimulus['signals'], stimulus['states'], stimulus['mappings'], 'STANDARD')
            for signals in (stimulus['signals'], current):
                plan = build_schedule(signals=signals, start=date.fromisoformat(stimulus['start']), target=date.fromisoformat(stimulus['target']),
                    daily_minutes=stimulus['dailyMinutes'], reserve_final_day=False, mode='STANDARD')
                predictions.append({'tasks': [{'topicId': row['knowledge_key'], 'day': row['scheduled_date'], 'minutes': row['estimated_minutes'], 'taskType': row['task_type']} for row in plan['tasks']]})
        for arm, prediction in zip(outputs, predictions):
            arm.append({'id': case_id, 'kind': kind, 'inputSha256': digest(stimulus), **prediction})
    arms = [{'schemaVersion': 1, 'runId': name, 'version': version, 'manifestSha256': digest(manifest), 'outputs': rows}
            for name, version, rows in zip(('control-run', 'current-run'),
            ('rrf-input+citation-only+unfiltered-plan-control-v1', 'lexical-dev+evidence-v2+claim-citation-v1+exam-state-scheduler-v3'), outputs)]
    return manifest, *arms
