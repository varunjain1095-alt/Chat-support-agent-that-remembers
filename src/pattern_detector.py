"""
pattern_detector.py — Backend-only cross-user issue pattern detection via SQLite.
"""

import sqlite3
import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config

logger = logging.getLogger(__name__)

def detect_patterns(
    threshold_count: int = 10,
    window_days: int = 7,
    db_path=config.DB_PATH
) -> list[dict]:
    """
    Scans the shared SQLite issue_log and aggregates issues reported
    across multiple distinct users. Returns a list of identified patterns.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # We query COUNT(DISTINCT user_id) as the user count (EC-PD-03)
        query = """
            SELECT issue_type, COUNT(DISTINCT user_id) as user_count
            FROM issue_log
            WHERE timestamp > datetime('now', ?)
            GROUP BY issue_type
            HAVING user_count >= ?
        """
        
        # SQLite datetime('now', '-7 days') accepts '-7 days' as argument
        modifier = f"-{window_days} days"
        cursor.execute(query, (modifier, threshold_count))
        rows = cursor.fetchall()
        
        # Calculate window start timestamp
        window_start_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
        window_start_str = window_start_dt.isoformat()
        
        patterns = []
        for row in rows:
            patterns.append({
                "issue_type": row[0],
                "count": row[1],
                "window_start": window_start_str
            })
            
        return patterns
    except Exception as e:
        logger.error(f"Error during cross-user pattern detection: {e}")
        return []
    finally:
        conn.close()
