"""Tests for the shared-secret endpoint guard."""

import pytest
from fastapi import HTTPException

from ticket_router.config import get_settings
from ticket_router.security import verify_token


def test_rejects_wrong_token():
    get_settings().webhook_token = "secret"
    with pytest.raises(HTTPException) as exc:
        verify_token("wrong")
    assert exc.value.status_code == 401


def test_rejects_missing_token_when_required():
    get_settings().webhook_token = "secret"
    with pytest.raises(HTTPException):
        verify_token(None)


def test_accepts_correct_token():
    get_settings().webhook_token = "secret"
    verify_token("secret")  # no exception


def test_allows_all_when_no_token_configured():
    get_settings().webhook_token = ""
    verify_token(None)  # development convenience, no exception
