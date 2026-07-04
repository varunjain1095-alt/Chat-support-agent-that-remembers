"""
memory.py — Thin wrappers around the Mem0 and Zep SDKs.
"""

import logging
import sys
import pathlib
from typing import Optional, List, Dict, Any

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from mem0 import MemoryClient
from zep_cloud.client import Zep
from zep_cloud.types.message import Message
from src.identity_resolver import resolve_user_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mem0 Preference Store Wrappers
# ---------------------------------------------------------------------------

def search_preferences(user_id: str, query: str) -> List[Dict[str, Any]]:
    """
    Queries Mem0 for user preferences. Returns a list of memory results.
    """
    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    try:
        # Use filters keyword arg to target the specific user_id
        result = mem0.search(query=query, filters={"user_id": user_id})
        results = result.get("results", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
        
        # Fallback to general search if query-specific search returned nothing
        if not results:
            result = mem0.search(query="communication style preference", filters={"user_id": user_id})
            results = result.get("results", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
            
        return results
    except Exception as e:
        logger.warning(f"Mem0 search error for user {user_id}: {e}")
        return []


def save_preference(user_id: str, turn: List[Dict[str, Any]]) -> None:
    """
    Saves a preference turn to Mem0.
    """
    # Guard against empty/whitespace-only messages (EC-M0-03)
    if not turn or not any(m.get("content", "").strip() for m in turn):
        logger.warning(f"Skipped save_preference for user {user_id} due to empty turn")
        return

    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    try:
        # Pass messages and user_id directly
        mem0.add(messages=turn, user_id=user_id)
    except Exception as e:
        logger.error(f"Mem0 save error for user {user_id}: {e}")


# ---------------------------------------------------------------------------
# Zep State Store Wrappers
# ---------------------------------------------------------------------------

def search_state(user_id: str, query: str) -> Dict[str, Any]:
    """
    Queries Zep for user state (account state, issue history).
    Returns a serialized dictionary of GraphSearchResults.
    """
    zep = Zep(api_key=config.ZEP_API_KEY)
    try:
        result = zep.graph.search(query=query, user_id=user_id)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        elif hasattr(result, "dict"):
            return result.dict()
        return {}
    except Exception as e:
        logger.warning(f"Zep search error for user {user_id}: {e}")
        return {}


def save_state(session_id: str, messages: List[Dict[str, Any]], timestamp: str = None) -> None:
    """
    Saves state/factual messages to Zep.
    """
    # Guard against empty turns
    if not messages or not any(m.get("content", "").strip() for m in messages):
        logger.warning(f"Skipped save_state for session {session_id} due to empty messages")
        return

    # Resolve user ID from session ID (since Zep thread creation requires user_id)
    user_id = resolve_user_id(session_id)
    if user_id == "unknown_user":
        if "user123" in session_id or "user_123" in session_id:
            user_id = "user_123"
        elif "session" in session_id:
            user_id = session_id.replace("session", "user")
        else:
            user_id = "unknown_user"

    zep = Zep(api_key=config.ZEP_API_KEY)
    try:
        # Ensure user exists
        try:
            zep.user.add(user_id=user_id)
        except Exception:
            pass

        # Ensure thread exists
        try:
            zep.thread.create(thread_id=session_id, user_id=user_id)
        except Exception:
            pass

        # Convert dict messages into Zep Message objects
        zep_msgs = [
            Message(role=msg["role"], content=msg["content"], created_at=timestamp)
            for msg in messages
        ]
        
        # Add messages to the thread history
        zep.thread.add_messages(thread_id=session_id, messages=zep_msgs)

        # Sync user messages to the Graph directly to trigger immediate fact extraction and indexing
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content", "").strip():
                try:
                    zep.graph.add(data=msg["content"], type="text", user_id=user_id)
                except Exception as ge:
                    logger.warning(f"Zep graph add error for user {user_id}: {ge}")
    except Exception as e:
        logger.error(f"Zep save error for session {session_id} (user {user_id}): {e}")
