"""Tests for the classifier: retry predicate, input handling, parse path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from ticket_router.classifier import TicketClassifier, _is_retryable_vertex
from ticket_router.config import get_settings


def test_retry_predicate_retries_server_error():
    exc = genai_errors.ServerError.__new__(genai_errors.ServerError)
    assert _is_retryable_vertex(exc) is True


def test_retry_predicate_retries_timeout():
    assert _is_retryable_vertex(TimeoutError()) is True


def test_retry_predicate_skips_client_error():
    exc = genai_errors.ClientError.__new__(genai_errors.ClientError)
    exc.code = 400
    assert _is_retryable_vertex(exc) is False


def test_retry_predicate_retries_rate_limit():
    exc = genai_errors.ClientError.__new__(genai_errors.ClientError)
    exc.code = 429
    assert _is_retryable_vertex(exc) is True


def _classifier():
    with patch("ticket_router.classifier.genai.Client", return_value=MagicMock()):
        return TicketClassifier(get_settings())


@pytest.mark.asyncio
async def test_analyze_rejects_empty_text():
    clf = _classifier()
    with pytest.raises(ValueError):
        await clf.analyze("   ")


@pytest.mark.asyncio
async def test_call_model_returns_parsed(sample_analysis):
    clf = _classifier()
    resp = MagicMock()
    resp.parsed = sample_analysis
    clf._client.aio.models.generate_content = AsyncMock(return_value=resp)

    out = await clf.analyze("my laptop won't boot")
    assert out is sample_analysis


@pytest.mark.asyncio
async def test_call_model_raises_on_unparseable(sample_analysis):
    clf = _classifier()
    resp = MagicMock()
    resp.parsed = None
    resp.text = "not json"
    clf._client.aio.models.generate_content = AsyncMock(return_value=resp)

    with pytest.raises(ValueError):
        await clf.analyze("something")
