from __future__ import annotations

import pytest

from runtime.json_extractor import JSONExtractionError, extract_json


def test_extract_fenced():
    text = 'preamble\n```json\n{"a": 1, "b": [1,2,3]}\n```\ntrailer'
    assert extract_json(text) == {"a": 1, "b": [1, 2, 3]}


def test_extract_fenced_no_lang_label():
    text = '```\n{"x": "y"}\n```'
    assert extract_json(text) == {"x": "y"}


def test_extract_bare_json():
    text = '   {"hello": "world"}   '
    assert extract_json(text) == {"hello": "world"}


def test_extract_brace_scan():
    text = "Sure! Here's the JSON: {\"a\": 1} ; thanks!"
    assert extract_json(text) == {"a": 1}


def test_extract_first_fence_wins():
    text = (
        "ignore me ```json\n{\"first\": true}\n```"
        " then ```json\n{\"second\": true}\n```"
    )
    assert extract_json(text) == {"first": True}


def test_empty_raises():
    with pytest.raises(JSONExtractionError):
        extract_json("")


def test_malformed_fence_raises():
    text = "```json\n{not json}\n```"
    with pytest.raises(JSONExtractionError):
        extract_json(text)


def test_array_top_level_raises():
    text = '```json\n[1,2,3]\n```'
    with pytest.raises(JSONExtractionError):
        extract_json(text)
