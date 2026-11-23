"""Offline scoring against separate labels. No network, model judge or application writes."""
import hashlib
import json
import math
import random
from datetime import date
from statistics import mean
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
Grade = Annotated[StrictInt, Field(ge=0, le=3)]
Hash = Annotated[str, Field(strict=True, pattern=r'^[0-9a-f]{64}$')]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Stimulus(Contract):
    id: Identifier
    inputSha256: Hash


class RetrievalCase(Stimulus):
    id: Identifier
    kind: Literal['retrieval']
    relevance: dict[Identifier, Grade] = Field(min_length=1, max_length=1000)
    forbiddenIds: list[Identifier] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def consistent(self):
        if not any(self.relevance.values()): raise ValueError('Retrieval needs a positive relevance label')
        if any(self.relevance.get(key, 0) for key in self.forbiddenIds):
            raise ValueError('A forbidden source cannot also be relevant')
        return self


class GroundingCase(Stimulus):
    id: Identifier
    kind: Literal['grounding']
    evidenceSufficient: StrictBool | None = None
    answerGrounded: StrictBool | None = None

    @model_validator(mode='after')
    def labelled(self):
        if self.evidenceSufficient is None and self.answerGrounded is None: raise ValueError('Need at least one labelled guard decision')
        return self


class PlanCase(Stimulus):
    id: Identifier
    kind: Literal['plan']
    relevance: dict[Identifier, Grade] = Field(min_length=1, max_length=1000)
    allowedTopicIds: list[Identifier] = Field(min_length=1, max_length=1000)
    capacityMinutes: dict[str, Annotated[StrictInt, Field(ge=0, le=1440)]] = Field(min_length=1, max_length=366)

    @model_validator(mode='after')
    def consistent(self):
        for day in self.capacityMinutes:
            if date.fromisoformat(day).isoformat() != day: raise ValueError('Use ISO calendar dates')
        if not any(self.relevance.values()): raise ValueError('Plan needs positive labels')
        if any(grade and topic not in self.allowedTopicIds for topic, grade in self.relevance.items()):
            raise ValueError('Relevant topics must be allowed')
        return self


class Manifest(Contract):
    schemaVersion: Annotated[StrictInt, Field(ge=1, le=1)]
    datasetId: Identifier
    datasetVersion: Identifier
    datasetKind: Literal['synthetic-regression', 'human-labelled']
    labelProvenance: Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
    cases: list[Annotated[RetrievalCase | GroundingCase | PlanCase, Field(discriminator='kind')]] = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases): raise ValueError('Duplicate case IDs')
        return self


class RetrievalOutput(Stimulus):
    id: Identifier
    kind: Literal['retrieval']
    rankedIds: list[Identifier] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique_ranks(self):
        if len(set(self.rankedIds)) != len(self.rankedIds): raise ValueError('Duplicate ranked IDs')
        return self


class GroundingOutput(Stimulus):
    id: Identifier
    kind: Literal['grounding']
    evidenceAccepted: StrictBool
    answerAccepted: StrictBool


class PlanTask(Contract):
    topicId: Identifier
    day: date
    minutes: Annotated[StrictInt, Field(ge=1, le=1440)]
    taskType: Identifier = 'unspecified'

    @field_validator('day', mode='before')
    @classmethod
    def iso_day(cls, value):
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError('Task day must be an ISO date string')
        return value


class PlanOutput(Stimulus):
    id: Identifier
    kind: Literal['plan']
    tasks: list[PlanTask] = Field(max_length=2000)


