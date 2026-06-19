"""Test the dashboard simulate endpoint with a mocked classifier.

The app lifespan builds real GCP clients, so these tests deliberately do not run
it (no `with TestClient(...)` block) and set app.state.classifier directly.
"""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


def test_simulate_returns_classification(sample_analysis):
    from ticket_router.dashboard import app

    classifier = MagicMock()
    classifier.analyze = AsyncMock(return_value=sample_analysis)
    app.state.classifier = classifier

    client = TestClient(app)  # no context manager, so lifespan does not run
    r = client.post("/api/simulate", json={"text": "my laptop will not boot"})

    assert r.status_code == 200
    body = r.json()
    assert body["category"] == sample_analysis.category.value
    assert body["priority"] == sample_analysis.priority.value
    assert "tags" in body


def test_simulate_rejects_empty_text(sample_analysis):
    from ticket_router.dashboard import app

    classifier = MagicMock()
    classifier.analyze = AsyncMock(return_value=sample_analysis)
    app.state.classifier = classifier

    client = TestClient(app)
    r = client.post("/api/simulate", json={"text": "   "})

    assert r.status_code == 200
    assert "error" in r.json()


def test_index_serves_html():
    from ticket_router.dashboard import app

    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "AI triage console" in r.text
