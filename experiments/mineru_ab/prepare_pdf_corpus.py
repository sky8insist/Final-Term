from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from experiments.mineru_ab.config import EXPERIMENT_ROOT
from experiments.mineru_ab.pdf_preflight import inspect_pdf_text_layer


def prepare(source: Path, output: Path) -> dict:
    source = source.resolve()
    cases = []
    for index, path in enumerate(sorted(source.glob("*.pdf"))):
        preflight = inspect_pdf_text_layer(path, sample_pages=5, min_text_chars_per_page=20)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        cases.append({
            "id": f"real_pdf_{index + 1:02d}_{digest[:8]}",
            "label": path.name,
            "path": str(path.relative_to(output.parent, walk_up=True)),
            "content_type": "application/pdf",
            "expected_outcome": "success" if preflight.accepted else str(preflight.reason),
            "expected_text": "",
            "preflight": {
                "pages": preflight.page_count,
                "sampledPages": preflight.sampled_pages,
                "sampleCharacters": preflight.extracted_characters,
                "pagesWithText": preflight.pages_with_text,
            },
        })
    payload = {"source": str(source), "cases": cases}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an external PDF corpus without copying files")
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output", type=Path,
        default=EXPERIMENT_ROOT / "results" / "real_pdf_manifest.json",
    )
    args = parser.parse_args()
    payload = prepare(args.source, args.output.resolve())
    accepted = sum(case["expected_outcome"] == "success" for case in payload["cases"])
    print(json.dumps({"cases": len(payload["cases"]), "accepted": accepted,
                      "rejected": len(payload["cases"]) - accepted,
                      "manifest": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
