import asyncio
import base64
import json
from time import perf_counter
from typing import Any

import httpx
from json_repair import repair_json

from app.config.settings import settings
from app.providers.openai_compatible import ProviderConfigurationError, get_model_provider
from app.services.llm_service import LLMServiceError, generate_json_async
from app.services.observability_service import ensure_model_budget, record_model_call
from app.services.mock_external_service import mock_image, mock_transcription


class MultimodalServiceError(RuntimeError):
    pass


VISION_SYSTEM_PROMPT = """你是严谨的期末复习资料视觉解析器。只描述图像中可验证的信息，不猜测缺失数据。
返回单个 JSON 对象：
{
  "kind": "table|chart|formula|image",
  "ocrText": "完整可见文字",
  "summary": "面向复习的客观摘要",
  "confidence": 0.0,
  "table": {"headers": [], "rows": [], "mergedCells": [], "units": [], "footnotes": []},
  "chart": {"chartType": "", "title": "", "axes": [], "legends": [], "series": [], "trends": [], "extrema": [], "anomalies": [], "limitations": []},
  "formula": {"latex": "", "symbols": [], "conditions": [], "derivation": "", "commonMistakes": [], "questionTypes": []}
}
不适用的对象使用空对象。数值不清晰时写入 limitations，不得编造。"""


def _api_headers() -> dict[str, str]:
    if not settings.openai_api_key:
        raise MultimodalServiceError("Multimodal API key is not configured")
    return {"Authorization": f"Bearer {settings.openai_api_key}"}


async def analyze_image_async(data: bytes, *, content_type: str, filename: str) -> dict[str, Any]:
    if settings.mock_external_apis:
        return mock_image(filename)
    ensure_model_budget()
    started_at = perf_counter()
    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "model": settings.vision_model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": f"解析文件 {filename}，提取 OCR、表格、图表或公式。"},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}},
            ]},
        ],
    }
    try:
        response_data = await get_model_provider().post_json_async("chat/completions", payload, timeout=180)
        content = response_data["choices"][0]["message"]["content"]
        parsed = json.loads(repair_json(content))
    except (httpx.HTTPError, ProviderConfigurationError, KeyError, IndexError, TypeError, ValueError) as exc:
        record_model_call(capability="vision", model_name=settings.vision_model, status="failed",
                          started_at=started_at, error_code="vision_error", metadata={"filename": filename})
        raise MultimodalServiceError("Image analysis failed") from exc
    if parsed.get("kind") not in {"table", "chart", "formula", "image"}:
        parsed["kind"] = "image"
    parsed["confidence"] = min(max(float(parsed.get("confidence", 0.5)), 0.0), 1.0)
    record_model_call(capability="vision", model_name=settings.vision_model, status="succeeded",
                      started_at=started_at, usage=response_data.get("usage"), metadata={"filename": filename},
                      estimated_cost_usd=settings.vision_cost_per_call)
    return parsed


async def transcribe_audio_async(data: bytes, *, content_type: str, filename: str) -> dict[str, Any]:
    if settings.mock_external_apis:
        return mock_transcription(filename)
    ensure_model_budget()
    started_at = perf_counter()
    files = {"file": (filename, data, content_type)}
    form = {"model": settings.transcription_model, "response_format": "verbose_json",
            "timestamp_granularities[]": "segment"}
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions",
                headers=_api_headers(), data=form, files=files,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        record_model_call(capability="transcription", model_name=settings.transcription_model,
                          status="failed", started_at=started_at, error_code="transcription_error")
        raise MultimodalServiceError("Audio transcription failed") from exc
    text, segments = str(result.get("text", "")).strip(), result.get("segments") or []
    if not text and not segments:
        raise MultimodalServiceError("Audio transcription returned no text")
    record_model_call(capability="transcription", model_name=settings.transcription_model,
                      status="succeeded", started_at=started_at,
                      metadata={"duration": result.get("duration"), "filename": filename},
                      estimated_cost_usd=(float(result.get("duration") or 0) / 60)
                      * settings.transcription_cost_per_minute)
    return {"text": text, "segments": segments, "duration": result.get("duration"),
            "language": result.get("language")}


def analyze_image(data: bytes, *, content_type: str, filename: str) -> dict[str, Any]:
    return asyncio.run(analyze_image_async(data, content_type=content_type, filename=filename))


def transcribe_audio(data: bytes, *, content_type: str, filename: str) -> dict[str, Any]:
    return asyncio.run(transcribe_audio_async(data, content_type=content_type, filename=filename))


async def analyze_transcript_async(transcript: str) -> dict[str, Any]:
    prompt = f"""整理课程录音转写，严格返回 JSON：
{{"correctedTranscript":"仅修正标点和明确术语，不改变事实","summary":"章节摘要","chapters":[{{"title":"","summary":""}}],"knowledgePoints":[],"examPoints":[],"uncertainTerms":[]}}
不得补充录音中没有的知识；无法确定的术语放入 uncertainTerms。
转写：{transcript[:30000]}"""
    try:
        return await generate_json_async(prompt)
    except LLMServiceError:
        return {"correctedTranscript": transcript, "summary": "", "chapters": [],
                "knowledgePoints": [], "examPoints": [], "uncertainTerms": []}


def analyze_transcript(transcript: str) -> dict[str, Any]:
    return asyncio.run(analyze_transcript_async(transcript))
