"""Tests for ServiceNow field building and incident parsing (no network)."""

from unittest.mock import AsyncMock

import pytest

from ticket_router import routing
from ticket_router.config import get_settings
from ticket_router.routing import RouteDecision
from ticket_router.servicenow import ServiceNowClient


@pytest.fixture
def client():
    return ServiceNowClient(get_settings())


def _decision(group="grp1", auto=True):
    return RouteDecision(
        assignment_group=group, impact="2", urgency="1", auto_routed=auto, reason="ok"
    )


def test_suggest_mode_only_writes_a_work_note(client, sample_analysis):
    fields = client._build_fields(sample_analysis, _decision(), "suggest", None, None)
    assert "work_notes" in fields
    # Suggest mode must not touch assignment or priority.
    assert "assignment_group" not in fields
    assert "impact" not in fields
    assert "urgency" not in fields


def test_enforce_mode_sets_assignment_and_priority(client, sample_analysis):
    fields = client._build_fields(sample_analysis, _decision(), "enforce", None, None)
    assert fields["assignment_group"] == "grp1"
    assert fields["impact"] == "2"
    assert fields["urgency"] == "1"
    assert fields["category"] == sample_analysis.category.value


def test_fallback_with_no_analysis_always_assigns(client):
    # Even in suggest mode, a None analysis (classification failed) must assign.
    fields = client._build_fields(
        None, _decision(group=routing.TRIAGE_GROUP_SYS_ID), "suggest", None, None
    )
    assert fields["assignment_group"] == routing.TRIAGE_GROUP_SYS_ID
    assert "classification failed" in fields["work_notes"]


@pytest.mark.asyncio
async def test_get_incident_parses_reference_field(client):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "result": {
                    "sys_id": "SN1",
                    "number": "INC1",
                    "assignment_group": {"link": "x", "value": "grpSysId"},
                }
            }

    client._client.get = AsyncMock(return_value=FakeResp())
    out = await client.get_incident("SN1")
    assert out["already_assigned"] is True
    assert out["number"] == "INC1"


@pytest.mark.asyncio
async def test_get_incident_handles_empty_assignment(client):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"sys_id": "SN2", "number": "INC2", "assignment_group": ""}}

    client._client.get = AsyncMock(return_value=FakeResp())
    out = await client.get_incident("SN2")
    assert out["already_assigned"] is False


@pytest.mark.asyncio
async def test_create_incident_posts_and_returns_ids(client, sample_analysis):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"sys_id": "SNc", "number": "INCc"}}

    client._client.post = AsyncMock(return_value=FakeResp())
    out = await client.create_incident(
        sample_analysis, _decision(), description="laptop dead", mode="enforce"
    )
    assert out == {"sys_id": "SNc", "number": "INCc"}
    client._client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_incident_patches_and_returns_ids(client, sample_analysis):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"sys_id": "SNu", "number": "INCu"}}

    client._client.patch = AsyncMock(return_value=FakeResp())
    out = await client.update_incident("SNu", sample_analysis, _decision(), mode="suggest")
    assert out == {"sys_id": "SNu", "number": "INCu"}
    client._client.patch.assert_awaited_once()


def test_is_transient_predicate():
    import httpx

    from ticket_router.servicenow import _is_transient

    assert _is_transient(httpx.ConnectError("boom")) is True
    req = httpx.Request("GET", "http://x")
    err5xx = httpx.HTTPStatusError("e", request=req, response=httpx.Response(503, request=req))
    err4xx = httpx.HTTPStatusError("e", request=req, response=httpx.Response(404, request=req))
    assert _is_transient(err5xx) is True
    assert _is_transient(err4xx) is False
    assert _is_transient(ValueError("nope")) is False


# --- Retry wrapper exercised across a real retry via a mocked transport ---


@pytest.mark.asyncio
async def test_send_retries_on_503_then_succeeds(sample_analysis):
    import httpx

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(201, json={"result": {"sys_id": "SN7", "number": "INC7"}})

    settings = get_settings()
    settings.servicenow_max_retries = 3
    sn = ServiceNowClient(settings)
    sn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    out = await sn.create_incident(sample_analysis, _decision(), description="x")
    assert out["sys_id"] == "SN7"
    assert calls["n"] == 2  # retried once then succeeded


@pytest.mark.asyncio
async def test_send_does_not_retry_on_400(sample_analysis):
    import httpx

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad"})

    settings = get_settings()
    settings.servicenow_max_retries = 3
    sn = ServiceNowClient(settings)
    sn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await sn.create_incident(sample_analysis, _decision(), description="x")
    assert calls["n"] == 1  # 4xx not retried
