"""Tests for the orchestration service with mocked dependencies."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ticket_router import routing
from ticket_router.config import get_settings
from ticket_router.service import RoutingService


def _settings(**overrides):
    s = get_settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _classifier(analysis):
    c = MagicMock()
    c.analyze = AsyncMock(return_value=analysis)
    return c


@pytest.mark.asyncio
async def test_enforce_mode_writes_assignment(sample_analysis, monkeypatch):
    monkeypatch.setitem(routing.ASSIGNMENT_GROUPS, sample_analysis.category, "realGroupSysId")
    settings = _settings(write_to_servicenow=True, routing_mode="enforce")

    sn = MagicMock()
    sn.create_incident = AsyncMock(return_value={"sys_id": "SN123", "number": "INC0012345"})

    service = RoutingService(settings, _classifier(sample_analysis), sn, MagicMock())
    outcome = await service.process(request_id="r1", text="laptop is dead")

    assert outcome.servicenow_sys_id == "SN123"
    assert outcome.decision.auto_routed is True
    # enforce mode passes mode through to the writer
    _, kwargs = sn.create_incident.call_args
    assert kwargs["mode"] == "enforce"


@pytest.mark.asyncio
async def test_suggest_mode_is_default_and_passed_through(sample_analysis, monkeypatch):
    monkeypatch.setitem(routing.ASSIGNMENT_GROUPS, sample_analysis.category, "realGroupSysId")
    settings = _settings(write_to_servicenow=True)  # default routing_mode == suggest

    sn = MagicMock()
    sn.create_incident = AsyncMock(return_value={"sys_id": "SN1", "number": "INC1"})

    service = RoutingService(settings, _classifier(sample_analysis), sn, MagicMock())
    outcome = await service.process(request_id="r1", text="laptop is dead")

    assert outcome.mode == "suggest"
    _, kwargs = sn.create_incident.call_args
    assert kwargs["mode"] == "suggest"


@pytest.mark.asyncio
async def test_skip_when_already_assigned(sample_analysis):
    settings = _settings(write_to_servicenow=True, skip_if_assigned=True)

    sn = MagicMock()
    sn.get_incident = AsyncMock(
        return_value={"sys_id": "SN9", "number": "INC9", "already_assigned": True}
    )
    sn.update_incident = AsyncMock()
    classifier = _classifier(sample_analysis)

    service = RoutingService(settings, classifier, sn, MagicMock())
    outcome = await service.process(request_id="r1", text="x", sys_id="SN9")

    assert outcome.skipped is True
    classifier.analyze.assert_not_awaited()  # never even classified
    sn.update_incident.assert_not_awaited()  # never wrote


@pytest.mark.asyncio
async def test_classification_failure_falls_back_to_triage(monkeypatch):
    settings = _settings(write_to_servicenow=True, routing_mode="suggest")

    classifier = MagicMock()
    classifier.analyze = AsyncMock(side_effect=RuntimeError("vertex exploded"))

    sn = MagicMock()
    sn.get_incident = AsyncMock(
        return_value={"sys_id": "SN5", "number": "INC5", "already_assigned": False}
    )
    sn.update_incident = AsyncMock(return_value={"sys_id": "SN5", "number": "INC5"})

    service = RoutingService(settings, classifier, sn, MagicMock())
    outcome = await service.process(request_id="r1", text="broken", sys_id="SN5")

    assert outcome.fallback is True
    assert outcome.analysis is None
    assert outcome.decision.assignment_group == routing.TRIAGE_GROUP_SYS_ID
    # fallback forces an enforce-style write so the ticket is not lost
    _, kwargs = sn.update_incident.call_args
    assert kwargs["mode"] == "enforce"


@pytest.mark.asyncio
async def test_redaction_applied_to_model_input(sample_analysis):
    settings = _settings(write_to_servicenow=False, redact_pii=True)
    classifier = _classifier(sample_analysis)

    service = RoutingService(settings, classifier, None, MagicMock())
    await service.process(request_id="r1", text="email me at jo@x.com about it")

    sent = classifier.analyze.call_args.args[0]
    assert "jo@x.com" not in sent
    assert "[EMAIL]" in sent


@pytest.mark.asyncio
async def test_servicenow_skipped_when_disabled(sample_analysis):
    settings = _settings(write_to_servicenow=False)
    service = RoutingService(settings, _classifier(sample_analysis), None, MagicMock())
    outcome = await service.process(request_id="r1", text="broken")
    assert outcome.servicenow_sys_id is None
