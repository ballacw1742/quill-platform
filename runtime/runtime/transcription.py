"""Local audio transcription substrate (Sprint Gemma.3).

Wraps the OpenAI Whisper CLI (already installed at /opt/homebrew/bin/whisper)
into an async-friendly Python interface. Produces a normalized transcript
artifact that downstream agents (daily-brief, knowledge-manager, etc.) can
consume without re-implementing whisper plumbing.

The Blomfield "record everything" recording substrate this serves:

  audio file in  ->  Whisper local  ->  TranscriptArtifact  ->  agents

No audio leaves the machine. No API key required. Models live in ~/.cache/whisper.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


DEFAULT_WHISPER_BIN = shutil.which("whisper") or "/opt/homebrew/bin/whisper"
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small.en")
DEFAULT_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "en")


class TranscriptionError(RuntimeError):
    """Whisper CLI failed or returned unparseable output."""


@dataclass
class TranscriptSegment:
    """One segment of speech from Whisper's JSON output."""

    id: int
    start: float
    end: float
    text: str


@dataclass
class TranscriptArtifact:
    """Normalized transcript ready for downstream agents.

    Field shape is intentionally minimal so it can serialize cleanly into
    Quill's audit log and approval items.
    """

    source_path: str
    model: str
    language: str
    duration_s: float
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    raw_json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "model": self.model,
            "language": self.language,
            "duration_s": self.duration_s,
            "text": self.text,
            "segments": [
                {"id": s.id, "start": s.start, "end": s.end, "text": s.text}
                for s in self.segments
            ],
            "raw_json_path": self.raw_json_path,
        }


async def transcribe(
    audio_path: str | Path,
    *,
    model: str | None = None,
    language: str | None = None,
    output_dir: Path | None = None,
    whisper_bin: str | None = None,
    timeout_s: float = 1800.0,
) -> TranscriptArtifact:
    """Transcribe an audio file with local Whisper.

    Defaults to the ``small.en`` model (good speed/quality tradeoff on M-series).
    The ``output_dir`` defaults to a tempdir; we keep the raw JSON for audit.
    """
    audio_path = Path(audio_path).resolve()
    if not audio_path.is_file():
        raise TranscriptionError(f"audio file not found: {audio_path}")

    model = model or DEFAULT_MODEL
    language = language or DEFAULT_LANGUAGE
    bin_path = whisper_bin or DEFAULT_WHISPER_BIN

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="quill-whisper-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        bin_path,
        str(audio_path),
        "--model", model,
        "--language", language,
        "--output_format", "json",
        "--output_dir", str(out_dir),
        "--verbose", "False",
    ]
    log.info("transcription.start", file=str(audio_path), model=model, language=language)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError as e:
        proc.kill()
        raise TranscriptionError(f"whisper timed out after {timeout_s}s") from e

    if proc.returncode != 0:
        raise TranscriptionError(
            f"whisper exited {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:500]}"
        )

    json_path = out_dir / f"{audio_path.stem}.json"
    if not json_path.is_file():
        raise TranscriptionError(f"whisper did not write expected JSON at {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    segs = [
        TranscriptSegment(
            id=int(s.get("id", i)),
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
            text=str(s.get("text", "")).strip(),
        )
        for i, s in enumerate(raw.get("segments", []))
    ]
    duration = float(segs[-1].end) if segs else 0.0

    log.info(
        "transcription.done",
        file=str(audio_path),
        duration_s=duration,
        segments=len(segs),
        chars=len(raw.get("text", "")),
    )

    return TranscriptArtifact(
        source_path=str(audio_path),
        model=model,
        language=raw.get("language", language),
        duration_s=duration,
        text=str(raw.get("text", "")).strip(),
        segments=segs,
        raw_json_path=str(json_path),
    )


__all__ = ["transcribe", "TranscriptArtifact", "TranscriptSegment", "TranscriptionError"]
