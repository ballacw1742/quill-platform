"""sha256 helpers with canonical JSON encoding."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_canonical(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj)).hexdigest()


def hash_input(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def hash_output(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def hash_prompt(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


__all__ = ["hash_input", "hash_output", "hash_prompt", "sha256_canonical"]
