import os
import sqlite3
import pytest
import pathlib
import sys

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.session import (
    create_session,
    get_active_session,
    close_session,
    record_activity,
    expire_stale_sessions
)
from src.ingestion import get_recent_transcripts

@pytest.fixture
def temp_db_p8(tmp_path):
    db_file = tmp_path / "test_sessions.db"
    init_db(str(db_file))
    return str(db_file)

def test_p8_01_create_session(temp_db_p8):
    """P8-01 [UNIT] — A new session is created with 'active' status."""
    session_id = create_session("user_123", db_path=temp_db_p8)
    
    assert session_id is not None
    assert "user_123" in session_id
    
    # Query database directly
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, status FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "user_123"
        assert row[1] == "active"
    finally:
        conn.close()

def test_p8_02_close_session(temp_db_p8):
    """P8-02 [UNIT] — close_session() updates status to 'closed'."""
    session_id = create_session("user_123", db_path=temp_db_p8)
    assert get_active_session("user_123", db_path=temp_db_p8) == session_id
    
    close_session(session_id, db_path=temp_db_p8)
    
    # Active session query should return None
    assert get_active_session("user_123", db_path=temp_db_p8) is None
    
    # Check DB status is closed
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        assert cursor.fetchone()[0] == "closed"
    finally:
        conn.close()

def test_p8_03_expire_stale_sessions(temp_db_p8):
    """P8-03 [UNIT] — expire_stale_sessions() marks sessions with inactivity > 24h as expired."""
    session_id = create_session("user_123", db_path=temp_db_p8)
    
    # Manually backdate the last_active to 25 hours ago
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET last_active = datetime('now', '-25 hours') WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
    finally:
        conn.close()
        
    # Expire stale
    expired_count = expire_stale_sessions(inactivity_hours=24, db_path=temp_db_p8)
    assert expired_count == 1
    
    # Verify status is expired
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        assert cursor.fetchone()[0] == "expired"
    finally:
        conn.close()

def test_p8_04_recent_session_not_expired(temp_db_p8):
    """P8-04 [UNIT] — Recent sessions with inactivity < 24h are not expired."""
    session_id = create_session("user_123", db_path=temp_db_p8)
    
    # Manually backdate last_active to 1 hour ago
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET last_active = datetime('now', '-1 hour') WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
    finally:
        conn.close()
        
    expired_count = expire_stale_sessions(inactivity_hours=24, db_path=temp_db_p8)
    assert expired_count == 0
    
    # Verify status remains active
    assert get_active_session("user_123", db_path=temp_db_p8) == session_id

def test_p8_05_exclude_active_session_transcripts(temp_db_p8):
    """P8-05 [UNIT] — get_recent_transcripts() excludes active session transcripts by default."""
    # 1. Create sessions
    s1_active = create_session("user_123", db_path=temp_db_p8)
    s2_closed = create_session("user_123", db_path=temp_db_p8)
    s3_closed = create_session("user_123", db_path=temp_db_p8)
    
    close_session(s2_closed, db_path=temp_db_p8)
    close_session(s3_closed, db_path=temp_db_p8)
    
    # 2. Insert corresponding transcripts
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?)",
            ("tr_1", "user_123", "chat", "2026-07-04T12:00:00Z", "active session chat text", s1_active)
        )
        cursor.execute(
            "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?)",
            ("tr_2", "user_123", "chat", "2026-07-04T11:00:00Z", "closed session chat text 1", s2_closed)
        )
        cursor.execute(
            "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?)",
            ("tr_3", "user_123", "chat", "2026-07-04T10:00:00Z", "closed session chat text 2", s3_closed)
        )
        conn.commit()
    finally:
        conn.close()
        
    # Query with default exclude_active=True
    res = get_recent_transcripts("user_123", limit=3, db_path=temp_db_p8, exclude_active=True)
    
    assert len(res) == 2
    transcript_ids = [t["transcript_id"] for t in res]
    assert "tr_2" in transcript_ids
    assert "tr_3" in transcript_ids
    assert "tr_1" not in transcript_ids  # Excluded active session transcript

def test_p8_06_include_active_session_transcripts(temp_db_p8):
    """P8-06 [UNIT] — get_recent_transcripts(exclude_active=False) includes active session transcripts."""
    s1_active = create_session("user_123", db_path=temp_db_p8)
    s2_closed = create_session("user_123", db_path=temp_db_p8)
    close_session(s2_closed, db_path=temp_db_p8)
    
    conn = sqlite3.connect(temp_db_p8)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?)",
            ("tr_1", "user_123", "chat", "2026-07-04T12:00:00Z", "active chat content", s1_active)
        )
        cursor.execute(
            "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?)",
            ("tr_2", "user_123", "chat", "2026-07-04T11:00:00Z", "closed chat content", s2_closed)
        )
        conn.commit()
    finally:
        conn.close()
        
    # Query with exclude_active=False
    res = get_recent_transcripts("user_123", limit=3, db_path=temp_db_p8, exclude_active=False)
    
    assert len(res) == 2
    transcript_ids = [t["transcript_id"] for t in res]
    assert "tr_1" in transcript_ids
    assert "tr_2" in transcript_ids
