"""CLI sanity tests."""

from __future__ import annotations

import os

from quill_bot.bot import _parse_argv, main


def test_parse_argv_default_run():
    assert _parse_argv([]) == {"cmd": "run"}
    assert _parse_argv(["run"]) == {"cmd": "run"}


def test_parse_argv_help():
    assert _parse_argv(["help"])["cmd"] == "help"
    assert _parse_argv(["-h"])["cmd"] == "help"


def test_parse_argv_version():
    assert _parse_argv(["version"])["cmd"] == "version"


def test_parse_argv_mint_pair():
    p = _parse_argv(["mint-pair", "--email", "charles@x.com"])
    assert p == {"cmd": "mint-pair", "email": "charles@x.com"}


def test_parse_argv_unknown():
    p = _parse_argv(["frobnicate"])
    assert p["cmd"] == "unknown"


def test_main_version(capsys):
    rc = main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "quill-bot" in out


def test_main_help(capsys):
    rc = main(["help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Subcommands" in out


def test_main_mint_pair_prints_code(capsys, monkeypatch):
    monkeypatch.setenv("TELEGRAM_PAIRING_SECRET", "test-pair-secret")
    rc = main(["mint-pair", "--email", "charles@example.com"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("Q1.charles@example.com.")
    # Q1, charles@example, com, <issued>, <sig> when email has 1 dot → 5 parts.
    parts = out.split(".")
    assert len(parts) >= 4
    # And the code roundtrips
    from quill_bot.pairing import verify_code
    parsed = verify_code(out, "test-pair-secret")
    assert parsed.email == "charles@example.com"


def test_main_mint_pair_requires_email(capsys):
    rc = main(["mint-pair"])
    assert rc == 2


def test_main_unknown_command(capsys):
    rc = main(["nosuch"])
    assert rc == 2
