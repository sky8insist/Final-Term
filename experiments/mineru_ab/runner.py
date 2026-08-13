from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from experiments.mineru_ab.adapters.mineru_content_adapter import adapt_content_list, read_mineru_bundle
from experiments.mineru_ab.config import EXPERIMENT_ROOT, ExperimentSettings
from experiments.mineru_ab.generate_fixtures import generate
from experiments.mineru_ab.metrics import compare_runs, evaluate_run
from experiments.mineru_ab.models import ParseRun
from experiments.mineru_ab.pdf_preflight import inspect_pdf_text_layer
from experiments.mineru_ab.providers.baseline_provider import BaselineProvider
from experiments.mineru_ab.providers.mineru_provider import MinerUError, MinerUProvider
from experiments.mineru_ab.report import write_report


def _load_cases(manifest_path: Path | None = None) -> list[dict]:
    manifest = manifest_path or EXPERIMENT_ROOT / "fixtures" / "manifest.json"
    if not manifest.exists():
        if manifest_path is None:
            generate()
        else:
            raise FileNotFoundError(f"Experiment manifest not found: {manifest}")
    cases = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        case["_resolved_path"] = str((manifest.parent / case["path"]).resolve())
    return cases


def _path(case: dict) -> Path:
    return Path(case["_resolved_path"])


def run_baseline(cases: list[dict]) -> list[ParseRun]:
    provider = BaselineProvider()
    return [provider.parse(_path(case), case_id=case["id"], content_type=case["content_type"]) for case in cases]


def run_mineru(cases: list[dict], settings: ExperimentSettings) -> list[ParseRun]:
    settings.require_live_credentials()
    provider = MinerUProvider(settings)
    runs: list[ParseRun] = []
    try:
        for case in cases:
            path = _path(case)
            started = perf_counter()
            if path.suffix.lower() == ".pdf":
                preflight = inspect_pdf_text_layer(
                    path, sample_pages=settings.pdf_sample_pages,
                    min_text_chars_per_page=settings.min_text_chars_per_page,
                )
                if not preflight.accepted:
                    runs.append(ParseRun(
                        case_id=case["id"], provider="mineru", success=False,
                        duration_seconds=perf_counter() - started,
                        error_code=preflight.reason, error_message=preflight.reason,
                        metadata={"preflight": preflight.__dict__, "ocrEnabled": False},
                    ))
                    continue
            try:
                data_id = f"ab-{case['id']}-{uuid4().hex[:12]}"
                stage = "request_upload_ticket"
                ticket = provider.request_upload(filename=path.name, data_id=data_id)
                stage = "signed_upload"
                provider.upload_file(ticket, path)
                stage = "poll_remote_result"
                remote = provider.wait_for_result(ticket.batch_id)
                stage = "download_result"
                bundle = provider.download_result(str(remote["full_zip_url"]))
                stage = "adapt_result"
                content, _markdown, bundle_meta = read_mineru_bundle(
                    bundle, max_result_bytes=settings.max_result_bytes,
                    max_unpacked_bytes=settings.max_unpacked_bytes,
                )
                blocks = adapt_content_list(content)
                runs.append(ParseRun(
                    case_id=case["id"], provider="mineru", success=True,
                    duration_seconds=perf_counter() - started, blocks=blocks,
                    metadata={
                        "batchId": ticket.batch_id, "traceId": ticket.trace_id,
                        "remoteState": remote.get("state"), "ocrEnabled": False,
                        "modelVersion": "pipeline", **bundle_meta,
                    },
                ))
            except MinerUError as exc:
                runs.append(ParseRun(
                    case_id=case["id"], provider="mineru", success=False,
                    duration_seconds=perf_counter() - started,
                    error_code=exc.code, error_message=str(exc),
                    metadata={
                        "retryable": exc.retryable, "ocrEnabled": False,
                        "failedStage": locals().get("stage", "unknown"),
                        "modelVersion": "pipeline",
                    },
                ))
    finally:
        provider.close()
    return runs


