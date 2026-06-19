"""Tests for PII redaction."""

from ticket_router.redaction import redact


def test_redacts_email():
    assert "[EMAIL]" in redact("reach me at jane.doe@example.gov please")
    assert "jane.doe@example.gov" not in redact("jane.doe@example.gov")


def test_redacts_ssn():
    assert redact("my ssn is 123-45-6789") == "my ssn is [SSN]"


def test_redacts_phone():
    out = redact("call (405) 555-1234 today")
    assert "[PHONE]" in out
    assert "555-1234" not in out


def test_leaves_clean_text_untouched():
    text = "the printer on the third floor is jammed again"
    assert redact(text) == text
