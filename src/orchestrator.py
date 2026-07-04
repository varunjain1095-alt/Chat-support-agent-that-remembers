"""
orchestrator.py — Central runtime coordinator wiring all components together.
"""

import sys
import logging
import pathlib
import threading

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.identity_resolver import resolve_user_id
from src.session import (
    get_active_session,
    create_session,
    record_activity,
    expire_stale_sessions
)
from src.context_assembler import assemble_context
from src.rag import retrieve
from src.agent import generate_response
from src.write_classifier import classify_and_save

logger = logging.getLogger(__name__)

# Run stale session cleanup on module startup/import
try:
    expire_stale_sessions(inactivity_hours=config.SESSION_INACTIVITY_HOURS)
except Exception as startup_err:
    logger.error(f"Failed to expire stale sessions on orchestrator startup: {startup_err}")

# Caches for session lifecycle caching
_SESSION_CONTEXT_CACHE = {}  # session_id -> context_obj
_SESSION_HISTORY_CACHE = {}  # session_id -> list of message dicts
_SESSION_RAG_CACHE = {}      # session_id -> list of policy chunks

def handle_message(
    raw_identifier: str,
    user_message: str,
    session_id: str | None = None
) -> str:
    """
    Central message handling pipeline that integrates retrieval, generation,
    session management, and asynchronous classification.
    """
    import time
    t_start_e2e = time.time()

    # 1. Identity Resolution
    t_id_start = time.time()
    user_id = resolve_user_id(raw_identifier)
    logger.info(f"[TIMING] Identity Resolution took: {((time.time() - t_id_start) * 1000):.2f} ms")

    # 2. Get or create session
    t_sess_start = time.time()
    if not session_id:
        session_id = get_active_session(user_id)
        if not session_id:
            session_id = create_session(user_id)
    logger.info(f"[TIMING] Session Lookup/Creation took: {((time.time() - t_sess_start) * 1000):.2f} ms")

    # 3. Record session activity
    record_activity(session_id)

    # 4. Context assembly and caching check
    t_ctx_start = time.time()
    if session_id in _SESSION_CONTEXT_CACHE:
        context_obj = _SESSION_CONTEXT_CACHE[session_id]
        logger.info(f"[TIMING] Context assembly (CACHED) took: {((time.time() - t_ctx_start) * 1000):.2f} ms")
    else:
        # Check if the query message is substantive (>= MIN_TURN_LENGTH_FOR_CLASSIFIER)
        if len(user_message.strip()) >= config.MIN_TURN_LENGTH_FOR_CLASSIFIER:
            context_obj = assemble_context(user_id, user_message)
            _SESSION_CONTEXT_CACHE[session_id] = context_obj
        else:
            # Skip assembly for low-signal greetings/short turns, do not cache yet
            context_obj = {
                "preferences": {},
                "account_state": {},
                "issue_history": [],
                "transcript_excerpts": []
            }
        logger.info(f"[TIMING] Context assembly (UNCACHED/TOTAL) took: {((time.time() - t_ctx_start) * 1000):.2f} ms")

    # 5. History retrieval
    if session_id not in _SESSION_HISTORY_CACHE:
        _SESSION_HISTORY_CACHE[session_id] = []
    history = _SESSION_HISTORY_CACHE[session_id]

    # 6. RAG Retrieval
    t_rag_start = time.time()
    policy_chunks = retrieve(user_message)
    _SESSION_RAG_CACHE[session_id] = policy_chunks
    logger.info(f"[TIMING] RAG retrieval took: {((time.time() - t_rag_start) * 1000):.2f} ms")

    # 7. Agent Response Generation
    t_gen_start = time.time()
    response = generate_response(user_message, context_obj, policy_chunks, history)
    logger.info(f"[TIMING] Agent Response Generation took: {((time.time() - t_gen_start) * 1000):.2f} ms")

    # 8. Append turn to conversation history cache
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": response})

    # 9. Asynchronous write-path classification in background
    turn = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response}
    ]
    
    # Run fire-and-forget background thread
    bg_thread = threading.Thread(
        target=classify_and_save,
        args=(user_id, session_id, turn),
        daemon=True
    )
    bg_thread.start()

    # 10. Return agent response
    logger.info(f"[TIMING] Total end-to-end time took: {((time.time() - t_start_e2e) * 1000):.2f} ms")
    return response

