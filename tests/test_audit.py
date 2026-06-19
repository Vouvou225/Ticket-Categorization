"""Tests for the BigQuery audit logger using a fake client (no GCP)."""

from unittest.mock import MagicMock

from ticket_router.audit import AuditLogger
from ticket_router.config import get_settings
from ticket_router.routing import RouteDecision, triage_fallback


def _logger_with_fake_client():
    audit = AuditLogger(get_settings())  # audit disabled in tests, _client is None
    fake = MagicMock()
    fake.insert_rows_json.return_value = []  # no errors
    audit._client = fake
    return audit, fake


def test_records_full_row_for_successful_analysis(sample_analysis):
    audit, fake = _logger_with_fake_client()
    decision = RouteDecision("grp1", "2", "1", auto_routed=True, reason="ok")

    audit.record("r1", "printer jammed", sample_analysis, decision, "SN1", "INC1")

    _, rows = fake.insert_rows_json.call_args.args
    row = rows[0]
    assert row["category"] == sample_analysis.category.value
    assert row["confidence"] == sample_analysis.confidence
    assert row["servicenow_number"] == "INC1"


def test_records_fallback_row_with_null_fields():
    audit, fake = _logger_with_fake_client()
    decision = triage_fallback("classification error: boom")

    audit.record("r2", "garbled text", None, decision, "SN2", "INC2")

    row = fake.insert_rows_json.call_args.args[1][0]
    assert row["category"] is None
    assert row["confidence"] is None
    assert row["tags"] == []
    assert "classification error" in row["reason"]
