"""Produce reproducible synthetic comparison artifacts without DB/provider calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.quality_experiment_fixture import build_fixture_runs
from app.services.paired_quality_service import compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    manifest, baseline, candidate = build_fixture_runs(ROOT)
    report = compare(manifest, baseline, candidate)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (('manifest', manifest), ('baseline', baseline), ('candidate', candidate), ('report', report)):
        target = args.output_dir/f'{name}.json'
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'datasetKind': report['datasetKind'], 'caseCount': report['caseCount'], 'metrics': report['metrics']}, ensure_ascii=False))


if __name__ == '__main__': main()