def handle_message_stream(
    raw_identifier: str,
    user_message: str,
    session_id: str | None = None
):
    """
    Central streaming message handling pipeline. Identical logic to handle_message,
    but yields tokens dynamically as they arrive from Claude, followed by the final context metadata.
    """
    import time
    t_start_e2e = time.time()

    # 1. Identity Resolution
    t_id_start = time.time()
    user_id = resolve_user_id(raw_identifier)
    logger.info(f"[TIMING] Identity Resolution took: {((time.time() - t_id_start) * 1000):.2f} ms")

    # 2. Get or create session
    t_sess_start = time.time()
    if not session_id:
        session_id = get_active_session(user_id)
        if not session_id:
            session_id = create_session(user_id)
    logger.info(f"[TIMING] Session Lookup/Creation took: {((time.time() - t_sess_start) * 1000):.2f} ms")

    # 3. Record session activity
    record_activity(session_id)

    # 4. Context assembly and caching check
    t_ctx_start = time.time()
    if session_id in _SESSION_CONTEXT_CACHE:
        context_obj = _SESSION_CONTEXT_CACHE[session_id]
        logger.info(f"[TIMING] Context assembly (CACHED) took: {((time.time() - t_ctx_start) * 1000):.2f} ms")
    else:
        # Check if the query message is substantive (>= MIN_TURN_LENGTH_FOR_CLASSIFIER)
        if len(user_message.strip()) >= config.MIN_TURN_LENGTH_FOR_CLASSIFIER:
            context_obj = assemble_context(user_id, user_message)
            _SESSION_CONTEXT_CACHE[session_id] = context_obj
        else:
            # Skip assembly for low-signal greetings/short turns, do not cache yet
            context_obj = {
                "preferences": {},
                "account_state": {},
                "issue_history": [],
                "transcript_excerpts": []
            }
        logger.info(f"[TIMING] Context assembly (UNCACHED/TOTAL) took: {((time.time() - t_ctx_start) * 1000):.2f} ms")

    # 5. History retrieval
    if session_id not in _SESSION_HISTORY_CACHE:
        _SESSION_HISTORY_CACHE[session_id] = []
    history = _SESSION_HISTORY_CACHE[session_id]

    # 6. RAG Retrieval
    t_rag_start = time.time()
    policy_chunks = retrieve(user_message)
    _SESSION_RAG_CACHE[session_id] = policy_chunks
    logger.info(f"[TIMING] RAG retrieval took: {((time.time() - t_rag_start) * 1000):.2f} ms")

    # 7. Agent Response Generation (Stream)
    from src.agent import generate_response_stream
    full_response_parts = []
    
    t_first_token_start = time.time()
    first_token_reported = False
    
    for token in generate_response_stream(user_message, context_obj, policy_chunks, history):
        if not first_token_reported:
            logger.info(f"[TIMING] Time to first token: {((time.time() - t_first_token_start) * 1000):.2f} ms")
            first_token_reported = True
        full_response_parts.append(token)
        yield {"type": "token", "text": token}

    response_text = "".join(full_response_parts)

    # 8. Append turn to conversation history cache
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": response_text})

    # 9. Asynchronous write-path classification in background
    turn = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response_text}
    ]
    bg_thread = threading.Thread(
        target=classify_and_save,
        args=(user_id, session_id, turn),
        daemon=True
    )
    bg_thread.start()

    logger.info(f"[TIMING] Total streaming e2e time took: {((time.time() - t_start_e2e) * 1000):.2f} ms")
    
    # 10. Yield final metadata payload
    yield {
        "type": "done",
        "session_id": session_id,
        "context": {
            "preferences": {
                "data": context_obj.get("preferences", {}),
                "source": "Mem0"
            },
            "account_state": {
                "data": context_obj.get("account_state", {}),
                "source": "Zep"
            },
            "issue_history": {
                "data": context_obj.get("issue_history", []),
                "source": "SQLite (issue_log)"
            },
            "transcript_excerpts": {
                "data": context_obj.get("transcript_excerpts", []),
                "source": "SQLite (transcripts)"
            },
            "policy_context": {
                "data": policy_chunks,
                "source": "RAG"
            }
        }
    }
