"""Sprint-4 fix #6: trust-tier alias normalization.

Every string we have ever seen in `agentic-pmo-prompts/agents/*/system.md`
must map to a stable API ApiTier value. Unknown strings collapse to
the strictest tier so we never silently weaken the gate.
"""

from __future__ import annotations

import pytest

from runtime.lane_router import ApiTier, normalize_trust_tier


_KNOWN_ALIASES = {
    # Canonical (idempotent)
    "tier-0-mandatory": "tier-0-mandatory",
    "tier-1-spotcheck": "tier-1-spotcheck",
    "tier-2-auto": "tier-2-auto",
    # Long-form prompt-repo aliases
    "tier-2-charles-approves": "tier-1-spotcheck",
    # Short forms
    "tier-0": "tier-0-mandatory",
    "tier-1": "tier-1-spotcheck",
    "tier-2": "tier-2-auto",
    # Typos / underscore variants
    "tier_0_mandatory": "tier-0-mandatory",
    "tier_2_charles_approves": "tier-1-spotcheck",
    "TIER-0-MANDATORY": "tier-0-mandatory",  # case-insensitive
    "  tier-0-mandatory  ": "tier-0-mandatory",  # whitespace
    # Synonyms
    "mandatory": "tier-0-mandatory",
    "spotcheck": "tier-1-spotcheck",
    "spot-check": "tier-1-spotcheck",
    "auto": "tier-2-auto",
    "automatic": "tier-2-auto",
    "charles-approves": "tier-1-spotcheck",
}


@pytest.mark.parametrize("alias,expected", list(_KNOWN_ALIASES.items()))
def test_known_alias_normalizes(alias: str, expected: ApiTier) -> None:
    assert normalize_trust_tier(alias) == expected


def test_empty_falls_back_to_strictest() -> None:
    assert normalize_trust_tier(None) == "tier-0-mandatory"
    assert normalize_trust_tier("") == "tier-0-mandatory"


def test_unknown_falls_back_to_strictest() -> None:
    assert normalize_trust_tier("nonsense-tier") == "tier-0-mandatory"
    assert normalize_trust_tier("tier-99-overlord") == "tier-0-mandatory"


def test_explicit_default_overrides() -> None:
    # Caller can opt into a less-strict default for a non-prod context
    assert (
        normalize_trust_tier("nonsense", default="tier-2-auto") == "tier-2-auto"
    )


def test_real_prompt_repo_tier_strings_all_recognized():
    """Every trust_tier_default we have seen in the wild MUST be known."""
    seen_in_repo = [
        "tier-0-mandatory",  # coordinator, rfi-triage, rfi-drafter, ...
        "tier-2-charles-approves",  # daily-brief, procurement-watch
    ]
    for s in seen_in_repo:
        result = normalize_trust_tier(s)
        # Anything that maps to "strictest fallback" probably means the
        # alias table is incomplete \u2014 fail loudly so we catch it.
        assert result in {"tier-0-mandatory", "tier-1-spotcheck", "tier-2-auto"}
        # The alias table must NOT collapse a known prompt-repo tier into
        # the conservative default unless that's literally tier-0-mandatory.
        if s != "tier-0-mandatory":
            assert result != "tier-0-mandatory", (
                f"alias {s!r} fell through to the strictest default \u2014 update _PROMPT_TIER_ALIASES"
            )
