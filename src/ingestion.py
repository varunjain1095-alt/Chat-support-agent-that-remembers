"""
ingestion.py — Transcript flat-file ingestion and SQLite querying.
"""

import json
import logging
import sqlite3
import pathlib
import sys

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.identity_resolver import resolve_user_id

logger = logging.getLogger(__name__)

def ingest_transcript(filepath: str, db_path=config.DB_PATH) -> None:
    """
    Reads a raw JSON transcript file, resolves the user ID using the identity resolver,
    and inserts it into the SQLite database. Duplicate ingestions are silently skipped.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Malformed JSON in {filepath}: {e}")
        return
    except Exception as e:
        logger.error(f"Error reading file {filepath}: {e}")
        return

    transcript_id = data.get("transcript_id")
    raw_user_id = data.get("user_id")
    channel = data.get("channel")
    timestamp = data.get("timestamp")
    content = data.get("content")
    
    # Resolve session_id: if absent and channel is chat, default to transcript_id
    session_id = data.get("session_id")
    if not session_id and channel == "chat":
        session_id = transcript_id

    # Resolve user ID via the identity resolver
    user_id = resolve_user_id(raw_user_id)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO transcripts (transcript_id, user_id, channel, timestamp, content, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (transcript_id, user_id, channel, timestamp, content, session_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Database error during ingestion of {filepath}: {e}")
    finally:
        conn.close()


def get_recent_transcripts(user_id: str, limit: int = 3, db_path=config.DB_PATH, exclude_active: bool = True) -> list[dict]:
    """
    Returns the last N transcript records for a given user, ordered by timestamp descending.
    If exclude_active is True, transcripts matching any active session are omitted.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        if exclude_active:
            cursor.execute(
                """
                SELECT transcripts.transcript_id, transcripts.user_id, transcripts.channel, transcripts.timestamp, transcripts.content, transcripts.session_id
                FROM transcripts
                LEFT JOIN sessions ON transcripts.session_id = sessions.session_id
                WHERE transcripts.user_id = ?
                  AND (sessions.status IS NULL OR sessions.status IN ('closed', 'expired'))
                ORDER BY transcripts.timestamp DESC
                LIMIT ?
                """,
                (user_id, limit)
            )
        else:
            cursor.execute(
                """
                SELECT transcripts.transcript_id, transcripts.user_id, transcripts.channel, transcripts.timestamp, transcripts.content, transcripts.session_id
                FROM transcripts
                WHERE transcripts.user_id = ?
                ORDER BY transcripts.timestamp DESC
                LIMIT ?
                """,
                (user_id, limit)
            )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error querying transcripts for user {user_id}: {e}")
        return []
    finally:
        conn.close()

def get_issue_history(user_id: str, db_path=config.DB_PATH) -> list[dict]:
    """
    Returns all classified issue logs from SQLite issue_log table for the given user,
    ordered by timestamp descending.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, issue_type, timestamp
            FROM issue_log
            WHERE user_id = ?
            ORDER BY timestamp DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error querying issue logs for user {user_id}: {e}")
        return []
    finally:
        conn.close()
