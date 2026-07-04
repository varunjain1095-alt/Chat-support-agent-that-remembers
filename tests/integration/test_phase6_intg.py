import os
import sqlite3
import pytest
import pathlib
import sys
from mem0 import MemoryClient
from zep_cloud.client import Zep

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.write_classifier import classify_and_save

def clean_mem0_and_zep(user_id, session_id):
    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    try:
        mem0.delete_all(user_id=user_id)
    except Exception:
        pass
        
    zep = Zep(api_key=config.ZEP_API_KEY)
    try:
        zep.thread.delete(thread_id=session_id)
    except Exception:
        pass
    try:
        zep.user.delete(user_id=user_id)
    except Exception:
        pass

@pytest.fixture
def temp_db_p6(tmp_path):
    db_file = tmp_path / "test_write_classifier.db"
    init_db(str(db_file))
    return str(db_file)

@pytest.fixture(autouse=True)
def cleanup_memories():
    user_id = "eval_user_p6"
    session_id = "eval_session_p6"
    clean_mem0_and_zep(user_id, session_id)
    yield
    clean_mem0_and_zep(user_id, session_id)

def get_issue_log_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM issue_log")
        return cursor.fetchone()[0]
    finally:
        conn.close()

def test_p6_01_intg_preference_routes_to_mem0(temp_db_p6):
    """P6-01 [INTG] — Explicit preference turn routes to Mem0 and does not write to Issue Log."""
    turn = [
        {"role": "user", "content": "Please always walk me through things step by step"},
        {"role": "assistant", "content": "Sure, we will take it step-by-step."}
    ]
    
    assert get_issue_log_count(temp_db_p6) == 0
    res = classify_and_save("eval_user_p6", "eval_session_p6", turn, db_path=temp_db_p6)
    
    assert res == "mem0"
    assert get_issue_log_count(temp_db_p6) == 0


def test_p6_02_intg_state_routes_to_zep_and_issue_log(temp_db_p6):
    """P6-02 [INTG] — State/issue turn routes to Zep, writes to Issue Log, and skips duplicate log writes."""
    turn = [
        {"role": "user", "content": "I'm still seeing rate limiting errors even after upgrading to Pro"},
        {"role": "assistant", "content": "Let me look into the 429 rate limit issue."}
    ]
    
    assert get_issue_log_count(temp_db_p6) == 0
    
    # Run 1: Should save to Zep and write to Issue Log
    res = classify_and_save("eval_user_p6", "eval_session_p6", turn, db_path=temp_db_p6)
    assert res == "zep"
    assert get_issue_log_count(temp_db_p6) == 1
    
    # Verify the issue_type is present and relevant
    conn = sqlite3.connect(temp_db_p6)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, issue_type FROM issue_log")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "eval_user_p6"
        assert "rate" in row[1].lower()
    finally:
        conn.close()

    # Run 2: Same turn again. Zep save continues, but duplicate SQLite write should be skipped
    res2 = classify_and_save("eval_user_p6", "eval_session_p6", turn, db_path=temp_db_p6)
    assert res2 == "zep"
    assert get_issue_log_count(temp_db_p6) == 1  # count remains 1 (prevented duplication)


def test_p6_03_intg_no_info_discard(temp_db_p6):
    """P6-03 [INTG] — A turn with polite acknowledgment but no new information is discarded."""
    turn = [
        {"role": "user", "content": "Okay, thank you so much for this help"},
        {"role": "assistant", "content": "You are welcome! Let me know if you need anything else."}
    ]
    
    res = classify_and_save("eval_user_p6", "eval_session_p6", turn, db_path=temp_db_p6)
    assert res == "discarded"
    assert get_issue_log_count(temp_db_p6) == 0


def test_p6_04_intg_grounding_check_fails_discard(temp_db_p6):
    """P6-04 [INTG] — Turn requesting broad help contains no explicit facts/preferences, so it is discarded."""
    turn = [
        {"role": "user", "content": "Can you help me?"},
        {"role": "assistant", "content": "How can I assist you today?"}
    ]
    
    res = classify_and_save("eval_user_p6", "eval_session_p6", turn, db_path=temp_db_p6)
    assert res == "discarded"
    assert get_issue_log_count(temp_db_p6) == 0
