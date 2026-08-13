from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def write_report(output_dir: Path, payload: dict) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    markdown_path = output_dir / "summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = payload.get("evaluations", [])
    lines = [
        "# MinerU no-OCR A/B experiment",
        "",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- OCR enabled: `{payload.get('ocrEnabled', False)}`",
        f"- Model: `{payload.get('modelVersion', 'pipeline')}`",
        f"- Unique cases: `{len({row['caseId'] for row in rows})}`",
        f"- Provider evaluations: `{len(rows)}`",
        "",
        "| Case | Provider | Success | Recall | Similarity | Blocks | Seconds | Error |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['caseId']} | {row['provider']} | {row['success']} | "
            f"{row['characterRecall']:.4f} | {row['textSimilarity']:.4f} | "
            f"{row['blocks']} | {row['durationSeconds']:.4f} | {row.get('errorCode') or ''} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    history = output_dir / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    (history / f"summary-{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (history / f"summary-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
