"""
Lightweight PII redaction.

This is a government help desk, so ticket text can contain personal data. Two
places care about it: what we send to Vertex, and what we store in the BigQuery
audit excerpt. Both are controlled by settings (redact_pii, redact_in_audit).

This is pattern-based redaction, which catches the common, high-risk cases
(emails, phone numbers, SSNs, card-like numbers). It is not a substitute for a
full DLP product. If you need guaranteed coverage, route the text through Cloud
DLP and replace the function below; the call sites do not change.

Redaction never touches the real ServiceNow incident description. That is the
actual ticket and already lives in your system; we only redact copies that
leave it (the model prompt and the audit log).
"""

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (
        re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "[PHONE]",
    ),
    # 13-16 digit sequences with optional spaces/dashes, card-like. Starts and
    # ends on a digit so it never swallows a trailing separator.
    (re.compile(r"\b\d(?:[ -]?\d){12,15}\b"), "[CARD]"),
]


def redact(text: str) -> str:
    """Replace common PII patterns with typed placeholders."""
    for pattern, token in _PATTERNS:
        text = pattern.sub(token, text)
    return text
