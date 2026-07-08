"""Phase D — channel adapters + pairing flow (contract: CHANNELS.md).

Covers: pairing lifecycle (code→link→revoke), webhook signature verify
(good/bad), identity→tenant resolution + cross-tenant isolation,
unconfigured-platform 503, budget/rate-limit enforcement on channel turns,
malformed-update resilience, and approval-in-chat deep-link surfacing.

sqlite baseline (no network): the model provider is faked and the outbound
HTTP send client is mocked (base.set_send_client).
"""

import uuid

import httpx
import pytest

import app.orchestrator as orch_mod
from app.api import app
from app.channels import base as channels_base
from app.channels import links as links_mod
from app.channels.base import InboundMessage
from app.config import get_settings
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT = "smoke-chan-a"
TENANT_B = "smoke-chan-b"


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def patch_provider(monkeypatch):
    def _patch(responses):
        provider = FakeProvider(responses)
        monkeypatch.setattr(orch_mod, "get_provider", lambda *a, **k: provider)
        return provider

    return _patch


class _MockSend:
    """Records outbound send calls; no network."""

    def __init__(self):
        self.calls = []

    async def post(self, url, *, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})

        class _R:
            status_code = 200

        return _R()


@pytest.fixture
def channels_on(monkeypatch):
    """Enable the feature + telegram + googlechat config; mock send client."""
    monkeypatch.setenv("CHANNELS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "tg-secret")
    monkeypatch.setenv("GOOGLECHAT_VERIFICATION_TOKEN", "gc-token")
    get_settings.cache_clear()
    mock = _MockSend()
    channels_base.set_send_client(lambda: mock)
    yield mock
    channels_base.set_send_client(None)
    get_settings.cache_clear()


# --- pairing lifecycle ------------------------------------------------------


async def test_pair_creates_pending_code(channels_on):
    res = await links_mod.create_pairing(
        tenant_id=TENANT, agent_id="personal", platform="telegram"
    )
    assert res["status"] == "pending"
    assert res["platform"] == "telegram"
    assert res["agent_id"] == "personal"
    assert res["pairing_code"]
    assert "expires_at" in res
    assert "instructions" in res


async def test_pair_unknown_agent_raises(channels_on):
    with pytest.raises(orch_mod.UnknownAgentError):
        await links_mod.create_pairing(
            tenant_id=TENANT, agent_id="ghost", platform="telegram"
        )


async def test_pair_bad_platform_raises(channels_on):
    with pytest.raises(links_mod.ChannelValidationError):
        await links_mod.create_pairing(
            tenant_id=TENANT, agent_id="personal", platform="sms"
        )


async def test_bind_redeems_code_and_links(channels_on, patch_provider):
    res = await links_mod.create_pairing(
        tenant_id=TENANT, agent_id="personal", platform="telegram"
    )
    code = res["pairing_code"]
    msg = InboundMessage(
        platform="telegram",
        platform_chat_id="chat-1",
        platform_user_id="u-1",
        display_name="Charles",
        text=f"/start {code}",
    )
    bound = await links_mod.bind_link(platform="telegram", code=code, msg=msg)
    assert bound is not None
    assert bound["status"] == "linked"
    assert bound["platform_chat_id"] == "chat-1"
    # code is now consumed — second bind fails
    again = await links_mod.bind_link(platform="telegram", code=code, msg=msg)
    assert again is None
    # channel.linked event emitted
    from app import events as events_mod

    types = [e["type"] for e in events_mod.get_bus().published]
    assert "channel.linked" in types


async def test_bind_invalid_code_returns_none(channels_on):
    msg = InboundMessage("telegram", "chat-x", "u", "n", "NOPE")
    assert await links_mod.bind_link(platform="telegram", code="NOPE", msg=msg) is None


async def test_bind_expired_code_returns_none(channels_on, monkeypatch):
    monkeypatch.setenv("CHANNELS_PAIRING_TTL_SECONDS", "0")
    get_settings.cache_clear()
    res = await links_mod.create_pairing(
        tenant_id=TENANT, agent_id="personal", platform="telegram"
    )
    code = res["pairing_code"]
    msg = InboundMessage("telegram", "chat-2", "u", "n", code)
    # TTL 0 → already expired
    assert await links_mod.bind_link(platform="telegram", code=code, msg=msg) is None


async def test_list_and_revoke(channels_on):
    res = await links_mod.create_pairing(
        tenant_id=TENANT, agent_id="personal", platform="telegram"
    )
    listing = await links_mod.list_links(TENANT)
    assert listing["total"] >= 1
    link_id = uuid.UUID(res["link_id"])
    revoked = await links_mod.revoke_link(TENANT, link_id)
    assert revoked["status"] == "revoked"
    # cross-tenant revoke → not found
    with pytest.raises(links_mod.ChannelNotFoundError):
        await links_mod.revoke_link(TENANT_B, link_id)


# --- resolution + cross-tenant isolation ------------------------------------


async def _link_chat(tenant, chat_id, agent="personal"):
    res = await links_mod.create_pairing(
        tenant_id=tenant, agent_id=agent, platform="telegram"
    )
    code = res["pairing_code"]
    msg = InboundMessage("telegram", chat_id, "u", "n", code)
    return await links_mod.bind_link(platform="telegram", code=code, msg=msg)


async def test_resolve_returns_live_link(channels_on):
    await _link_chat(TENANT, "chat-r")
    link = await links_mod.resolve_link("telegram", "chat-r")
    assert link is not None
    assert link.tenant_id == TENANT
    assert link.status == "linked"


async def test_resolve_unlinked_chat_is_none(channels_on):
    assert await links_mod.resolve_link("telegram", "no-such-chat") is None


async def test_cross_tenant_chat_isolation(channels_on):
    """Two tenants each link their own chat; resolution routes correctly."""
    await _link_chat(TENANT, "chat-A")
    await _link_chat(TENANT_B, "chat-B")
    la = await links_mod.resolve_link("telegram", "chat-A")
    lb = await links_mod.resolve_link("telegram", "chat-B")
    assert la.tenant_id == TENANT
    assert lb.tenant_id == TENANT_B
    # each tenant only sees its own link in list
    assert (await links_mod.list_links(TENANT))["total"] == 1
    assert (await links_mod.list_links(TENANT_B))["total"] == 1


# --- inbound turn (reuses orchestrator) -------------------------------------


async def test_inbound_unlinked_gives_onboarding(channels_on):
    msg = InboundMessage("telegram", "fresh-chat", "u", "n", "hello there")
    reply = await links_mod.handle_inbound("telegram", msg)
    assert "pairing code" in reply.lower()


async def test_inbound_linked_runs_turn(channels_on, patch_provider):
    await _link_chat(TENANT, "chat-turn")
    patch_provider([text_response("hi from the agent")])
    msg = InboundMessage("telegram", "chat-turn", "u", "n", "what's up")
    reply = await links_mod.handle_inbound("telegram", msg)
    assert reply == "hi from the agent"
    # channel.message event emitted (no content)
    from app import events as events_mod

    evs = [e for e in events_mod.get_bus().published if e["type"] == "channel.message"]
    assert evs and "text" not in evs[0]["payload"]
    assert evs[0]["payload"]["chars"] == len("what's up")


async def test_inbound_persists_link_session(channels_on, patch_provider):
    await _link_chat(TENANT, "chat-sess")
    patch_provider([text_response("first"), text_response("second")])
    msg1 = InboundMessage("telegram", "chat-sess", "u", "n", "one")
    await links_mod.handle_inbound("telegram", msg1)
    link = await links_mod.resolve_link("telegram", "chat-sess")
    assert link.session_id is not None
    sid1 = link.session_id
    # second message reuses the same session
    msg2 = InboundMessage("telegram", "chat-sess", "u", "n", "two")
    await links_mod.handle_inbound("telegram", msg2)
    link2 = await links_mod.resolve_link("telegram", "chat-sess")
    assert link2.session_id == sid1


async def test_inbound_approval_gated_write_appends_deeplink(channels_on, patch_provider):
    """A turn that calls a write tool surfaces a web approval deep link."""
    # give the personal agent a write tool for this test
    from app import agents as agents_mod

    await agents_mod.update_agent(
        TENANT, "personal", {"tools": ["get_time", "quill_project_update"]}
    )
    await _link_chat(TENANT, "chat-appr")
    # model proposes a write, then (tool loop) returns a final text
    patch_provider(
        [
            tool_use_response("quill_project_update", {"project_id": "p1", "notes": "x"}),
            text_response("I've proposed the update."),
        ]
    )
    msg = InboundMessage("telegram", "chat-appr", "u", "n", "update project p1")
    reply = await links_mod.handle_inbound("telegram", msg)
    assert "/queue" in reply
    assert "approval" in reply.lower()


# --- rate limit on channel turns --------------------------------------------


async def test_inbound_rate_limited(channels_on, patch_provider, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    try:
        await _link_chat(TENANT, "chat-rl")
        patch_provider([text_response("ok1"), text_response("ok2")])
        m = InboundMessage("telegram", "chat-rl", "u", "n", "hi")
        r1 = await links_mod.handle_inbound("telegram", m)
        assert r1 == "ok1"
        r2 = await links_mod.handle_inbound("telegram", m)
        assert "too fast" in r2.lower()
    finally:
        get_settings.cache_clear()


# --- adapter verification (good/bad) ----------------------------------------


def test_telegram_verify(channels_on):
    from app.channels.telegram import ADAPTER

    assert ADAPTER.verify({"x-telegram-bot-api-secret-token": "tg-secret"}, {}) is True
    assert ADAPTER.verify({"x-telegram-bot-api-secret-token": "wrong"}, {}) is False
    assert ADAPTER.verify({}, {}) is False


def test_googlechat_verify(channels_on):
    from app.channels.googlechat import ADAPTER

    assert ADAPTER.verify({"authorization": "Bearer gc-token"}, {}) is True
    assert ADAPTER.verify({"authorization": "gc-token"}, {}) is True
    assert ADAPTER.verify({"authorization": "Bearer nope"}, {}) is False
    assert ADAPTER.verify({}, {}) is False


def test_telegram_parse(channels_on):
    from app.channels.telegram import ADAPTER

    body = {
        "message": {
            "text": "hello",
            "chat": {"id": 12345},
            "from": {"id": 999, "username": "charles"},
        }
    }
    m = ADAPTER.parse(body)
    assert m.platform_chat_id == "12345"
    assert m.platform_user_id == "999"
    assert m.display_name == "charles"
    assert m.text == "hello"
    # non-message update → None
    assert ADAPTER.parse({"channel_post": {}}) is None
    assert ADAPTER.parse({"message": {"chat": {"id": 1}}}) is None  # no text


def test_googlechat_parse_strips_mention(channels_on):
    from app.channels.googlechat import ADAPTER

    body = {
        "type": "MESSAGE",
        "message": {"text": "@QuillAgent hello world"},
        "space": {"name": "spaces/AAAA"},
        "user": {"name": "users/1", "displayName": "Charles"},
    }
    m = ADAPTER.parse(body)
    assert m.platform_chat_id == "spaces/AAAA"
    assert m.text == "hello world"
    assert ADAPTER.parse({"type": "ADDED_TO_SPACE"}) is None


# --- webhook endpoints (HTTP) -----------------------------------------------


async def test_telegram_webhook_bad_secret_403(channels_on, client):
    async with client:
        r = await client.post(
            "/v1/channels/telegram/webhook",
            json={"message": {"text": "hi", "chat": {"id": 1}, "from": {"id": 2}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert r.status_code == 403


async def test_telegram_webhook_good_secret_200(channels_on, client, patch_provider):
    await _link_chat(TENANT, "77")
    patch_provider([text_response("bot reply")])
    async with client:
        r = await client.post(
            "/v1/channels/telegram/webhook",
            json={
                "message": {"text": "hi", "chat": {"id": 77}, "from": {"id": 2}}
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # the out-of-band send was invoked with the reply
    assert channels_on.calls
    assert channels_on.calls[-1]["json"]["text"] == "bot reply"


async def test_googlechat_webhook_sync_reply(channels_on, client, patch_provider):
    # link the space
    res = await links_mod.create_pairing(
        tenant_id=TENANT, agent_id="personal", platform="googlechat"
    )
    code = res["pairing_code"]
    await links_mod.bind_link(
        platform="googlechat",
        code=code,
        msg=InboundMessage("googlechat", "spaces/Z", "users/1", "C", code),
    )
    patch_provider([text_response("chat reply")])
    async with client:
        r = await client.post(
            "/v1/channels/googlechat/webhook",
            json={
                "type": "MESSAGE",
                "message": {"text": "hello"},
                "space": {"name": "spaces/Z"},
                "user": {"name": "users/1", "displayName": "C"},
            },
            headers={"Authorization": "Bearer gc-token"},
        )
    assert r.status_code == 200
    assert r.json()["text"] == "chat reply"


async def test_webhook_malformed_body_acked_not_5xx(channels_on, client):
    async with client:
        r = await client.post(
            "/v1/channels/telegram/webhook",
            content=b"not json",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": "tg-secret",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_webhook_unhandled_update_ignored(channels_on, client):
    async with client:
        r = await client.post(
            "/v1/channels/telegram/webhook",
            json={"my_chat_member": {"foo": "bar"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
        )
    assert r.status_code == 200
    assert "ignored" in r.json()


# --- unconfigured / disabled platform → 503 ---------------------------------


async def test_webhook_feature_disabled_503(client, monkeypatch):
    monkeypatch.setenv("CHANNELS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        async with client:
            r = await client.post(
                "/v1/channels/telegram/webhook",
                json={"message": {"text": "x", "chat": {"id": 1}}},
            )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_webhook_platform_unconfigured_503(client, monkeypatch):
    monkeypatch.setenv("CHANNELS_ENABLED", "true")
    # bot token unset → telegram adapter not configured
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        async with client:
            r = await client.post(
                "/v1/channels/telegram/webhook",
                json={"message": {"text": "x", "chat": {"id": 1}}},
            )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_pair_endpoint_disabled_503(client, monkeypatch):
    monkeypatch.setenv("CHANNELS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        async with client:
            r = await client.post(
                "/v1/agents/channels/pair",
                json={"tenant_id": TENANT, "agent_id": "personal", "platform": "telegram"},
            )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_pair_list_revoke_endpoints(channels_on, client):
    async with client:
        r = await client.post(
            "/v1/agents/channels/pair",
            json={"tenant_id": TENANT, "agent_id": "personal", "platform": "telegram"},
        )
        assert r.status_code == 201
        link_id = r.json()["link_id"]
        lst = await client.get("/v1/agents/channels", params={"tenant_id": TENANT})
        assert lst.status_code == 200
        assert lst.json()["total"] >= 1
        rev = await client.post(
            f"/v1/agents/channels/{link_id}/revoke", params={"tenant_id": TENANT}
        )
        assert rev.status_code == 200
        assert rev.json()["status"] == "revoked"


async def test_channels_route_not_shadowed_by_agent_id(channels_on, client):
    """`/v1/agents/channels` must not be captured by `/v1/agents/{agent_id}`."""
    async with client:
        r = await client.get("/v1/agents/channels", params={"tenant_id": TENANT})
    assert r.status_code == 200
    assert "items" in r.json()
