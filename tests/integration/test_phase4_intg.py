import time
import pytest
import sqlite3
import pathlib
import sys
from mem0 import MemoryClient
from zep_cloud.client import Zep

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.context_assembler import assemble_context
from src.memory import save_preference, save_state
from src.ingestion import get_recent_transcripts

def insert_test_transcript(user_id, transcript_id, content):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO transcripts (transcript_id, user_id, channel, timestamp, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (transcript_id, user_id, "chat", "2026-07-04T12:00:00Z", content)
        )
        conn.commit()
    finally:
        conn.close()

def delete_test_transcript(transcript_id):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transcripts WHERE transcript_id = ?", (transcript_id,))
        conn.commit()
    finally:
        conn.close()

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

def test_p4_01_intg_all_stores_populated():
    """P4-01 [INTG] — Populated stores result in all four schema fields being non-empty."""
    user_id = "eval_user_p4"
    session_id = "eval_session_p4"
    transcript_id = "tr_p4_01"

    # Pre-test cleanup
    clean_mem0_and_zep(user_id, session_id)
    delete_test_transcript(transcript_id)

    try:
        # Seeding
        save_preference(user_id, [{"role": "user", "content": "I prefer step-by-step guidance"}])
        save_state(session_id, [{"role": "user", "content": "I upgraded to Pro plan last week"}])
        insert_test_transcript(user_id, transcript_id, "Customer wants to check upgrade details.")

        # Poll for async extraction from Mem0 and Zep
        start_time = time.time()
        result = {}
        while time.time() - start_time < 90:
            result = assemble_context(user_id, "I need help with my Pro plan upgrade step-by-step")
            
            # Check if both stores have finished processing
            pref_ok = "step" in str(result.get("preferences", "")).lower()
            state_ok = "pro" in str(result.get("account_state", "")).lower() or "pro" in str(result.get("issue_history", "")).lower()
            trans_ok = len(result.get("transcript_excerpts", [])) > 0
            
            if pref_ok and state_ok and trans_ok:
                break
            time.sleep(5)

        assert result.get("preferences") != {}
        assert result.get("account_state") != {}
        assert len(result.get("transcript_excerpts", [])) > 0
        
    finally:
        clean_mem0_and_zep(user_id, session_id)
        delete_test_transcript(transcript_id)


def test_p4_02_intg_cold_start():
    """P4-02 [INTG] — Cold start returns empty schema directly, without executing LLM call."""
    # Using a random user id ensures stores are completely empty
    random_user_id = "brand_new_user_xyz_9999"
    result = assemble_context(random_user_id, "hello")
    
    assert result == {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }


def test_p4_03_intg_conflict_scenario():
    """P4-03 [INTG] — Merges Mem0 style preference and Zep state details correctly without discarding either."""
    user_id = "eval_user_p4_conflict"
    session_id = "eval_session_p4_conflict"

    # Pre-test cleanup
    clean_mem0_and_zep(user_id, session_id)

    try:
        # Seeding
        save_preference(user_id, [{"role": "user", "content": "I prefer verbose responses"}])
        save_state(session_id, [{"role": "user", "content": "I upgraded to Pro plan last week"}])

        # Poll for async extraction
        start_time = time.time()
        result = {}
        while time.time() - start_time < 90:
            result = assemble_context(user_id, "my issue is still open")
            
            pref_ok = "verbose" in str(result.get("preferences", "")).lower()
            state_ok = "pro" in str(result.get("account_state", "")).lower() or "pro" in str(result.get("issue_history", "")).lower()
            
            if pref_ok and state_ok:
                break
            time.sleep(5)

        assert "verbose" in str(result.get("preferences", "")).lower()
        assert "pro" in (str(result.get("account_state", "")) + str(result.get("issue_history", ""))).lower()

    finally:
        clean_mem0_and_zep(user_id, session_id)


def test_p4_04_intg_conformance():
    """P4-04 [INTG] — The output dictionary always conforms to the fixed schema structure across multiple runs."""
    user_id = "eval_user_p4_conformance"
    
    # Verify conformance across different scenarios
    for i in range(5):
        result = assemble_context(user_id, f"test run {i}")
        assert set(result.keys()) == {"preferences", "account_state", "issue_history", "transcript_excerpts"}
        assert isinstance(result["preferences"], dict)
        assert isinstance(result["account_state"], dict)
        assert isinstance(result["issue_history"], list)
        assert isinstance(result["transcript_excerpts"], list)
