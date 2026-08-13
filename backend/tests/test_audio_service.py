from app.config.settings import settings
from app.services import audio_service, material_service


def test_long_audio_uses_nearby_silence_boundaries(monkeypatch):
    monkeypatch.setattr(settings, "audio_segment_seconds", 100)
    monkeypatch.setattr(settings, "max_audio_minutes", 10)
    monkeypatch.setattr(audio_service, "_probe_duration", lambda _path: 250.0)
    monkeypatch.setattr(audio_service, "_detect_silence_midpoints", lambda _path: [96.0, 204.0])
    monkeypatch.setattr(
        audio_service, "_extract_wav_segment",
        lambda _path, start, end: f"wav:{start}:{end}".encode(),
    )

    segments, duration = audio_service.split_audio_bytes(
        b"source", filename="lecture.m4a", content_type="audio/mp4",
    )

    assert duration == 250.0
    assert [(item.start_time, item.end_time) for item in segments] == [
        (0.0, 96.0), (96.0, 204.0), (204.0, 250.0),
    ]
    assert all(item.derived and item.content_type == "audio/wav" for item in segments)


def test_short_audio_keeps_original_without_decoding_segment(monkeypatch):
    monkeypatch.setattr(settings, "audio_segment_seconds", 600)
    monkeypatch.setattr(audio_service, "_probe_duration", lambda _path: 30.0)
    monkeypatch.setattr(
        audio_service, "_detect_silence_midpoints",
        lambda _path: (_ for _ in ()).throw(AssertionError("silence scan should not run")),
    )

    segments, duration = audio_service.split_audio_bytes(
        b"original", filename="lecture.mp3", content_type="audio/mpeg",
    )

    assert duration == 30.0
    assert segments[0].data == b"original"
    assert segments[0].derived is False


def test_material_retry_reuses_successful_audio_segment_transcriptions(monkeypatch):
    segments = [
        audio_service.AudioSegment(0, 0.0, 10.0, b"one", "one.wav", "audio/wav", False),
        audio_service.AudioSegment(1, 10.0, 20.0, b"two", "two.wav", "audio/wav", False),
    ]
    monkeypatch.setattr(material_service, "split_audio_bytes", lambda *_args, **_kwargs: (segments, 20.0))
    monkeypatch.setattr(material_service, "_store_audio_segments", lambda **_: {0: None, 1: None})
    monkeypatch.setattr(material_service, "analyze_transcript", lambda _text: {})
    monkeypatch.setattr(material_service, "build_audio_blocks", lambda result, **kwargs: [{
        "block_type": "audio", "content_text": result["text"], "structured_data": {},
        "page_number": None, "bounding_box": None, "start_time": kwargs["audio_time_offset"],
        "end_time": kwargs["audio_time_offset"] + 10, "parent_block_id": None,
        "sequence_index": 0, "parser_name": "transcription-api", "parser_version": "1.0.0",
        "confidence": 1.0, "source_hash": result["text"], "metadata": {},
    }])
    calls: list[str] = []
    monkeypatch.setattr(
        material_service, "transcribe_audio",
        lambda _data, **kwargs: calls.append(kwargs["filename"]) or {
            "text": kwargs["filename"], "segments": [], "duration": 10,
        },
    )

    class AudioSegmentTable:
        def __init__(self):
            self.rows: dict[int, dict] = {}
            self.filters: dict[str, object] = {}
            self.payload = None
            self.mode = "select"

        def select(self, *_args): self.mode = "select"; return self
        def eq(self, key, value): self.filters[key] = value; return self
        def limit(self, _value): return self
        def upsert(self, payload, **_kwargs):
            self.mode = "upsert"; self.payload = payload; return self
        def update(self, payload):
            self.mode = "update"; self.payload = payload; return self
        def execute(self):
            index = int(self.filters.get("segment_index", self.payload.get("segment_index", 0) if self.payload else 0))
            if self.mode == "select":
                row = self.rows.get(index)
                data = [row] if row else []
            elif self.mode == "upsert":
                self.rows[index] = {**self.rows.get(index, {}), **self.payload}
                data = [self.rows[index]]
            else:
                self.rows[index] = {**self.rows[index], **self.payload}
                data = [self.rows[index]]
            self.filters = {}
            return type("Response", (), {"data": data})()

    table = AudioSegmentTable()
    client = type("Client", (), {"table": lambda self, name: table if name == "audio_segments" else None})()
    arguments = {
        "client": client, "user_id": "user", "subject_id": "subject",
        "material_id": "material", "filename": "lecture.wav",
        "content_type": "audio/wav", "file_bytes": b"source",
    }

    first = material_service._parse_material_blocks(**arguments)
    second = material_service._parse_material_blocks(**arguments)

    assert len(first) == len(second) == 2
    assert calls == ["one.wav", "two.wav"]