class Arm(Contract):
    schemaVersion: Annotated[StrictInt, Field(ge=1, le=1)]
    runId: Identifier
    version: Identifier
    manifestSha256: Hash
    outputs: list[Annotated[RetrievalOutput | GroundingOutput | PlanOutput, Field(discriminator='kind')]] = Field(min_length=1, max_length=2000)


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def score_case(case, output, top_k: int) -> dict[str, float | None]:
    if case.kind == 'retrieval':
        ids = output.rankedIds[:top_k]
        relevant = {key for key, grade in case.relevance.items() if grade > 0}
        gains = [case.relevance.get(key, 0) for key in ids]
        ideal = sorted(case.relevance.values(), reverse=True)[:top_k]
        dcg = lambda values: sum((2**grade-1)/math.log2(index+2) for index, grade in enumerate(values))
        rank = next((index for index, key in enumerate(ids, 1) if key in relevant), None)
        return {'retrieval.ndcg': dcg(gains)/dcg(ideal), 'retrieval.mrr': 1/rank if rank else 0,
                'retrieval.recall': len(relevant.intersection(ids))/len(relevant),
                'retrieval.isolation': float(not set(output.rankedIds).intersection(case.forbiddenIds))}
    if case.kind == 'grounding':
        decisions = [(case.evidenceSufficient, output.evidenceAccepted), (case.answerGrounded, output.answerAccepted)]
        return {'grounding.falseReject': float(not output.evidenceAccepted) if case.evidenceSufficient is True else None,
                'grounding.falseAccept': float(output.evidenceAccepted) if case.evidenceSufficient is False else None,
                'grounding.supportedAnswerAccept': float(output.answerAccepted) if case.answerGrounded is True else None,
                'grounding.unsupportedAnswerAccept': float(output.answerAccepted) if case.answerGrounded is False else None,
                'grounding.decisionAccuracy': mean(expected == actual for expected, actual in decisions if expected is not None)}
    tasks = output.tasks
    allowed = set(case.allowedTopicIds)
    relevant = {key for key, value in case.relevance.items() if value > 0}
    days = {}
    for task in tasks: days[task.day.isoformat()] = days.get(task.day.isoformat(), 0)+task.minutes
    return {'plan.taskRelevance': mean(case.relevance.get(task.topicId, 0)/3 for task in tasks) if tasks else None,
            'plan.topicCoverage': len(relevant.intersection(task.topicId for task in tasks))/len(relevant),
            'plan.forbiddenTaskRate': mean(task.topicId not in allowed for task in tasks) if tasks else None,
            'plan.capacityViolationRate': mean(amount > case.capacityMinutes.get(day, 0) for day, amount in days.items()) if days else None,
            'plan.duplicateTaskRate': 1-len({(task.topicId, task.day, task.taskType) for task in tasks})/len(tasks) if tasks else None}


LOWER_IS_BETTER = {'grounding.falseReject', 'grounding.falseAccept', 'grounding.unsupportedAnswerAccept',
                   'plan.forbiddenTaskRate', 'plan.capacityViolationRate', 'plan.duplicateTaskRate'}


def _interval(deltas: list[float], samples: int, seed: int):
    if len(deltas) < 2: return None
    rng = random.Random(seed)
    estimates = sorted(sum(rng.choices(deltas, k=len(deltas)))/len(deltas) for _ in range(samples))
    def percentile(q):
        position = (len(estimates)-1)*q
        lo = math.floor(position)
        hi = math.ceil(position)
        return estimates[lo]+(estimates[hi]-estimates[lo])*(position-lo)
    return [percentile(.025), percentile(.975)]


