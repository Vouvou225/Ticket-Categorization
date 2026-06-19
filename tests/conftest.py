"""Shared test fixtures."""

import os

import pytest

# Set required env before importing app modules so config validation passes.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("SERVICENOW_INSTANCE", "test")
os.environ.setdefault("SERVICENOW_USER", "test")
os.environ.setdefault("SERVICENOW_PASSWORD", "test")
os.environ.setdefault("AUDIT_ENABLED", "false")
os.environ.setdefault("WRITE_TO_SERVICENOW", "false")
os.environ.setdefault("ENVIRONMENT", "development")

from ticket_router.config import get_settings  # noqa: E402
from ticket_router.routing import ETA, Category, Priority  # noqa: E402
from ticket_router.schemas import TicketAnalysis  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_analysis() -> TicketAnalysis:
    return TicketAnalysis(
        category=Category.HARDWARE,
        confidence=0.91,
        tags=["laptop", "power", "boot"],
        priority=Priority.HIGH,
        eta=ETA.ASAP,
        draft_response="Sorry your laptop won't start. We've flagged this as urgent, ETA ASAP.",
    )
