import os
import sys
import json
import time
import pytest
import sqlite3
import pathlib
import datetime
from mem0 import MemoryClient
from zep_cloud.client import Zep
from zep_cloud.types import Message
from zep_cloud.errors import NotFoundError
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.write_classifier import classify_and_save
from src.context_assembler import assemble_context
from src.agent import generate_response
from src.ingestion import get_recent_transcripts
from src.session import create_session, expire_stale_sessions
from src.pattern_detector import detect_patterns
from src.memory import save_preference, save_state
from src.identity_resolver import _IDENTITY_MAP
import anthropic

def get_issue_log_count(db_path=config.DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM issue_log")
        return cursor.fetchone()[0]
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

# 1. Grounding check
def test_p12_01_grounding_check():
    """P12-01 · Grounding check: inferred fact -> discard [INTG]"""
    # Grounding check: inferred fact -> discard
    turn = [{"role": "user", "content": "Can you help?"}]
    result = classify_and_save("eval_user_p12_01", "sess_p12_01", turn)
    assert result == "discarded"

# 2. Conflict policy
def test_p12_02_conflict_policy():
    """P12-02 · Conflict policy — field-level merge with LLM-as-judge tone check [EVAL]"""
    user_id = "user_eval_p12_02"
    session_id = "sess_eval_p12_02"
    
    # Register in identity resolver _IDENTITY_MAP for save_state/resolve_user_id
    _IDENTITY_MAP[session_id] = user_id

    # Pre-test cleanup
    clean_mem0_and_zep(user_id, session_id)

    try:
        # Seed Mem0: "prefers verbose, detailed updates"
        save_preference(user_id, [{"role": "user", "content": "I prefer verbose, detailed updates"}])
        # Seed Zep: "account flagged for fast-path resolution"
        save_state(session_id, [{"role": "user", "content": "I am an enterprise priority customer, account flagged for fast-path resolution"}])

        # Poll for async extraction from Mem0 and Zep
        start_time = time.time()
        result = {}
        while time.time() - start_time < 90:
            # Bypass cache inside orchestrator by generating direct context assembly
            result = assemble_context(user_id, "my issue is still open")
            
            pref_ok = "verbose" in str(result.get("preferences", "")).lower()
            state_ok = "fast-path" in str(result.get("account_state", "")).lower() or "priority" in str(result.get("account_state", "")).lower()
            
            if pref_ok and state_ok:
                break
            time.sleep(5)

        # Assert Step 1 — Context object check
        assert "verbose" in str(result.get("preferences", "")).lower()
        assert "fast-path" in str(result.get("account_state", "")).lower() or "priority" in str(result.get("account_state", "")).lower()

        # Step 2 — Factual routing check
        # policy_chunks matching "Priority Customers" (fast-tracked/Priority)
        policy_chunks = [
            "Priority Customers: Enterprise tier customers should be fast-tracked to the next tier immediately without waiting."
        ]
        conversation_history = []
        response_text = generate_response("my issue is still open", result, policy_chunks, conversation_history)
        
        # Assert factional routing (priority/fast-track/expedited)
        assert any(keyword in response_text.lower() for keyword in ["fast-track", "fast-tracked", "priority", "expedited"])

        # Step 3 — Tone routing check (LLM-as-judge)
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        judge_prompt = f"""
        You are evaluating whether a support response matches a "verbose, detailed" communication style.
        Score the response on a scale of 1–5:
          1 = very terse / one or two words
          2 = brief / one sentence
          3 = moderate / two to three sentences
          4 = verbose / multi-sentence with explanation
          5 = very verbose / detailed multi-paragraph explanation
        Respond with JSON only: {{"score": <int>, "reason": "<one sentence>"}}
        
        Response to evaluate:
        {response_text}
        """
        judge_result = client.messages.create(
            model=config.CLAUDE_RESPONSE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": judge_prompt}]
        )
        judge_text = judge_result.content[0].text.strip()
        print(f"\n[LLM-as-judge raw response]: {judge_text}")
        
        import re
        match = re.search(r"\{.*\}", judge_text, re.DOTALL)
        if match:
            judge_data = json.loads(match.group(0))
        else:
            judge_data = json.loads(judge_text)
            
        score = judge_data["score"]
        reason = judge_data.get("reason", "No reason provided.")
        print(f"\n=== LLM-AS-JUDGE VERDICT ===")
        print(f"Score: {score}/5")
        print(f"Reason: {reason}")
        print(f"============================")
        
        assert score >= 3, f"Tone check failed: expected verbose style (score >= 3), got {score}. Reason: {reason}"

    finally:
        clean_mem0_and_zep(user_id, session_id)
        if session_id in _IDENTITY_MAP:
            del _IDENTITY_MAP[session_id]

# 3. Issue Log write scope
def test_p12_03_issue_log_write_scope():
    """P12-03 · Issue Log write scope invariant [INTG]"""
    db_path = config.DB_PATH
    initial_count = get_issue_log_count(db_path)

    # 1. Preference turn
    turn_pref = [{"role": "user", "content": "Please walk me through things step by step"}]
    result_pref = classify_and_save("eval_user_p12_03", "sess_pref", turn_pref, db_path=db_path)
    assert get_issue_log_count(db_path) == initial_count

    # 2. State/issue turn
    turn_state = [{"role": "user", "content": "I'm still hitting rate limits after upgrading"}]
    result_state = classify_and_save("eval_user_p12_03", "sess_state", turn_state, db_path=db_path)
    assert get_issue_log_count(db_path) == initial_count + 1
    
    # Verify new row details
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT issue_type FROM issue_log ORDER BY id DESC LIMIT 1")
        issue_type = cursor.fetchone()[0]
        assert issue_type and len(issue_type.strip()) > 0
    finally:
        conn.close()

    # 3. Discard turn
    current_count = get_issue_log_count(db_path)
    turn_discard = [{"role": "user", "content": "ok"}]
    result_discard = classify_and_save("eval_user_p12_03", "sess_discard", turn_discard, db_path=db_path)
    assert get_issue_log_count(db_path) == current_count

# 4. Session boundary
def test_p12_04_session_boundary():
    """P12-04 · Session boundary handling [UNIT]"""
    db_path = config.DB_PATH
    user_id = "eval_user_p12_04"
    
    # Clear transcripts/sessions for user
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transcripts WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    
    # 1. Seed a transcript for eval_user_p12_04 in transcripts table
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO transcripts (transcript_id, user_id, channel, timestamp, content, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("tr_expired", user_id, "chat", "2024-06-15T11:40:00Z", "Expired transcript", "sess_expired")
        )
        conn.commit()
    finally:
        conn.close()

    # 2. Insert session into sessions table with status active and 25 hours ago last_active
    session_id = "sess_expired"
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (session_id, user_id, status, created_at, last_active)
            VALUES (?, ?, ?, datetime('now', '-25 hours'), datetime('now', '-25 hours'))
            """,
            (session_id, user_id, "active")
        )
        conn.commit()
    finally:
        conn.close()

    # 3. Call expire_stale_sessions
    expire_stale_sessions(inactivity_hours=24, db_path=db_path)

    # Assert session status is now expired
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,))
        status = cursor.fetchone()[0]
        assert status == "expired"
    finally:
        conn.close()

    # 4. Seed an active session with transcripts that should be EXCLUDED
    active_session_id = "sess_active_now"
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (session_id, user_id, status, created_at, last_active)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            """,
            (active_session_id, user_id, "active")
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO transcripts (transcript_id, user_id, channel, timestamp, content, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("tr_active", user_id, "chat", datetime.datetime.utcnow().isoformat() + "Z", "Active transcript", active_session_id)
        )
        conn.commit()
    finally:
        conn.close()

    # 5. Call get_recent_transcripts
    transcripts = get_recent_transcripts(user_id, limit=3, db_path=db_path, exclude_active=True)
    
    # Assert tr_expired transcript is included
    transcript_ids = [t["transcript_id"] for t in transcripts]
    assert "tr_expired" in transcript_ids
    # Assert tr_active is NOT included
    assert "tr_active" not in transcript_ids

# 5. Cold-start
def test_p12_05_cold_start():
    """P12-05 · Cold-start [INTG]"""
    result = assemble_context("never_seen_user_abc_9999", "hello")
    assert isinstance(result, dict)
    assert result["preferences"] == {}
    assert result["account_state"] == {}
    assert result["issue_history"] == []
    assert result["transcript_excerpts"] == []

# 6. Cross-user pattern threshold
def test_p12_06_cross_user_pattern():
    """P12-06 · Cross-user pattern threshold [UNIT]"""
    db_path = config.DB_PATH
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Clean issue_log first
        cursor.execute("DELETE FROM issue_log")
        
        # Seed Above threshold: 10 rows, api_rate_limit, within 7 days, 5 distinct users
        users = ["user_a", "user_b", "user_c", "user_d", "user_e"]
        for u in users:
            cursor.execute(
                "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, datetime('now', '-2 hours'))",
                (u, "api_rate_limit")
            )
            cursor.execute(
                "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, datetime('now', '-3 hours'))",
                (u, "api_rate_limit")
            )
        conn.commit()
    finally:
        conn.close()

    # Call detect_patterns with threshold_count=5
    patterns = detect_patterns(threshold_count=5, window_days=7, db_path=db_path)
    issue_types = [p["issue_type"] for p in patterns]
    assert "api_rate_limit" in issue_types

    # Below threshold: if we increase threshold to 6, it should be empty
    patterns = detect_patterns(threshold_count=6, window_days=7, db_path=db_path)
    issue_types = [p["issue_type"] for p in patterns]
    assert "api_rate_limit" not in issue_types

    # Outside window: 4 distinct users in window + 6 users 8 days ago
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM issue_log")
        # Seed 4 distinct users in window
        for i in range(4):
            cursor.execute(
                "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, datetime('now', '-1 hours'))",
                (f"user_{i}", "api_rate_limit")
            )
        # Seed 6 logs dated 8 days ago
        for i in range(6):
            cursor.execute(
                "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, datetime('now', '-8 days'))",
                (f"user_old_{i}", "api_rate_limit")
            )
        conn.commit()
    finally:
        conn.close()

    # If threshold is 5, it should not match (since only 4 are within the last 7 days)
    patterns = detect_patterns(threshold_count=5, window_days=7, db_path=db_path)
    issue_types = [p["issue_type"] for p in patterns]
    assert "api_rate_limit" not in issue_types

    # Single-user inflation: 15 rows, same user_id, within 7 days.
    # If we set threshold to 5, it should not return anything because distinct user count is 1.
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM issue_log")
        for i in range(15):
            cursor.execute(
                "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, datetime('now', '-1 hours'))",
                ("single_user", "api_rate_limit")
            )
        conn.commit()
    finally:
        conn.close()

    patterns = detect_patterns(threshold_count=5, window_days=7, db_path=db_path)
    issue_types = [p["issue_type"] for p in patterns]
    assert "api_rate_limit" not in issue_types
