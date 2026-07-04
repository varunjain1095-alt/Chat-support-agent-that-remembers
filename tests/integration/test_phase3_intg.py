import time
import pytest
import config
from src.memory import save_preference, search_preferences, save_state, search_state

def test_p3_01_mem0_roundtrip():
    """P3-01 · Mem0 preference save → search round-trip [INTG]"""
    user_id = "eval_user_p3"
    
    # Pre-test cleanup
    from mem0 import MemoryClient
    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    try:
        mem0.delete_all(user_id=user_id)
    except Exception:
        pass
        
    try:
        # Save preference
        save_preference(user_id, [{"role": "user", "content": "I prefer step-by-step guidance"}])
        
        # Hosted Mem0 is asynchronous, poll for memory extraction
        start_time = time.time()
        result = []
        while time.time() - start_time < 30:
            result = search_preferences(user_id, "how do you like to be helped")
            if result and any("step" in str(r.get("memory", "")).lower() for r in result):
                break
            time.sleep(2)
            
        assert len(result) >= 1
        assert any("step" in str(r.get("memory", "")).lower() for r in result)
        
    finally:
        # Cleanup
        try:
            mem0.delete_all(user_id=user_id)
        except Exception:
            pass

def test_p3_02_zep_roundtrip():
    """P3-02 · Zep state save → search round-trip [INTG]"""
    session_id = "eval_session_p3"
    user_id = "eval_user_p3"
    
    # Pre-test cleanup
    from zep_cloud.client import Zep
    zep = Zep(api_key=config.ZEP_API_KEY)
    try:
        zep.thread.delete(thread_id=session_id)
    except Exception:
        pass
    try:
        zep.user.delete(user_id=user_id)
    except Exception:
        pass
        
    try:
        # Save state
        save_state(session_id, [{"role": "user", "content": "I upgraded to Pro plan last week"}])
        
        # Hosted Zep is asynchronous for graph updates, poll for facts extraction (up to 120 seconds)
        start_time = time.time()
        result = {}
        while time.time() - start_time < 120:
            result = search_state(user_id, "what plan is this user on")
            result_str = str(result).lower()
            if "pro" in result_str:
                break
            time.sleep(5)
            
        # Verify result contains Pro
        result_str = str(result).lower()
        assert "pro" in result_str
        
    finally:
        # Cleanup
        try:
            zep.thread.delete(thread_id=session_id)
        except Exception:
            pass
        try:
            zep.user.delete(user_id=user_id)
        except Exception:
            pass
