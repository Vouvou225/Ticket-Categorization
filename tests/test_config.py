"""Tests for configuration validation."""

import pytest

from ticket_router.config import get_settings


def test_production_requires_webhook_token():
    s = get_settings()
    s.environment = "production"
    s.webhook_token = ""
    with pytest.raises(RuntimeError) as exc:
        s.assert_production_ready()
    assert "WEBHOOK_TOKEN" in str(exc.value)


def test_production_passes_with_token():
    s = get_settings()
    s.environment = "production"
    s.webhook_token = "secret"
    s.write_to_servicenow = False
    s.assert_production_ready()  # no raise


def test_development_skips_the_check():
    s = get_settings()
    s.environment = "development"
    s.assert_production_ready()  # no raise even with empty token
