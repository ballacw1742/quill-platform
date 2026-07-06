"""Seed-parity checks for the agent registry.

Guards against fleet agents landing in the registry without display
metadata (the "weird slug names, no description" bug from 2026-07-06).
"""

from app.enums import AGENT_FLEET
from app.routes.agents import FLEET_METADATA, SEED_AGENTS


def test_fleet_metadata_covers_every_fleet_agent():
    missing = [slug for slug in AGENT_FLEET if slug not in FLEET_METADATA]
    assert not missing, f"Fleet agents missing display metadata: {missing}"


def test_fleet_metadata_fields_are_complete():
    for slug, meta in FLEET_METADATA.items():
        assert meta.get("display_name"), f"{slug}: empty display_name"
        assert meta.get("description"), f"{slug}: empty description"
        assert meta.get("role_summary"), f"{slug}: empty role_summary"
        # Written-out names, not slugs: no hyphenated lowercase slugs allowed.
        assert meta["display_name"] != slug, f"{slug}: display_name is the raw slug"
        assert meta["display_name"][0].isupper(), f"{slug}: display_name not capitalized"


def test_no_stale_metadata_for_unknown_slugs():
    stale = [slug for slug in FLEET_METADATA if slug not in AGENT_FLEET]
    assert not stale, f"FLEET_METADATA has entries not in AGENT_FLEET: {stale}"


def test_adk_seed_agents_have_metadata():
    for data in SEED_AGENTS:
        assert data.get("display_name"), f"{data['agent_id']}: empty display_name"
        assert data.get("description"), f"{data['agent_id']}: empty description"
