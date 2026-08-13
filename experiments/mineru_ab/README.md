# MinerU no-OCR A/B experiment

This is an isolated feasibility harness. It does not write to Supabase, Celery,
LightRAG, or the production upload flow.

## Safety contract

- MinerU model is fixed to `pipeline`.
- Every submitted file contains `is_ocr: false`.
- Live calls are disabled unless `MINERU_AB_LIVE=true` is set explicitly.
- The MinerU token is read from this experiment's local `.env`, the process
  environment, or explicitly namespaced `MINERU_AB_*` values in the repository
  root `.env`. Other root settings are ignored.
- Scanned PDFs without a usable text layer are rejected as `ocr_required`.
- Extracted text is redacted from JSON reports unless `--include-text` is used.

## Offline checkpoint

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest experiments/mineru_ab/tests -p no:cacheprovider
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.runner generate
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.runner baseline
```

The baseline imports the current parser read-only. It does not change existing
code or write to production services.

## Live MinerU smoke test

Do this only after reviewing the generated fixtures. Copy `.env.example` to
`.env`, add the experiment token, and explicitly enable live mode:

```env
MINERU_AB_LIVE=true
MINERU_AB_TOKEN=your-token
```

Then run:

```powershell
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.runner live --case simple_text_pdf
```

This first command uploads exactly one generated PDF. After its report is
reviewed, run `all` for the full paired corpus. Only files listed in
`fixtures/manifest.json` are submitted. The initial corpus is generated locally
and contains no user material.

To recompute metrics from the latest completed MinerU batch IDs without
uploading the files again:

```powershell
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.runner reuse
```

## External PDF corpus

Create a manifest that references files in place without copying them:

```powershell
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.prepare_pdf_corpus "PDF资料"
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.runner all --manifest experiments/mineru_ab/results/real_pdf_manifest.json
```

Generate per-page and per-block-type diagnostics from completed batches without
emitting raw document text:

```powershell
.\backend\.venv\Scripts\python.exe -m experiments.mineru_ab.diagnose_report --manifest experiments/mineru_ab/results/real_pdf_manifest.json
```
