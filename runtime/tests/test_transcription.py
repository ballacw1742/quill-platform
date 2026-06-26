"""Tests for runtime.transcription — JSON parsing + subprocess wiring."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.transcription import (
    TranscriptionError,
    TranscriptArtifact,
    transcribe,
)


@pytest.fixture
def fake_audio(tmp_path: Path) -> Path:
    p = tmp_path / "meeting.wav"
    p.write_bytes(b"\x52\x49\x46\x46fake-wav")
    return p


def _make_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


def test_transcribe_happy_path_parses_segments(fake_audio: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    raw = {
        "text": "Hello world. This is a test.",
        "language": "en",
        "segments": [
            {"id": 0, "start": 0.0, "end": 1.5, "text": "Hello world."},
            {"id": 1, "start": 1.5, "end": 3.0, "text": " This is a test."},
        ],
    }
    (out_dir / f"{fake_audio.stem}.json").write_text(json.dumps(raw))

    proc = _make_proc(0)
    with patch("runtime.transcription.asyncio.create_subprocess_exec",
               AsyncMock(return_value=proc)):
        artifact = asyncio.run(
            transcribe(fake_audio, output_dir=out_dir, whisper_bin="/usr/bin/whisper")
        )

    assert isinstance(artifact, TranscriptArtifact)
    assert artifact.source_path == str(fake_audio.resolve())
    assert artifact.text == "Hello world. This is a test."
    assert artifact.language == "en"
    assert artifact.duration_s == 3.0
    assert len(artifact.segments) == 2
    assert artifact.segments[0].text == "Hello world."
    assert artifact.segments[1].start == 1.5


def test_transcribe_missing_audio_raises(tmp_path: Path):
    bad = tmp_path / "nope.wav"
    with pytest.raises(TranscriptionError):
        asyncio.run(transcribe(bad))


def test_transcribe_nonzero_exit_raises(fake_audio: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    proc = _make_proc(2, stderr=b"model not found")
    with patch("runtime.transcription.asyncio.create_subprocess_exec",
               AsyncMock(return_value=proc)):
        with pytest.raises(TranscriptionError):
            asyncio.run(
                transcribe(fake_audio, output_dir=out_dir, whisper_bin="/usr/bin/whisper")
            )


def test_transcribe_missing_json_raises(fake_audio: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    proc = _make_proc(0)
    # No JSON file written.
    with patch("runtime.transcription.asyncio.create_subprocess_exec",
               AsyncMock(return_value=proc)):
        with pytest.raises(TranscriptionError):
            asyncio.run(
                transcribe(fake_audio, output_dir=out_dir, whisper_bin="/usr/bin/whisper")
            )


def test_artifact_to_dict_roundtrip(fake_audio: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    raw = {
        "text": "ok",
        "language": "en",
        "segments": [{"id": 0, "start": 0.0, "end": 0.5, "text": "ok"}],
    }
    (out_dir / f"{fake_audio.stem}.json").write_text(json.dumps(raw))
    proc = _make_proc(0)
    with patch("runtime.transcription.asyncio.create_subprocess_exec",
               AsyncMock(return_value=proc)):
        artifact = asyncio.run(
            transcribe(fake_audio, output_dir=out_dir, whisper_bin="/usr/bin/whisper")
        )

    d = artifact.to_dict()
    assert d["text"] == "ok"
    assert d["segments"] == [{"id": 0, "start": 0.0, "end": 0.5, "text": "ok"}]
    assert d["model"] == artifact.model
