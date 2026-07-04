"""
session.py — Session lifecycle: creation, activity tracking, close, and expiry.
"""

import uuid
import sqlite3
import logging
import pathlib
import sys

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config

logger = logging.getLogger(__name__)

def create_session(user_id: str, db_path=config.DB_PATH) -> str:
    """
    Generates a unique session_id, registers it as active, and returns it.
    """
    session_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (session_id, user_id, status) VALUES (?, ?, 'active')",
            (session_id, user_id)
        )
        conn.commit()
        logger.info(f"Session created: {session_id} for user {user_id}")
        return session_id
    except Exception as e:
        logger.error(f"Failed to create session in DB: {e}")
        raise
    finally:
        conn.close()


def get_active_session(user_id: str, db_path=config.DB_PATH) -> str | None:
    """
    Returns the session_id of the active session for user_id, or None.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id FROM sessions WHERE user_id = ? AND status = 'active'",
            (user_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to query active session for user {user_id}: {e}")
        return None
    finally:
        conn.close()


def close_session(session_id: str, db_path=config.DB_PATH) -> None:
    """
    Updates the session status to 'closed'.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET status = 'closed', last_active = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
        logger.info(f"Session closed: {session_id}")
    except Exception as e:
        logger.error(f"Failed to close session {session_id}: {e}")
    finally:
        conn.close()


def record_activity(session_id: str, db_path=config.DB_PATH) -> None:
    """
    Updates the last_active timestamp of the session to current time.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to update activity for session {session_id}: {e}")
    finally:
        conn.close()


def expire_stale_sessions(inactivity_hours: int = 24, db_path=config.DB_PATH) -> int:
    """
    Finds active sessions with no activity in inactivity_hours and marks them 'expired'.
    Returns the count of expired sessions.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        modifier = f"-{inactivity_hours} hours"
        cursor.execute(
            """
            UPDATE sessions
            SET status = 'expired'
            WHERE status = 'active' AND last_active < datetime('now', ?)
            """,
            (modifier,)
        )
        conn.commit()
        expired_count = cursor.rowcount
        if expired_count > 0:
            logger.info(f"Expired {expired_count} stale sessions")
        return expired_count
    except Exception as e:
        logger.error(f"Failed to expire stale sessions: {e}")
        return 0
    finally:
        conn.close()
