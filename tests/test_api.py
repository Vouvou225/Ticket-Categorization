"""API tests. The classifier is mocked so no real Vertex call is made."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from ticket_router.routing import RouteDecision
from ticket_router.service import RoutingOutcome


@pytest.fixture
def client(sample_analysis):
    from ticket_router.main import app, get_service

    decision = RouteDecision(
        assignment_group="grp1",
        impact="2",
        urgency="1",
        auto_routed=True,
        reason="ok",
    )
    outcome = RoutingOutcome(
        analysis=sample_analysis,
        decision=decision,
        servicenow_sys_id="SN1",
        servicenow_number="INC1",
        mode="enforce",
    )

    service = MagicMock()
    service.process = AsyncMock(return_value=outcome)

    app.dependency_overrides[get_service] = lambda: service
    # Provide app.state pieces the health endpoints read.
    from ticket_router.config import get_settings

    app.state.settings = get_settings()
    app.state.service = service

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_route_endpoint(client):
    r = client.post("/route", json={"text": "my laptop won't turn on"})
    assert r.status_code == 200
    body = r.json()
    assert body["auto_routed"] is True
    assert body["servicenow_sys_id"] == "SN1"
    assert body["analysis"]["category"] == "hardwares"
    assert body["mode"] == "enforce"


def test_route_rejects_empty_text(client):
    r = client.post("/route", json={"text": ""})
    assert r.status_code == 422  # schema validation rejects empty string


def test_webhook_requires_sys_id(client):
    r = client.post("/sn/webhook", json={"description": "broken thing"})
    assert r.status_code == 400


def test_webhook_success(client):
    r = client.post("/sn/webhook", json={"sys_id": "SN1", "description": "printer down"})
    assert r.status_code == 200
    body = r.json()
    assert body["sys_id"] == "SN1"
    assert body["category"] == "hardwares"


def test_webhook_rejects_blank_text(client):
    r = client.post("/sn/webhook", json={"sys_id": "SN1", "description": "   "})
    assert r.status_code == 400


def test_unhandled_error_returns_500(sample_analysis):
    from ticket_router.config import get_settings
    from ticket_router.main import app, get_service

    service = MagicMock()
    service.process = AsyncMock(side_effect=RuntimeError("kaboom"))
    app.dependency_overrides[get_service] = lambda: service
    app.state.settings = get_settings()
    app.state.service = service

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/route", json={"text": "anything"})
    app.dependency_overrides.clear()

    assert r.status_code == 500
    assert "request_id" in r.json()
