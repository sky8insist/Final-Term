"""Compare pre-collected outputs against separate labels; offline, no credentials required."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.paired_quality_service import Gate, compare, check_gate, digest


def read_json(path):
    if path.stat().st_size > 10_000_000: raise ValueError('Artifact exceeds 10 MB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def reject_constant(value): raise ValueError('Non-finite JSON number')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=reject_constant)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gate', type=Path)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--bootstrap-samples', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261027)
    args = parser.parse_args(argv)
    inputs = [args.manifest, args.baseline, args.candidate]+([args.gate] if args.gate else [])
    if args.output.resolve() in {path.resolve() for path in inputs}:
        parser.error('Output must not overwrite inputs or labels')
    try:
        report = compare(*(read_json(path) for path in inputs[:3]), top_k=args.top_k,
                         bootstrap_samples=args.bootstrap_samples, seed=args.seed)
        spec = Gate.model_validate(read_json(args.gate)).model_dump() if args.gate else None
        failures = check_gate(report, spec) if spec is not None else None
    except (OSError, ValueError, TypeError):
        # Do not echo potentially private artifact content from validation errors.
        print('Invalid quality artifacts/configuration; no report written', file=sys.stderr)
        return 2
    report['gate'] = {'status': 'not_requested' if failures is None else 'failed' if failures else 'passed',
                      'failures': failures, 'spec': spec, 'specSha256': digest(spec) if spec else None}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'datasetKind': report['datasetKind'], 'evidenceStatus': report['evidenceStatus'], 'caseCount': report['caseCount'], 'gateStatus': report['gate']['status']}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == '__main__': raise SystemExit(main())
