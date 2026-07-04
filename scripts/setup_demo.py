#!/usr/bin/env python3
"""
scripts/setup_demo.py — Resets and seeds the entire application state for the demo scenario.
"""

import os
import sys
import json
import time
import sqlite3
import pathlib
import logging
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from db.init_db import init_db
from src.ingestion import ingest_transcript
from src.write_classifier import classify_and_save
from src.memory import search_preferences, search_state
from mem0 import MemoryClient
from zep_cloud.client import Zep
from zep_cloud.errors import NotFoundError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("setup_demo")

# WARNING: Running this script drops all existing SQLite tables and clears Zep/Mem0 data for user_123!

def parse_turns_from_content(content: str, channel: str) -> List[List[Dict[str, str]]]:
    """
    Parses dialogue text into chronologically grouped dialogue turns
    suitable for the write classifier.
    """
    if channel == "email":
        return [[{"role": "user", "content": content}]]

    turns = []
    lines = content.strip().split("\n")
    current_turn = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith("Rahul:") or line.startswith("User:") or line.startswith("Rahul reported"):
            if any(m["role"] == "user" for m in current_turn):
                turns.append(current_turn)
                current_turn = []
            msg = line.split(":", 1)[1].strip() if ":" in line else line
            current_turn.append({"role": "user", "content": msg})
            
        elif line.startswith("Agent:") or line.startswith("Assistant:") or line.startswith("Priya:"):
            msg = line.split(":", 1)[1].strip() if ":" in line else line
            current_turn.append({"role": "assistant", "content": msg})
            
        else:
            # Descriptive line or narrative: treat as a user signal
            if any(m["role"] == "user" for m in current_turn):
                turns.append(current_turn)
                current_turn = []
            current_turn.append({"role": "user", "content": line})
            
    if current_turn:
        turns.append(current_turn)
        
    return turns


