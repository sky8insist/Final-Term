from io import BytesIO
import wave

from app.services import multimodal_service
from app.services.parse_service import parse_document_blocks


def test_image_analysis_becomes_structured_chart_block(monkeypatch):
    monkeypatch.setattr(
        multimodal_service,
        "analyze_image",
        lambda *_args, **_kwargs: {
            "kind": "chart", "ocrText": "2025 销量", "summary": "销量逐季上升",
            "confidence": 0.91,
            "chart": {"chartType": "line", "axes": ["季度", "销量"], "trends": ["上升"]},
        },
    )
    blocks = parse_document_blocks(b"fake-image", filename="chart.png", content_type="image/png")

    assert blocks[0]["block_type"] == "chart"
    assert blocks[0]["structured_data"]["chartType"] == "line"
    assert blocks[0]["confidence"] == 0.91
    assert blocks[0]["metadata"]["needsReview"] is False


def test_low_confidence_image_is_marked_for_review(monkeypatch):
    monkeypatch.setattr(
        multimodal_service,
        "analyze_image",
        lambda *_args, **_kwargs: {
            "kind": "image", "ocrText": "模糊", "summary": "无法确认", "confidence": 0.2,
            "image": {},
        },
    )
    block = parse_document_blocks(b"fake", filename="scan.jpg", content_type="image/jpeg")[0]
    assert block["metadata"]["needsReview"] is True


def test_audio_segments_keep_timestamps(monkeypatch):
    monkeypatch.setattr(
        multimodal_service,
        "transcribe_audio",
        lambda *_args, **_kwargs: {
            "text": "第一章 定义", "duration": 8.5, "language": "zh",
            "segments": [
                {"start": 0.0, "end": 3.2, "text": "第一章"},
                {"start": 3.2, "end": 8.5, "text": "定义"},
            ],
        },
    )
    blocks = parse_document_blocks(b"fake-audio", filename="lecture.mp3", content_type="audio/mpeg")

    assert [block["block_type"] for block in blocks] == ["audio", "audio"]
    assert blocks[1]["start_time"] == 3.2
    assert blocks[1]["end_time"] == 8.5
    assert blocks[1]["structured_data"]["language"] == "zh"


def test_audio_segment_offset_is_applied_to_provider_timestamps(monkeypatch):
    monkeypatch.setattr(
        multimodal_service,
        "transcribe_audio",
        lambda *_args, **_kwargs: {
            "text": "第二分片", "duration": 4.0, "language": "zh",
            "segments": [{"start": 1.0, "end": 4.0, "text": "第二分片"}],
        },
    )
    audio = BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 160)
    blocks = parse_document_blocks(
        audio.getvalue(), filename="lecture.segment-0002.wav",
        content_type="audio/wav", audio_time_offset=600.0,
        analyze_audio_transcript=False, audio_segment_index=1,
    )

    assert blocks[0]["start_time"] == 601.0
    assert blocks[0]["end_time"] == 604.0
    assert blocks[0]["structured_data"]["audioSegmentIndex"] == 1