def compare(manifest: dict, baseline: dict, candidate: dict, *, top_k: int = 5,
            bootstrap_samples: int = 2000, seed: int = 20261027) -> dict:
    if type(top_k) is not int or not 1 <= top_k <= 100: raise ValueError('top_k must be 1..100')
    if type(bootstrap_samples) is not int or not 100 <= bootstrap_samples <= 10000: raise ValueError('bootstrap_samples must be 100..10000')
    if type(seed) is not int or not 0 <= seed <= 2**32-1: raise ValueError('seed must be an unsigned 32-bit integer')
    labels = Manifest.model_validate(manifest)
    arms = [Arm.model_validate(value) for value in (baseline, candidate)]
    if arms[0].version == arms[1].version: raise ValueError('Comparison needs distinct version identifiers')
    if arms[0].runId == arms[1].runId: raise ValueError('Comparison needs distinct run IDs')
    label_hash = digest(labels.model_dump(mode='json'))
    ids = {case.id: case.kind for case in labels.cases}
    scores = []
    for arm in arms:
        actual_ids = [row.id for row in arm.outputs]
        if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(ids):
            raise ValueError('Every arm must contain every labelled case exactly once')
        if arm.manifestSha256 != label_hash: raise ValueError('Outputs belong to a different manifest revision')
        by_id = {row.id: row for row in arm.outputs}
        if any(by_id[key].kind != kind for key, kind in ids.items()): raise ValueError('Case/output kind mismatch')
        if any(by_id[case.id].inputSha256 != case.inputSha256 for case in labels.cases): raise ValueError('Case inputs differ across arms or labels')
        scores.append({case.id: score_case(case, by_id[case.id], top_k) for case in labels.cases})
    metrics = {}
    keys = sorted({key for row in scores[0].values() for key in row})
    for key in keys:
        base_available = [row[key] for row in scores[0].values() if row.get(key) is not None]
        cand_available = [row[key] for row in scores[1].values() if row.get(key) is not None]
        pairs = [(scores[0][case.id][key], scores[1][case.id][key]) for case in labels.cases
                 if scores[0][case.id].get(key) is not None and scores[1][case.id].get(key) is not None]
        deltas = [right-left for left, right in pairs]
        sign = -1 if key in LOWER_IS_BETTER else 1
        metrics[key] = {'direction': 'lower' if sign == -1 else 'higher', 'pairedCaseCount': len(pairs),
                        'baselineAvailable': len(base_available), 'candidateAvailable': len(cand_available),
                        'baselineAllAvailableMean': mean(base_available) if base_available else None,
                        'candidateAllAvailableMean': mean(cand_available) if cand_available else None,
                        'baseline': mean(left for left, _ in pairs) if pairs else None,
                        'candidate': mean(right for _, right in pairs) if pairs else None,
                        'delta': mean(deltas) if deltas else None,
                        'improvement': sign*mean(deltas) if deltas else None,
                        'deltaCI95': _interval(deltas, bootstrap_samples, seed)}
    return {'schemaVersion': 1, 'evaluatorVersion': 'paired-quality-v1',
            'datasetId': labels.datasetId, 'datasetVersion': labels.datasetVersion, 'datasetKind': labels.datasetKind,
            'evidenceStatus': 'regression-only' if labels.datasetKind == 'synthetic-regression' else 'external-labels-unverified',
            'labelProvenance': labels.labelProvenance, 'manifestSha256': label_hash,
            'baseline': {'runId': arms[0].runId, 'version': arms[0].version, 'sha256': digest(arms[0].model_dump(mode='json'))},
            'candidate': {'runId': arms[1].runId, 'version': arms[1].version, 'sha256': digest(arms[1].model_dump(mode='json'))},
            'config': {'topK': top_k, 'bootstrapSamples': bootstrap_samples, 'seed': seed,
                       'interval': 'paired case percentile bootstrap; 95%; null for <2 pairs'},
            'caseCount': len(labels.cases), 'metrics': metrics,
            'cases': [{'id': case.id, 'kind': case.kind, 'baseline': scores[0][case.id], 'candidate': scores[1][case.id]} for case in labels.cases],
            'limitations': ['offline scoring of supplied outputs and labels; no model/service was invoked by evaluator',
                            'human-labelled provenance is supplied metadata, not independently verified reviewer identity',
                            'guard verdicts use fixed evidence/answer stimuli; they are not generated-answer semantic quality',
                            'bootstrap assumes independent cases; related learners/documents need grouped sampling',
                            'synthetic data, small samples and repeated comparisons cannot establish production uplift',
                            'plan relevance labels and capacity are external judgements; no learning efficacy claim']}


class Gate(Contract):
    minimumCaseCount: Annotated[StrictInt, Field(ge=1, le=2000)] = 2
    candidateMinimums: dict[str, Annotated[float, Field(ge=0, le=1, strict=True)]] = Field(default_factory=dict)
    candidateMaximums: dict[str, Annotated[float, Field(ge=0, le=1, strict=True)]] = Field(default_factory=dict)
    minimumImprovements: dict[str, Annotated[float, Field(ge=-1, le=1, strict=True)]] = Field(default_factory=dict)
    minimumImprovementCI95LowerBounds: dict[str, Annotated[float, Field(ge=-1, le=1, strict=True)]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def consistent(self):
        if any(value > self.candidateMaximums.get(key, 1) for key, value in self.candidateMinimums.items()):
            raise ValueError('Minimum exceeds maximum')
        return self


def check_gate(report: dict, spec: dict) -> list[str]:
    gate = Gate.model_validate(spec)
    if not any((gate.candidateMinimums, gate.candidateMaximums, gate.minimumImprovements, gate.minimumImprovementCI95LowerBounds)):
        raise ValueError('Gate needs at least one explicit threshold')
    failures = []
    for field, thresholds in gate.model_dump(exclude={'minimumCaseCount'}).items():
        for name, threshold in thresholds.items():
            if name not in report['metrics']: raise ValueError(f'Unknown gate metric: {name}')
            metric = report['metrics'][name]
            # Absolute gates include all available candidate cases, not only nonempty baseline pairs.
            if field == 'minimumImprovementCI95LowerBounds':
                interval = metric['deltaCI95']
                value = None if interval is None else interval[0] if metric['direction'] == 'higher' else -interval[1]
            else:
                value = metric['improvement'] if field == 'minimumImprovements' else metric['candidateAllAvailableMean']
            count = metric['pairedCaseCount'] if field.startswith('minimumImprovement') else metric['candidateAvailable']
            if count < gate.minimumCaseCount or value is None or (value > threshold if field == 'candidateMaximums' else value < threshold):
                failures.append(f'{field}:{name}')
    return failures