def reuse_mineru(cases: list[dict], settings: ExperimentSettings, previous: dict) -> list[ParseRun]:
    """Rebuild MinerU blocks from completed batches without uploading again."""
    settings.require_live_credentials()
    prior = {
        item["case_id"]: item for item in previous.get("runs", [])
        if item.get("provider") == "mineru"
    }
    provider = MinerUProvider(settings)
    runs: list[ParseRun] = []
    try:
        for case in cases:
            item = prior.get(case["id"])
            if not item:
                raise RuntimeError(f"No prior MinerU run found for {case['id']}")
            metadata = dict(item.get("metadata") or {})
            if item.get("error_code") == "ocr_required":
                runs.append(ParseRun(
                    case_id=case["id"], provider="mineru", success=False,
                    duration_seconds=float(item.get("duration_seconds", 0)),
                    error_code="ocr_required", error_message="ocr_required",
                    metadata={**metadata, "reused": True},
                ))
                continue
            batch_id = metadata.get("batchId")
            if not batch_id:
                raise RuntimeError(f"Prior MinerU run has no batchId for {case['id']}")
            remote = provider.wait_for_result(str(batch_id))
            bundle = provider.download_result(str(remote["full_zip_url"]))
            content, _markdown, bundle_meta = read_mineru_bundle(
                bundle, max_result_bytes=settings.max_result_bytes,
                max_unpacked_bytes=settings.max_unpacked_bytes,
            )
            runs.append(ParseRun(
                case_id=case["id"], provider="mineru", success=True,
                duration_seconds=float(item.get("duration_seconds", 0)),
                blocks=adapt_content_list(content),
                metadata={**metadata, **bundle_meta, "reused": True},
            ))
    finally:
        provider.close()
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated MinerU no-OCR A/B experiment")
    parser.add_argument("mode", choices=["generate", "baseline", "live", "all", "reuse"])
    parser.add_argument(
        "--case", action="append", dest="case_ids",
        help="Run only the named manifest case; repeat the option for multiple cases",
    )
    parser.add_argument("--manifest", type=Path, help="Use an alternate corpus manifest")
    parser.add_argument("--include-text", action="store_true", help="Include extracted text in JSON output")
    args = parser.parse_args()
    if args.mode == "generate":
        generate()
        return 0
    cases = _load_cases(args.manifest.resolve() if args.manifest else None)
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in cases}
        if missing:
            parser.error(f"Unknown case id(s): {', '.join(sorted(missing))}")
    settings = ExperimentSettings.from_env()
    previous = None
    if args.mode == "reuse":
        summary_path = EXPERIMENT_ROOT / "results" / "summary.json"
        if not summary_path.exists():
            raise RuntimeError("No prior summary.json is available to reuse")
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
    baseline_runs = run_baseline(cases) if args.mode in {"baseline", "all", "reuse"} else []
    mineru_runs = run_mineru(cases, settings) if args.mode in {"live", "all"} else []
    if args.mode == "reuse":
        mineru_runs = reuse_mineru(cases, settings, previous or {})
    by_case = {case["id"]: case for case in cases}
    evaluations = [evaluate_run(run, by_case[run.case_id]) for run in baseline_runs + mineru_runs]
    baseline_by_case = {item.case_id: item for item in baseline_runs}
    mineru_by_case = {item.case_id: item for item in mineru_runs}
    comparisons = [
        compare_runs(baseline_by_case[case_id], mineru_by_case[case_id])
        for case_id in baseline_by_case.keys() & mineru_by_case.keys()
    ]
    payload = {
        "mode": args.mode, "ocrEnabled": False, "modelVersion": "pipeline",
        "evaluations": evaluations, "comparisons": comparisons,
        "runs": [run.to_dict(include_text=args.include_text) for run in baseline_runs + mineru_runs],
    }
    json_path, markdown_path = write_report(EXPERIMENT_ROOT / "results", payload)
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
