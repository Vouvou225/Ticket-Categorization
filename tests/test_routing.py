"""Tests for the routing decision logic."""

from ticket_router import routing
from ticket_router.routing import Category, Priority, decide_route


def test_low_confidence_goes_to_triage():
    d = decide_route(Category.APPLICATION, Priority.MEDIUM, 0.40)
    assert d.auto_routed is False
    assert d.assignment_group == routing.TRIAGE_GROUP_SYS_ID
    assert "below threshold" in d.reason


def test_placeholder_group_falls_through_to_triage():
    # With unconfigured placeholder sys_ids, even a confident ticket is held.
    d = decide_route(Category.HARDWARE, Priority.HIGH, 0.95)
    assert d.auto_routed is False
    assert "no assignment group configured" in d.reason


def test_configured_group_auto_routes(monkeypatch):
    monkeypatch.setitem(routing.ASSIGNMENT_GROUPS, Category.HARDWARE, "abc123realSysId")
    d = decide_route(Category.HARDWARE, Priority.HIGH, 0.95)
    assert d.auto_routed is True
    assert d.assignment_group == "abc123realSysId"


def test_priority_maps_to_impact_and_urgency():
    d = decide_route(Category.APPLICATION, Priority.HIGH, 0.30)
    assert d.impact == routing.PRIORITY_MAP[Priority.HIGH]["impact"]
    assert d.urgency == routing.PRIORITY_MAP[Priority.HIGH]["urgency"]
