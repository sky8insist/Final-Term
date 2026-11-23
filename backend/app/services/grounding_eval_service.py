from app.services.evidence_assessment_service import assess_material_evidence
from app.services.grounding_service import verify_answer


def evaluate_grounding_cases(dataset):
    failures = []
    evidence_results = []
    answer_results = []
    for case in dataset['evidenceCases']:
        result = assess_material_evidence(question=case['question'], raw_context=case['text'],
            citations=[{'id': 'c1', 'materialId': 'm1', 'text': case['text']}])
        evidence_results.append((case['sufficient'], result['sufficient']))
        if result['sufficient'] != case['sufficient']: failures.append(case['id'])
    for case in dataset['answerCases']:
        citations = [{'id': f'c{index}', 'text': text} for index, text in enumerate(case['sources'], 1)]
        result = verify_answer(answer=case['answer'], citations=citations)
        answer_results.append((case['passed'], result['passed']))
        if result['passed'] != case['passed']: failures.append(case['id'])
    absent = [actual for expected, actual in evidence_results if not expected]
    present = [actual for expected, actual in evidence_results if expected]
    rejected = [actual for expected, actual in answer_results if not expected]
    return {'datasetKind': dataset['datasetKind'], 'evidenceCaseCount': len(evidence_results),
            'answerCaseCount': len(answer_results), 'insufficientRejectionRate': sum(not value for value in absent) / max(len(absent), 1),
            'sufficientAcceptanceRate': sum(present) / max(len(present), 1),
            'unsupportedAnswerRejectionRate': sum(not value for value in rejected) / max(len(rejected), 1), 'failures': failures}
