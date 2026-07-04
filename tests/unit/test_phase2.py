import os
import json
import sqlite3
import pytest
import pathlib
import sys

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.ingestion import ingest_transcript, get_recent_transcripts

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_transcripts.db"
    init_db(str(db_file))
    return str(db_file)

def test_p2_01_db_schema_initializes():
    """P2-01 · Database initializes with correct schema [UNIT]"""
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        cursor = conn.cursor()
        
        # Verify transcripts schema
        cursor.execute("PRAGMA table_info(transcripts)")
        columns = [row[1] for row in cursor.fetchall()]
        expected_transcripts = ["transcript_id", "user_id", "channel", "timestamp", "content"]
        assert all(col in columns for col in expected_transcripts)
        
        # Verify issue_log schema
        cursor.execute("PRAGMA table_info(issue_log)")
        columns_issue = [row[1] for row in cursor.fetchall()]
        expected_issue = ["id", "user_id", "issue_type", "timestamp"]
        assert all(col in columns_issue for col in expected_issue)
    finally:
        conn.close()

def test_p2_02_transcript_ingests_correctly(temp_db, tmp_path):
    """P2-02 · Transcript ingests correctly [UNIT]"""
    data = {
        "transcript_id": "test_id_001",
        "user_id": "rahul@acme.com",
        "channel": "email",
        "timestamp": "2024-06-12T10:30:00Z",
        "content": "Test content"
    }
    file_path = tmp_path / "test_ingest.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    ingest_transcript(str(file_path), db_path=temp_db)
    
    conn = sqlite3.connect(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transcripts WHERE transcript_id = ?", ("test_id_001",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "test_id_001"
        assert row[1] == "user_123"  # rahul@acme.com resolves to user_123
        assert row[2] == "email"
        assert row[3] == "2024-06-12T10:30:00Z"
        assert row[4] == "Test content"
    finally:
        conn.close()

def test_p2_03_duplicate_ingest_skipped(temp_db, tmp_path):
    """P2-03 · Duplicate ingest is silently skipped [UNIT]"""
    data = {
        "transcript_id": "test_id_001",
        "user_id": "rahul@acme.com",
        "channel": "email",
        "timestamp": "2024-06-12T10:30:00Z",
        "content": "Test content"
    }
    file_path = tmp_path / "test_ingest.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    ingest_transcript(str(file_path), db_path=temp_db)
    ingest_transcript(str(file_path), db_path=temp_db)
    
    conn = sqlite3.connect(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transcripts WHERE transcript_id = ?", ("test_id_001",))
        count = cursor.fetchone()[0]
        assert count == 1
    finally:
        conn.close()

def test_p2_04_malformed_json_skips(temp_db, tmp_path):
    """P2-04 · Malformed JSON skips file, does not crash [UNIT]"""
    file_path = tmp_path / "malformed.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write('{ "transcript_id": "x", INVALID JSON }')
        
    ingest_transcript(str(file_path), db_path=temp_db)
    
    conn = sqlite3.connect(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transcripts")
        count = cursor.fetchone()[0]
        assert count == 0
    finally:
        conn.close()

def test_p2_05_get_recent_transcripts_limit_order(temp_db):
    """P2-05 · get_recent_transcripts returns correct limit and order [UNIT]"""
    conn = sqlite3.connect(temp_db)
    try:
        cursor = conn.cursor()
        for i in range(1, 6):
            cursor.execute(
                "INSERT INTO transcripts (transcript_id, user_id, channel, timestamp, content) VALUES (?, ?, ?, ?, ?)",
                (f"tr_{i}", "user_123", "email", f"2024-06-12T10:0{i}:00Z", f"Content {i}")
            )
        conn.commit()
    finally:
        conn.close()
        
    result = get_recent_transcripts("user_123", limit=3, db_path=temp_db)
    assert len(result) == 3
    assert result[0]["transcript_id"] == "tr_5"
    assert result[1]["transcript_id"] == "tr_4"
    assert result[2]["transcript_id"] == "tr_3"
    assert result[0]["timestamp"] > result[1]["timestamp"] > result[2]["timestamp"]

def test_p2_06_demo_transcripts_ingest():
    """P2-06 · All four demo transcript files ingest without errors [UNIT]"""
    raw_dir = pathlib.Path(config.DATA_RAW_DIR)
    files = [
        "email_user123_20240612.json",
        "phone_user123_20240614.json",
        "chat_user123_20240615.json",
        "chat_user123_20240620.json"
    ]
    
    for f in files:
        filepath = raw_dir / f
        ingest_transcript(str(filepath), db_path=config.DB_PATH)
        
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transcripts WHERE user_id = 'user_123'")
        count = cursor.fetchone()[0]
        assert count == 4
    finally:
        conn.close()
