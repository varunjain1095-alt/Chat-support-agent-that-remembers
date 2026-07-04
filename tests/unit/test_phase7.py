import os
import sqlite3
import pytest
import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.pattern_detector import detect_patterns

@pytest.fixture
def temp_db_p7(tmp_path):
    db_file = tmp_path / "test_pattern_detector.db"
    init_db(str(db_file))
    return str(db_file)

def insert_issue_entry(db_path, user_id, issue_type, timestamp_str):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, ?)",
            (user_id, issue_type, timestamp_str)
        )
        conn.commit()
    finally:
        conn.close()

def test_p7_01_above_threshold_detected(temp_db_p7):
    """P7-01 [UNIT] — Issue count above threshold (distinct users) is successfully detected."""
    # Seed 10 distinct users with 'api_rate_limit' within 7 days
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = (now - timedelta(days=i * 0.5)).strftime("%Y-%m-%d %H:%M:%S")
        insert_issue_entry(temp_db_p7, f"user_{i}", "api_rate_limit", ts)
        
    results = detect_patterns(threshold_count=10, window_days=7, db_path=temp_db_p7)
    
    assert len(results) == 1
    assert results[0]["issue_type"] == "api_rate_limit"
    assert results[0]["count"] == 10
    assert "window_start" in results[0]

def test_p7_02_below_threshold_ignored(temp_db_p7):
    """P7-02 [UNIT] — Issue count below threshold (distinct users) is ignored."""
    # Seed 9 distinct users with 'api_rate_limit'
    now = datetime.now(timezone.utc)
    for i in range(9):
        ts = (now - timedelta(days=i * 0.5)).strftime("%Y-%m-%d %H:%M:%S")
        insert_issue_entry(temp_db_p7, f"user_{i}", "api_rate_limit", ts)
        
    results = detect_patterns(threshold_count=10, window_days=7, db_path=temp_db_p7)
    
    assert len(results) == 0

def test_p7_03_out_of_window_excluded(temp_db_p7):
    """P7-03 [UNIT] — Issues outside the window are excluded from pattern counts."""
    # Seed 9 within window + 6 from 8 days ago (total 15 but only 9 active)
    now = datetime.now(timezone.utc)
    # 9 in-window (0 to 4 days ago)
    for i in range(9):
        ts = (now - timedelta(days=i * 0.4)).strftime("%Y-%m-%d %H:%M:%S")
        insert_issue_entry(temp_db_p7, f"user_{i}", "api_rate_limit", ts)
    # 6 out-of-window (8 to 11 days ago)
    for i in range(9, 15):
        ts = (now - timedelta(days=8 + (i - 9) * 0.5)).strftime("%Y-%m-%d %H:%M:%S")
        insert_issue_entry(temp_db_p7, f"user_{i}", "api_rate_limit", ts)
        
    results = detect_patterns(threshold_count=10, window_days=7, db_path=temp_db_p7)
    
    assert len(results) == 0

def test_p7_04_decoupled_from_orchestrator():
    """P7-04 [UNIT] — Detector is decoupled from orchestrator and never queried during a chat turn."""
    orchestrator_path = project_root / "src" / "orchestrator.py"
    if orchestrator_path.exists():
        with open(orchestrator_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "detect_patterns" not in content, "Error: detect_patterns is referenced in orchestrator.py"
    else:
        # If it doesn't exist yet, it's decoupled by default
        pass

def test_p7_05_single_user_inflation_avoided(temp_db_p7):
    """P12-06 [UNIT] — Single-user inflation is avoided using distinct user count (EC-PD-03)."""
    # Seed 15 entries for a single user 'user_power' within 7 days
    now = datetime.now(timezone.utc)
    for i in range(15):
        ts = (now - timedelta(hours=i * 2)).strftime("%Y-%m-%d %H:%M:%S")
        insert_issue_entry(temp_db_p7, "user_power", "api_rate_limit", ts)
        
    # The count of distinct users is 1, so threshold_count=5 should NOT be triggered
    results = detect_patterns(threshold_count=5, window_days=7, db_path=temp_db_p7)
    
    assert len(results) == 0