def main():
    print("==================================================")
    print("         AI CUSTOMER SUPPORT DEMO SETUP           ")
    print("==================================================")
    print("WARNING: This script drops all tables in SQLite and clears cloud stores for user_123.")

    # 1. Reset SQLite Database
    print("\n[1/5] Resetting SQLite Database...")
    db_path = config.DB_PATH
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS transcripts")
            cursor.execute("DROP TABLE IF EXISTS issue_log")
            cursor.execute("DROP TABLE IF EXISTS sessions")
            conn.commit()
            print("Dropped existing SQLite tables.")
        except Exception as e:
            print(f"Error dropping tables: {e}")
        finally:
            conn.close()

    init_db(db_path)
    print("Database initialized successfully with clean schema.")

    # 2. Reset Zep and Mem0 Cloud Stores
    print("\n[2/5] Resetting Zep and Mem0 Cloud Stores for user_123...")
    
    # 2a. Zep Reset & Poll
    zep = Zep(api_key=config.ZEP_API_KEY)
    print("Triggering Zep user deletion...")
    try:
        zep.user.delete(user_id="user_123")
    except Exception as e:
        print(f"Zep user delete query (expected fallback if user is new): {e}")

    # Polling up to 10 seconds for Zep deletion propagation
    deleted = False
    for i in range(10):
        print(f"Polling Zep deletion status... (attempt {i+1}/10)")
        try:
            zep.user.get(user_id="user_123")
            time.sleep(1)
        except NotFoundError:
            deleted = True
            print("Zep deletion confirmed propagated (NotFoundError received).")
            break
        except Exception as e:
            print(f"Unexpected status fetch error: {e}")
            time.sleep(1)

    if not deleted:
        print("Warning: Zep delete polling timed out. Proceeding anyway.")

    # Ensure user exists for Zep writes
    try:
        zep.user.add(user_id="user_123")
        print("Re-registered user_123 in Zep.")
    except Exception as e:
        print(f"Zep user registration error: {e}")

    # 2b. Mem0 Reset
    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    print("Deleting Mem0 preferences...")
    try:
        mem0.delete_all(user_id="user_123")
        print("Mem0 preferences cleared.")
    except Exception as e:
        print(f"Mem0 clear error: {e}")

    # 3. Read and Chronologically Sort Transcript Files
    print("\n[3/5] Reading and sorting raw transcripts...")
    raw_dir = project_root / "data" / "raw"
    files = list(raw_dir.glob("*.json"))
    
    transcripts_data = []
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            transcripts_data.append({
                "filepath": str(filepath),
                "timestamp": data.get("timestamp", ""),
                "transcript_id": data.get("transcript_id", ""),
                "channel": data.get("channel", ""),
                "content": data.get("content", "")
            })

    # Chronological sort by internal timestamp field
    transcripts_data.sort(key=lambda x: x["timestamp"])
    
    print("Chronological order for ingestion:")
    for t in transcripts_data:
        print(f"  - {t['transcript_id']} ({t['timestamp']})")

    # 4. Ingest and Run Classifier Turn-by-Turn
    print("\n[4/5] Ingesting and classifying dialogue turns...")
    for t in transcripts_data:
        print(f"\nProcessing transcript: {t['transcript_id']} (channel: {t['channel']})")
        # Step 4a: Ingest to SQLite
        ingest_transcript(t["filepath"], db_path=db_path)
        print(f"  -> Ingested into SQLite database.")

        # Step 4b: Parse into turns and classify
        turns = parse_turns_from_content(t["content"], t["channel"])
        print(f"  -> Parsed into {len(turns)} turns. Classifying...")
        for idx, turn in enumerate(turns):
            # Run write-path classifier
            result = classify_and_save(
                user_id="user_123",
                session_id=t["transcript_id"],
                conversation_turn=turn,
                db_path=db_path,
                timestamp=t["timestamp"]
            )
            user_msg = next((m["content"] for m in turn if m["role"] == "user"), "")
            msg_snippet = (user_msg[:50] + "...") if len(user_msg) > 50 else user_msg
            print(f"    Turn {idx+1}/{len(turns)}: '{msg_snippet}' -> Result: {result}")
            # Give Zep graph API time to process without hitting rate limits
            time.sleep(0.5)

    # 5. Telemetry Summary
    print("\n[5/5] Generating Telemetry Summary...")
    print("==================================================")
    print("               TELEMETRY SUMMARY                  ")
    print("==================================================")

    # 5a. Mem0 preferences content
    print("\n--- Mem0 Preferences ---")
    prefs = search_preferences("user_123", "communication preferences")
    if prefs:
        for p in prefs:
            print(f"  - [{p.get('id', 'N/A')}] {p.get('memory')}")
    else:
        print("  (No preferences stored in Mem0)")

    # 5b. Zep graph fact nodes & thread history
    print("\n--- Zep Graph Status ---")
    # Wait a moment for asynchronous graph index to settle before query
    time.sleep(2)
    zep_state = search_state("user_123", "rate limit upgrade Pro")
    nodes = zep_state.get("nodes", [])
    edges = zep_state.get("edges", [])
    if nodes:
        print("  Nodes:")
        for n in nodes:
            print(f"    - ID: {n.get('id')} ({n.get('type')}) -> Name: '{n.get('name')}'")
        if edges:
            print("  Edges:")
            for e in edges:
                print(f"    - Source: {e.get('source')} -[{e.get('type')}]-> Target: {e.get('target')}")
    else:
        print("  (No Zep graph data found)")

    # 5c. Zep Threads Status (Omnichannel verification)
    print("\n--- Zep Threads Status (Omnichannel Verification) ---")
    for t in transcripts_data:
        thread_id = t["transcript_id"]
        try:
            thread_info = zep.thread.get(thread_id=thread_id)
            # Access messages attribute directly from Thread object
            msg_list = thread_info.messages if thread_info.messages else []
            print(f"  - Thread: '{thread_id}' | Status: Found | Messages count: {len(msg_list)}")
            if msg_list:
                first_content = msg_list[-1].content  # Zep messages are ordered, first user message is at index -1 or 0
                snippet = (first_content[:65] + "...") if len(first_content) > 65 else first_content
                print(f"    First msg: {msg_list[-1].role}: '{snippet}'")
        except Exception as ex:
            print(f"  - Thread: '{thread_id}' | Status: Error ({ex})")

    # 5d. SQLite issue_log rows
    print("\n--- SQLite Issue Log ---")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, issue_type, timestamp FROM issue_log ORDER BY id ASC")
        rows = cursor.fetchall()
        if rows:
            for r in rows:
                print(f"  - Row ID {r[0]}: User: {r[1]} | Issue Type: '{r[2]}' | Time: {r[3]}")
        else:
            print("  (No issue log rows found)")
    except Exception as e:
        print(f"Error querying issue log: {e}")
    finally:
        conn.close()

    print("\n==================================================")
    print("              DEMO SETUP COMPLETED                ")
    print("==================================================")

if __name__ == "__main__":
    main()
