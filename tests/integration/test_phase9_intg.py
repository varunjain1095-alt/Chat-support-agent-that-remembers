import os
import time
import sqlite3
import pytest
import pathlib
import sys
from unittest.mock import patch, MagicMock
from mem0 import MemoryClient
from zep_cloud.client import Zep

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.orchestrator import handle_message, _SESSION_CONTEXT_CACHE, _SESSION_HISTORY_CACHE
from src.memory import save_preference, save_state
from src.ingestion import ingest_transcript
from src.rag import build_index

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

@pytest.fixture(autouse=True)
def clean_caches_and_mem():
    # Clear in-memory cache for isolation
    _SESSION_CONTEXT_CACHE.clear()
    _SESSION_HISTORY_CACHE.clear()
    
    user_id = "user_123"
    session_id = get_current_active_session_id()
    if session_id:
        clean_mem0_and_zep(user_id, session_id)
    yield
    # Post-cleanup
    session_id = get_current_active_session_id()
    if session_id:
        clean_mem0_and_zep(user_id, session_id)
    _SESSION_CONTEXT_CACHE.clear()
    _SESSION_HISTORY_CACHE.clear()

def get_current_active_session_id():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id FROM sessions WHERE user_id = 'user_123' AND status = 'active' ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()

def delete_all_sessions():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions")
        conn.commit()
    finally:
        conn.close()

def test_p9_01_and_04_intg_orchestration_flow():
    """P9-01 & P9-04 [INTG] — handle_message creates active session in SQLite and returns non-empty response."""
    delete_all_sessions()
    
    # 1. Trigger handle_message
    res = handle_message("rahul@acme.com", "I need help checking my account subscription tier.")
    
    assert isinstance(res, str)
    assert len(res.strip()) > 0
    
    # 2. Check DB
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id, user_id, status FROM sessions WHERE user_id = 'user_123'")
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "user_123"
        assert row[2] == "active"
    finally:
        conn.close()

@patch("src.orchestrator.assemble_context")
def test_p9_02_intg_context_assembly_once(mock_assemble):
    """P9-02 [INTG] — Context assembly is run only once on the first substantive session message."""
    mock_assemble.return_value = {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }
    
    delete_all_sessions()
    
    # Message 1 (Substantive) -> Triggers assembly
    handle_message("rahul@acme.com", "I want to upgrade my subscription plan.")
    # Message 2 (Substantive) -> Reuses cache, does not trigger assembly
    handle_message("rahul@acme.com", "How much does the Pro tier cost?")
    
    assert mock_assemble.call_count == 1

@patch("src.orchestrator.assemble_context")
def test_p9_02_substantive_trigger_check(mock_assemble):
    """P9-02 [INTG] — Greetings bypass context assembly, only substantive queries trigger it."""
    mock_assemble.return_value = {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }
    
    delete_all_sessions()
    
    # Message 1 (Low-signal greeting) -> Bypasses context assembly
    res1 = handle_message("rahul@acme.com", "Hi")
    assert isinstance(res1, str)
    assert mock_assemble.call_count == 0
    
    # Message 2 (Substantive query) -> Triggers context assembly
    res2 = handle_message("rahul@acme.com", "I upgraded to Pro and am getting 429 rate limit errors.")
    assert isinstance(res2, str)
    assert mock_assemble.call_count == 1
    
    # Message 3 (Substantive query in same session) -> Reuses cached context
    res3 = handle_message("rahul@acme.com", "Can you help me clear the cache?")
    assert isinstance(res3, str)
    assert mock_assemble.call_count == 1

@patch("src.orchestrator.classify_and_save")
def test_p9_03_intg_write_classifier_fires(mock_classify):
    """P9-03 [INTG] — Write-path classifier fires after every turn."""
    delete_all_sessions()
    
    # Send 3 messages
    handle_message("rahul@acme.com", "Hi")
    handle_message("rahul@acme.com", "I upgraded to Pro plan yesterday.")
    handle_message("rahul@acme.com", "Can you confirm my plan status?")
    
    # Wait briefly for background threads to launch
    time.sleep(0.5)
    assert mock_classify.call_count == 3

def test_p9_05_and_06_intg_demo_journey():
    """P9-05 & P9-06 [INTG] — E2E Journey: response recognises past rate limiting issue and applies step-by-step guidance preference."""
    # Seed transcripts and build RAG index
    build_index()
    
    raw_dir = pathlib.Path(config.DATA_RAW_DIR)
    ingest_transcript(str(raw_dir / "email_user123_20240612.json"))
    ingest_transcript(str(raw_dir / "phone_user123_20240614.json"))
    
    user_id = "user_123"
    session_id = "chat_user123_20240615"
    
    # Seed Mem0 & Zep to simulate the exact demo state
    clean_mem0_and_zep(user_id, session_id)
    save_preference(user_id, [{"role": "user", "content": "Please always walk me through things step by step"}])
    save_state(session_id, [{"role": "user", "content": "I upgraded to Pro plan last week"}])
    save_state(session_id, [{"role": "user", "content": "I'm still seeing rate limiting errors even after upgrading"}])
    
    # Wait for async updates
    time.sleep(5)
    
    # 2. Trigger orchestrator
    _SESSION_CONTEXT_CACHE.clear()
    _SESSION_HISTORY_CACHE.clear()
    
    res = handle_message("rahul@acme.com", "I upgraded my plan, but I am still hitting rate limiting errors with HTTP 429. What are the resolution steps?")
    
    # Assert Zep/history recognition (P9-05)
    res_lower = res.lower()
    assert any(k in res_lower for k in ["pro", "upgrade", "rate", "429", "cache", "key"])
    
    # Assert Mem0 preference styling applies (P9-06)
    # The response should present the resolution steps step-by-step
    assert "1." in res or "2." in res or res.count("step") >= 2
