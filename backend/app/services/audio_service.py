from dataclasses import dataclass
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from app.config.settings import settings


class AudioProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioSegment:
    index: int
    start_time: float
    end_time: float
    data: bytes
    filename: str
    content_type: str
    derived: bool


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AudioProcessingError(
            f"{name} is required for safe audio duration checks and segmentation"
        )
    return path


def _run(command: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command, capture_output=True, check=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioProcessingError("Audio decoding or segmentation failed") from exc


@contextmanager
def _with_input_file(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower() or ".audio"
    temporary = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        temporary.write(data)
        temporary.close()
        yield temporary.name
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def _probe_duration(path: str) -> float:
    result = _run([
        _require_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
        "-of", "json", path,
    ])
    try:
        duration = float(json.loads(result.stdout.decode("utf-8"))["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AudioProcessingError("Audio duration could not be determined") from exc
    if duration <= 0:
        raise AudioProcessingError("Audio is empty")
    return duration


def _detect_silence_midpoints(path: str) -> list[float]:
    result = _run([
        _require_binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", path,
        "-af", f"silencedetect=noise={settings.audio_silence_threshold_db}dB:"
        f"d={settings.audio_min_silence_seconds}",
        "-f", "null", "-",
    ])
    stderr = result.stderr.decode("utf-8", errors="replace")
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    return [(start + end) / 2 for start, end in zip(starts, ends, strict=False) if end >= start]


def _segment_ranges(duration: float, silence_points: list[float]) -> list[tuple[float, float]]:
    target = max(float(settings.audio_segment_seconds), 30.0)
    if duration <= target:
        return [(0.0, duration)]
    ranges: list[tuple[float, float]] = []
    start = 0.0
    search_window = min(target * 0.2, 90.0)
    while duration - start > target:
        ideal = start + target
        candidates = [
            point for point in silence_points
            if ideal - search_window <= point <= ideal + search_window and point - start >= 30
        ]
        end = min(candidates, key=lambda point: abs(point - ideal)) if candidates else ideal
        ranges.append((start, min(end, duration)))
        start = min(end, duration)
    if duration - start > 0.05:
        ranges.append((start, duration))
    return ranges


def _extract_wav_segment(path: str, start: float, end: float) -> bytes:
    result = _run([
        _require_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}", "-i", path, "-t", f"{max(end - start, 0):.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
    ], timeout=max(180, int(end - start) * 2))
    if not result.stdout:
        raise AudioProcessingError("Audio segment was empty")
    return result.stdout


def split_audio_bytes(
    data: bytes, *, filename: str, content_type: str,
) -> tuple[list[AudioSegment], float]:
    with _with_input_file(data, filename) as path:
        duration = _probe_duration(path)
        if duration > settings.max_audio_minutes * 60:
            raise AudioProcessingError(
                f"Audio must be {settings.max_audio_minutes} minutes or shorter"
            )
        silence_points = (
            _detect_silence_midpoints(path)
            if duration > max(float(settings.audio_segment_seconds), 30.0) else []
        )
        ranges = _segment_ranges(duration, silence_points)
        if len(ranges) == 1:
            return [AudioSegment(
                index=0, start_time=0.0, end_time=duration, data=data,
                filename=filename, content_type=content_type, derived=False,
            )], duration
        segments = [
            AudioSegment(
                index=index, start_time=start, end_time=end,
                data=_extract_wav_segment(path, start, end),
                filename=f"{Path(filename).stem}.segment-{index + 1:04d}.wav",
                content_type="audio/wav", derived=True,
            )
            for index, (start, end) in enumerate(ranges)
        ]
        return segments, duration
