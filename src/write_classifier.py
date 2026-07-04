"""
write_classifier.py — Post-turn LLM classifier that routes memory saves to Mem0 or Zep.
"""

import sys
import json
import logging
import pathlib
import sqlite3
import anthropic

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.memory import save_preference, save_state

logger = logging.getLogger(__name__)

def classify_and_save(
    user_id: str,
    session_id: str,
    conversation_turn: list[dict],
    db_path=config.DB_PATH,
    timestamp: str = None
) -> str:
    """
    Post-turn memory routing component. After every agent turn, it extracts any new memory signals,
    passes them through a grounding check, and routes them to the correct store — or discards them.
    """
    # 1. Pre-check content length
    user_content = " ".join([m.get("content", "") for m in conversation_turn if m.get("role") == "user"])
    if len(user_content.strip()) < config.MIN_TURN_LENGTH_FOR_CLASSIFIER:
        logger.info(f"Skipping classifier call because turn length {len(user_content)} < {config.MIN_TURN_LENGTH_FOR_CLASSIFIER}")
        return "discarded"

    # 2. Build prompt for Claude
    system_prompt = (
        "You are a memory extraction and classification engine.\n"
        "Your task is to analyze a single customer support conversation turn and determine if there is any new preference or factual state information to extract and save.\n\n"
        "Evaluate the turn against two gates:\n\n"
        "Gate 1: Grounding Check\n"
        "The extracted info must be explicitly stated in the turn text. Do not make inferences or assume facts. "
        "If the turn is just greetings, acknowledgments ('ok', 'thanks'), or contains no new, explicit preferences/facts, select 'discard'.\n\n"
        "Gate 2: Classification Check\n"
        "If the turn passes the grounding check, classify it:\n"
        "- If it is a soft preference, communication style, or tone preference (e.g. 'be concise', 'explain step-by-step'), select 'save_mem0'.\n"
        "- If it is a hard fact, account status update, plan history change, transactional event, or support issue (e.g. 'upgraded to Pro', 'seeing rate limit errors'), select 'save_zep'. "
        "If it is a support issue, extract a concise lowercase keyword/phrase for 'issue_type'.\n\n"
        "Respond ONLY with a valid JSON object matching this schema:\n"
        "{\n"
        "  \"action\": \"save_mem0\" | \"save_zep\" | \"discard\",\n"
        "  \"content\": \"verbatim extracted preference or fact text (or null if action is discard)\",\n"
        "  \"issue_type\": \"concise lowercase issue type keyword if it is a support issue, otherwise null\"\n"
        "}"
    )

    user_content_prompt = f"Conversation Turn:\n{json.dumps(conversation_turn, indent=2)}"

    # 3. Call Claude
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=config.CLAUDE_JUDGE_MODEL,
            max_tokens=500,
            temperature=0.0,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content_prompt}
            ]
        )
        response_text = message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude request error in classifier: {e}")
        return "discarded"

    # 4. Parse JSON
    try:
        import re
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if match:
            json_text = match.group(0)
        else:
            json_text = response_text
        parsed = json.loads(json_text)
    except Exception as e:
        logger.warning(f"Failed to parse JSON response from classifier: '{response_text}'. Error: {e}")
        return "discarded"

    # 5. Dispatch actions
    action = parsed.get("action")
    content = parsed.get("content")
    issue_type = parsed.get("issue_type")

    if action == "save_mem0":
        save_preference(user_id, conversation_turn)
        return "mem0"

    elif action == "save_zep":
        save_state(session_id, conversation_turn, timestamp=timestamp)
        
        # Log to issue_log if an issue_type is returned
        if issue_type and isinstance(issue_type, str) and issue_type.strip():
            clean_issue_type = issue_type.strip().lower()
            
            # Deduplication check (EC-WC-04): check if this user + issue was logged in the last 24 hours
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                if timestamp:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM issue_log 
                        WHERE user_id = ? AND issue_type = ? 
                          AND timestamp > datetime(?, '-24 hours')
                          AND timestamp <= ?
                        """,
                        (user_id, clean_issue_type, timestamp, timestamp)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM issue_log 
                        WHERE user_id = ? AND issue_type = ? 
                          AND timestamp > datetime('now', '-24 hours')
                        """,
                        (user_id, clean_issue_type)
                    )
                count = cursor.fetchone()[0]
                
                if count == 0:
                    if timestamp:
                        cursor.execute(
                            "INSERT INTO issue_log (user_id, issue_type, timestamp) VALUES (?, ?, ?)",
                            (user_id, clean_issue_type, timestamp)
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO issue_log (user_id, issue_type) VALUES (?, ?)",
                            (user_id, clean_issue_type)
                        )
                    conn.commit()
                    logger.info(f"Logged new issue to db: {clean_issue_type} for user {user_id}")
                else:
                    logger.info(f"Skipped duplicate issue log entry for {clean_issue_type} (user {user_id}) in last 24h")
            except Exception as e:
                logger.error(f"Error checking/inserting into issue_log: {e}")
            finally:
                conn.close()

        return "zep"

    else:
        # action is discard or unknown
        return "discarded"
