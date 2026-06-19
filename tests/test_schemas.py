"""Tests for the Pydantic schemas."""

import pytest
from pydantic import ValidationError

from ticket_router.routing import ETA, Category, Priority
from ticket_router.schemas import RouteRequest, TicketAnalysis


def test_analysis_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        TicketAnalysis(
            category=Category.APPLICATION,
            confidence=1.5,
            tags=["x"],
            priority=Priority.LOW,
            eta=ETA.H24,
            draft_response="ok",
        )


def test_analysis_rejects_unknown_category():
    with pytest.raises(ValidationError):
        TicketAnalysis(
            category="Made up category",
            confidence=0.5,
            tags=["x"],
            priority=Priority.LOW,
            eta=ETA.H24,
            draft_response="ok",
        )


def test_route_request_rejects_empty_text():
    with pytest.raises(ValidationError):
        RouteRequest(text="")
