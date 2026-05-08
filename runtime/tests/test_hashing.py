from __future__ import annotations

from runtime.hashing import hash_input, hash_output, hash_prompt, sha256_canonical


def test_input_hash_insertion_order_independent():
    a = {"x": 1, "y": [1, 2, {"k": "v"}]}
    b = {"y": [1, 2, {"k": "v"}], "x": 1}
    assert hash_input(a) == hash_input(b)


def test_distinct_inputs_distinct_hashes():
    assert hash_input({"x": 1}) != hash_input({"x": 2})


def test_output_hash_matches_input_hash_function():
    payload = {"k": 1}
    assert hash_output(payload) == hash_input(payload)


def test_prompt_hash_stable():
    h1 = hash_prompt("hello world")
    h2 = hash_prompt("hello world")
    h3 = hash_prompt("hello world!")
    assert h1 == h2
    assert h1 != h3


def test_canonical_hash_unicode():
    a = {"name": "café"}
    b = {"name": "caf\u00e9"}
    assert sha256_canonical(a) == sha256_canonical(b)
