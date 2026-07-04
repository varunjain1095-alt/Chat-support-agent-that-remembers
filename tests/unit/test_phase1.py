import logging
import pytest
from src.identity_resolver import resolve_user_id

def test_p1_01_known_email_resolves():
    """P1-01 · Known email resolves correctly [UNIT]"""
    result = resolve_user_id("rahul@acme.com")
    assert result == "user_123"


def test_p1_02_known_phone_resolves():
    """P1-02 · Known phone resolves correctly [UNIT]"""
    result = resolve_user_id("+91-9876543210")
    assert result == "user_123"


def test_p1_03_known_session_resolves():
    """P1-03 · Known session token resolves correctly [UNIT]"""
    result = resolve_user_id("sess_abc_789")
    assert result == "user_123"


def test_p1_04_unknown_identifier_fallback():
    """P1-04 · Unknown identifier returns fallback [UNIT]"""
    result = resolve_user_id("unknown@random.com")
    assert result == "unknown_user"


def test_p1_05_empty_identifier_fallback():
    """P1-05 · Empty identifier returns fallback, does not crash [UNIT]"""
    assert resolve_user_id("") == "unknown_user"
    assert resolve_user_id(None) == "unknown_user"


def test_p1_06_resolution_event_logged(caplog):
    """P1-06 · Resolution event is logged [UNIT]"""
    with caplog.at_level(logging.INFO):
        resolve_user_id("rahul@acme.com")
        assert any("Identity resolved: rahul@acme.com → user_123" in record.message for record in caplog.records)
