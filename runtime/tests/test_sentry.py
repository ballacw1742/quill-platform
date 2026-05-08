"""Runtime sentry wrapper sanity tests."""

from __future__ import annotations

from runtime.notifications import sentry as sentry_svc


def test_init_no_dsn_idempotent(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN_RUNTIME", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert sentry_svc.init(force=True) is False
    assert sentry_svc.init(force=True) is False


def test_tag_helpers_no_raise():
    sentry_svc.tag_agent("rfi-triage")
    sentry_svc.tag_approval("ap-1")
    sentry_svc.tag_run("run-1")
    # None values must be accepted silently
    sentry_svc.tag_agent(None)
    sentry_svc.tag_approval(None)
    sentry_svc.tag_run(None)


def test_capture_helpers_no_dsn_return_none_or_str():
    eid = sentry_svc.capture_message("hello", level="info", agent_id="x")
    assert eid is None or isinstance(eid, str)
    try:
        raise ValueError("bang")
    except ValueError as e:
        eid2 = sentry_svc.capture_exception(e, agent_id="x")
    assert eid2 is None or isinstance(eid2, str)


def test_scrubber_redacts_pii():
    event = {
        "extra": {"input": "secret rfi text", "agent_id": "rfi-triage"},
        "breadcrumbs": {
            "values": [
                {"data": {"prompt": "long prompt", "ok": True}},
            ]
        },
    }
    out = sentry_svc._scrub(event, {})
    assert out is not None
    assert out["extra"]["input"] == "<redacted>"
    assert out["extra"]["agent_id"] == "rfi-triage"
    assert out["breadcrumbs"]["values"][0]["data"]["prompt"] == "<redacted>"
