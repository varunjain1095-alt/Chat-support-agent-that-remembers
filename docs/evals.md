# Evals — Customer Support Agent with Memory

> **Purpose:** Phase-by-phase verification plan. Each phase section defines the specific test scenarios that must pass before the phase is considered done. Includes: test type (unit / integration / eval), exact inputs, expected outputs, and binary pass/fail criteria. This document is the executable test spec — scenarios here map 1:1 to test functions in `tests/`.

---

## Conventions

| Symbol | Meaning |
| :--- | :--- |
| ✅ PASS | Assertion holds exactly |
| ❌ FAIL | Assertion does not hold — phase is not done |
| `[UNIT]` | Pure function test, no external API calls, fast |
| `[INTG]` | Calls real external APIs (Mem0, Zep, Claude, OpenAI) — slower, requires live credentials |
| `[EVAL]` | LLM-as-judge or semantic assertion — output is scored, not string-matched |

All `[UNIT]` tests must run via `pytest` with no credentials. All `[INTG]` and `[EVAL]` tests require the `.env` file and are grouped under `tests/integration/` and `tests/evals/` respectively.

---

## Phase 0 — Environment & Scaffold

### P0-01 · Dependency install `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Run `pip install -r requirements.txt` in a clean virtual environment |
| **Expected behavior** | All packages install without conflicts or errors |
| **Pass criterion** | Exit code 0; no `ERROR` in pip output |
| **Fail criterion** | Any package fails to install; version conflict reported |

### P0-02 · Config loads from `.env` `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Call `from config import ANTHROPIC_API_KEY, MEM0_API_KEY, ZEP_API_KEY` |
| **Expected behavior** | All three variables are non-empty strings |
| **Pass criterion** | `assert all([ANTHROPIC_API_KEY, MEM0_API_KEY, ZEP_API_KEY])` |
| **Fail criterion** | Any variable is `None` or empty string |

### P0-03 · Claude client initializes `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | `Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(model="claude-sonnet-4-5-20250929", max_tokens=5, messages=[{"role":"user","content":"hi"}])` |
| **Expected behavior** | Response object returned with non-empty content |
| **Pass criterion** | `response.content[0].text` is a non-empty string |
| **Fail criterion** | `AuthenticationError`, `APIConnectionError`, or any exception |

### P0-04 · Mem0 client initializes `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | `MemoryClient(api_key=MEM0_API_KEY).search(query="test", filters={"user_id": "smoke_test_user"})` |
| **Expected behavior** | Returns a list (empty or populated — does not matter) without raising |
| **Pass criterion** | Call completes; result is a `list` |
| **Fail criterion** | Any authentication or connection exception |

### P0-05 · Zep client initializes `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | `Zep(api_key=ZEP_API_KEY).graph.search(query="test", user_id="smoke_test_user")` |
| **Expected behavior** | Returns a result object without raising |
| **Pass criterion** | Call completes without exception |
| **Fail criterion** | Any authentication or connection exception |

---

## Phase 1 — Identity Resolver

### P1-01 · Known email resolves correctly `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("rahul@acme.com")` |
| **Expected output** | `"user_123"` |
| **Pass criterion** | `assert result == "user_123"` |
| **Fail criterion** | Any other value or exception |

### P1-02 · Known phone resolves correctly `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("+91-9876543210")` |
| **Expected output** | `"user_123"` |
| **Pass criterion** | `assert result == "user_123"` |
| **Fail criterion** | Any other value or exception |

### P1-03 · Known session token resolves correctly `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("sess_abc_789")` |
| **Expected output** | `"user_123"` |
| **Pass criterion** | `assert result == "user_123"` |
| **Fail criterion** | Any other value or exception |

### P1-04 · Unknown identifier returns fallback `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("unknown@random.com")` |
| **Expected output** | `"unknown_user"` |
| **Pass criterion** | `assert result == "unknown_user"` |
| **Fail criterion** | Exception raised, or any other string returned |

### P1-05 · Empty identifier returns fallback, does not crash `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("")` and `resolve_user_id(None)` |
| **Expected output** | `"unknown_user"` in both cases |
| **Pass criterion** | Both return `"unknown_user"` without raising |
| **Fail criterion** | `AttributeError`, `TypeError`, or any exception |

### P1-06 · Resolution event is logged `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `resolve_user_id("rahul@acme.com")` with `caplog` capturing INFO |
| **Expected output** | Log message contains `"Identity resolved: rahul@acme.com → user_123"` |
| **Pass criterion** | `"Identity resolved"` appears in captured log output |
| **Fail criterion** | No log message emitted |

---

## Phase 2 — Transcript Ingestion Pipeline

### P2-01 · Database initializes with correct schema `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Run `init_db.py` against a fresh in-memory SQLite database |
| **Expected behavior** | Tables `transcripts` and `issue_log` exist with correct columns |
| **Pass criterion** | `PRAGMA table_info(transcripts)` returns columns: `transcript_id`, `user_id`, `channel`, `timestamp`, `content` |
| **Fail criterion** | Any column missing; table does not exist; exception |

### P2-02 · Transcript ingests correctly `[UNIT]`
| | |
| :--- | :--- |
| **Input** | A valid transcript JSON dict with all required fields |
| **Expected behavior** | One row appears in `transcripts` table with matching field values |
| **Pass criterion** | `SELECT COUNT(*) FROM transcripts WHERE transcript_id = ?` returns 1; all field values match |
| **Fail criterion** | Row count is 0; any field value is wrong; exception |

### P2-03 · Duplicate ingest is silently skipped `[UNIT]`
| | |
| :--- | :--- |
| **Input** | Same transcript file ingested twice |
| **Expected behavior** | Row count remains 1 after second ingest; no exception |
| **Pass criterion** | `SELECT COUNT(*) FROM transcripts WHERE transcript_id = ?` returns 1 after both calls |
| **Fail criterion** | Count becomes 2; `IntegrityError` raised and unhandled |

### P2-04 · Malformed JSON skips file, does not crash `[UNIT]`
| | |
| :--- | :--- |
| **Input** | A file path pointing to a file containing `{ "transcript_id": "x", INVALID JSON }` |
| **Expected behavior** | Function catches `JSONDecodeError`, logs a warning, returns without crashing |
| **Pass criterion** | No exception propagates; `transcripts` table count is unchanged |
| **Fail criterion** | Unhandled exception; row incorrectly inserted |

### P2-05 · `get_recent_transcripts` returns correct limit and order `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Insert 5 transcript rows for `user_123` with timestamps T1 < T2 < T3 < T4 < T5, all in closed sessions |
| **Input** | `get_recent_transcripts("user_123", limit=3)` |
| **Expected output** | List of 3 dicts, ordered T5, T4, T3 (newest first) |
| **Pass criterion** | `len(result) == 3` and `result[0]["timestamp"] > result[1]["timestamp"] > result[2]["timestamp"]` |
| **Fail criterion** | Wrong count; wrong order |

### P2-06 · All four demo transcript files ingest without errors `[UNIT]`
| | |
| :--- | :--- |
| **Input** | Run `ingest_transcript()` on each of the four demo files in `data/raw/` |
| **Expected behavior** | All four rows appear in `transcripts` with correct `user_id = "user_123"` and correct `channel` values |
| **Pass criterion** | `SELECT COUNT(*) FROM transcripts WHERE user_id = 'user_123'` returns 4 |
| **Fail criterion** | Count != 4; any exception during ingestion |

---

## Phase 3 — Memory Store Integration

### P3-01 · Mem0 preference save → search round-trip `[INTG]`
| | |
| :--- | :--- |
| **Input** | `save_preference("eval_user_p3", [{"role":"user","content":"I prefer step-by-step guidance"}])` then `search_preferences("eval_user_p3", "how do you like to be helped")` |
| **Expected output** | Search result contains a memory referencing `"step-by-step"` |
| **Pass criterion** | At least one result in the returned list; result text contains `"step"` or `"step-by-step"` |
| **Fail criterion** | Empty result list; exception; no match |
| **Cleanup** | Delete `eval_user_p3` test memories after test |

### P3-02 · Zep state save → search round-trip `[INTG]`
| | |
| :--- | :--- |
| **Input** | `save_state("eval_session_p3", [{"role":"user","content":"I upgraded to Pro plan last week"}])` then `search_state("eval_user_p3", "what plan is this user on")` |
| **Expected output** | Search result references `"Pro"` |
| **Pass criterion** | At least one result; result text contains `"Pro"` |
| **Fail criterion** | Empty result; exception; no plan reference |
| **Cleanup** | Delete test session and user data after test |

### P3-03 · No raw SDK calls outside `memory.py` `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | `grep -r "mem0ai\|zep_cloud\|MemoryClient\|from zep" src/ --include="*.py" --exclude="memory.py"` |
| **Expected output** | Zero matches |
| **Pass criterion** | Command returns no output |
| **Fail criterion** | Any match found — raw SDK call exists outside the wrapper module |

---

## Phase 4 — Context Assembler

### P4-01 · Populated stores → all four schema fields non-empty `[INTG]`
| | |
| :--- | :--- |
| **Setup** | Seed Mem0 with a preference, Zep with an account state, and SQLite with two closed-session transcripts for `eval_user_p4` |
| **Input** | `assemble_context("eval_user_p4", "I need help with my account")` |
| **Expected output** | Dict with all four keys; each value is non-empty |
| **Pass criterion** | `result["preferences"] != {}` and `result["account_state"] != {}` and `len(result["issue_history"]) >= 0` and `len(result["transcript_excerpts"]) > 0` |
| **Fail criterion** | Any key missing; `json.JSONDecodeError`; exception |

### P4-02 · Cold-start → all four fields empty, no crash `[INTG]`
| | |
| :--- | :--- |
| **Input** | `assemble_context("brand_new_user_xyz_9999", "hello")` (user with no data anywhere) |
| **Expected output** | `{"preferences": {}, "account_state": {}, "issue_history": [], "transcript_excerpts": []}` |
| **Pass criterion** | All four fields are empty collections; no exception raised |
| **Fail criterion** | Exception raised; schema malformed; non-empty value from empty stores |

### P4-03 · Field-level conflict merge — both stores contribute `[INTG]`
| | |
| :--- | :--- |
| **Setup** | Seed Mem0 with `"prefers verbose responses"` for `eval_user_p4_conflict`. Seed Zep with `"account: Pro plan, issue: rate limiting open"` |
| **Input** | `assemble_context("eval_user_p4_conflict", "my issue is still open")` |
| **Expected behavior** | `preferences` block contains Mem0 data; `account_state`/`issue_history` contains Zep data; neither is absent |
| **Pass criterion** | `"verbose"` appears somewhere in `str(result["preferences"])` AND `"Pro"` or `"rate"` appears in `str(result["account_state"]) + str(result["issue_history"])` |
| **Fail criterion** | Either block is empty; one store's data overwrites the other completely |

### P4-04 · Output always conforms to fixed four-field schema `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Run `assemble_context()` 5 times with different inputs (including edge cases: one store empty, two stores empty) |
| **Expected behavior** | Every result contains exactly the keys: `preferences`, `account_state`, `issue_history`, `transcript_excerpts` |
| **Pass criterion** | `set(result.keys()) == {"preferences", "account_state", "issue_history", "transcript_excerpts"}` for all 5 runs |
| **Fail criterion** | Any extra key present; any required key missing; in any run |

### P4-05 · Parallel fetch is concurrent, not sequential `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Mock all three fetch functions to sleep for 1 second each. Time the total execution of `assemble_context()` |
| **Expected behavior** | Total time ≈ 1 second (parallel) not ≈ 3 seconds (sequential) |
| **Pass criterion** | `elapsed_time < 2.0` seconds |
| **Fail criterion** | `elapsed_time >= 2.5` seconds (sequential execution) |

---

## Phase 5 — RAG Policy Retriever & Agent Response Generator

### P5-01 · `build_index()` creates the vector store `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Run `build_index()` against the three policy docs in `data/policy/` |
| **Expected behavior** | `vector_store/` directory is created and non-empty |
| **Pass criterion** | `os.path.exists("vector_store/")` is True and directory contains at least one file |
| **Fail criterion** | Directory not created; exception during embedding; empty directory |

### P5-02 · `retrieve()` returns relevant chunks `[INTG]`
| | |
| :--- | :--- |
| **Input** | `retrieve("rate limiting after plan upgrade", top_k=3)` |
| **Expected output** | At least one chunk containing content from `known_issues_resolutions.md` |
| **Pass criterion** | `len(result) >= 1` and any chunk contains the word `"rate"` or `"limit"` |
| **Fail criterion** | Empty list returned; no relevant chunk retrieved; exception |

### P5-03 · `retrieve()` below similarity threshold returns empty `[INTG]`
| | |
| :--- | :--- |
| **Input** | `retrieve("what is the capital of France", top_k=3)` (completely off-topic) |
| **Expected output** | Empty list or list with all chunks below the similarity threshold |
| **Pass criterion** | Result is `[]` or all returned chunks have similarity score below the configured threshold |
| **Fail criterion** | Irrelevant policy chunks returned at full confidence |

### P5-04 · `generate_response()` returns non-empty string `[INTG]`
| | |
| :--- | :--- |
| **Input** | A synthetic context object (all four fields populated), two policy chunks, `user_message = "I need help with rate limiting"` |
| **Expected output** | A non-empty string response |
| **Pass criterion** | `isinstance(result, str) and len(result.strip()) > 0` |
| **Fail criterion** | Empty string; exception; non-string return |

### P5-05 · Prompt contains distinct USER CONTEXT and POLICY CONTEXT sections `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Intercept the prompt string assembled inside `generate_response()` before the Claude call |
| **Expected behavior** | Prompt contains both `"[USER CONTEXT"` and `"[POLICY CONTEXT"` as section headers |
| **Pass criterion** | `"[USER CONTEXT" in prompt and "[POLICY CONTEXT" in prompt` |
| **Fail criterion** | Either section header absent; sections merged into one block |

---

## Phase 6 — Write-Path Classifier

### P6-01 · Explicit preference turn → routes to Mem0, not Issue Log `[INTG]`
| | |
| :--- | :--- |
| **Input** | Turn: `[{"role":"user","content":"Please always walk me through things step by step"}]` |
| **Pre-condition** | Record the current Issue Log count |
| **Expected behavior** | Returns `"mem0"`; Issue Log count unchanged |
| **Pass criterion** | `result == "mem0"` AND `issue_log_count_after == issue_log_count_before` |
| **Fail criterion** | Any other return value; Issue Log count increases |

### P6-02 · Explicit state fact → routes to Zep, writes to Issue Log `[INTG]`
| | |
| :--- | :--- |
| **Input** | Turn: `[{"role":"user","content":"I'm still seeing rate limiting errors even after upgrading to Pro"}]` |
| **Pre-condition** | Record the current Issue Log count |
| **Expected behavior** | Returns `"zep"`; Issue Log count increases by 1; `issue_type` is present |
| **Pass criterion** | `result == "zep"` AND `issue_log_count_after == issue_log_count_before + 1` AND new row has a non-empty `issue_type` |
| **Fail criterion** | Wrong return value; Issue Log not written; Issue Log written when it shouldn't be |

### P6-03 · Turn with no new information → discard `[INTG]`
| | |
| :--- | :--- |
| **Input** | Turn: `[{"role":"user","content":"ok"}, {"role":"assistant","content":"Got it!"}]` |
| **Expected behavior** | Returns `"discarded"`; no writes to Mem0, Zep, or Issue Log |
| **Pass criterion** | `result == "discarded"` |
| **Fail criterion** | Any save action returned |

### P6-04 · Grounding check — inferred fact not in turn → discard `[INTG]`
| | |
| :--- | :--- |
| **Input** | Turn: `[{"role":"user","content":"Can you help me?"}]` (no stated preference or fact) |
| **Expected behavior** | Even if Claude could infer something, the grounding check prevents a save → `"discarded"` |
| **Pass criterion** | `result == "discarded"` |
| **Fail criterion** | Classifier returns `"mem0"` or `"zep"` based on inference, not explicit statement |

### P6-05 · Classifier output is valid JSON on every call `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Mock Claude to return malformed JSON (`"not json"`) from the classifier call |
| **Expected behavior** | Function catches parse error, returns `"discarded"`, does not raise |
| **Pass criterion** | Return value is `"discarded"`; no exception propagates |
| **Fail criterion** | `JSONDecodeError` or `KeyError` propagates to caller |

### P6-06 · Short turn (< 10 chars) → skips classifier call entirely `[UNIT]`
| | |
| :--- | :--- |
| **Input** | Turn content: `"ok"` (2 characters) |
| **Expected behavior** | Pre-check fires before the Claude API call; classifier Claude call is NOT made; returns `"discarded"` |
| **Pass criterion** | `result == "discarded"` AND mock confirms Claude was not called |
| **Fail criterion** | Claude API is called; non-discard result returned |

---

## Phase 7 — Cross-User Pattern Detector

### P7-01 · Issue count above threshold → pattern detected `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Seed `issue_log` with 10 rows: `issue_type = "api_rate_limit"`, all within the last 7 days, across 5 distinct `user_id` values |
| **Input** | `detect_patterns(threshold_count=10, window_days=7)` |
| **Expected output** | List containing `{"issue_type": "api_rate_limit", "count": 10, ...}` |
| **Pass criterion** | `any(p["issue_type"] == "api_rate_limit" for p in result)` |
| **Fail criterion** | Empty list; wrong issue type returned |

### P7-02 · Issue count below threshold → not detected `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Seed 9 rows for `issue_type = "api_rate_limit"` within 7 days |
| **Input** | `detect_patterns(threshold_count=10, window_days=7)` |
| **Expected output** | `[]` |
| **Pass criterion** | `result == []` |
| **Fail criterion** | Pattern returned despite count below threshold |

### P7-03 · Issues outside the time window are excluded `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Seed 5 rows within the window + 6 rows from 8 days ago (outside 7-day window) |
| **Input** | `detect_patterns(threshold_count=10, window_days=7)` |
| **Expected output** | `[]` (only 5 in-window; 6 out-of-window not counted) |
| **Pass criterion** | `result == []` |
| **Fail criterion** | Pattern detected using out-of-window data |

### P7-04 · Detector output never reaches orchestrator during a chat turn `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Trace all call paths from `handle_message()` through the call graph |
| **Expected behavior** | `detect_patterns()` is not in the call graph of `handle_message()` |
| **Pass criterion** | `grep -r "detect_patterns" src/orchestrator.py` returns zero matches |
| **Fail criterion** | Any call to `detect_patterns` found in the orchestrator or any module it imports |

---

## Phase 8 — Session Lifecycle

### P8-01 · New session is created with `active` status `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `session_id = create_session("user_123")` |
| **Expected output** | Row in `sessions` table with `status = 'active'` and `user_id = 'user_123'` |
| **Pass criterion** | `SELECT status FROM sessions WHERE session_id = ?` returns `'active'` |
| **Fail criterion** | Row not found; wrong status; exception |

### P8-02 · `close_session()` sets status to `closed` `[UNIT]`
| | |
| :--- | :--- |
| **Input** | Create a session, then call `close_session(session_id)` |
| **Expected output** | Status changes to `'closed'` |
| **Pass criterion** | `SELECT status FROM sessions WHERE session_id = ?` returns `'closed'` |
| **Fail criterion** | Status is still `'active'`; exception |

### P8-03 · Session with stale `last_active` is expired `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Create a session; manually set `last_active` to 25 hours ago in the DB |
| **Input** | `expire_stale_sessions(inactivity_hours=24)` |
| **Expected output** | Status changes to `'expired'` |
| **Pass criterion** | `SELECT status FROM sessions WHERE session_id = ?` returns `'expired'`; function returns count of 1 |
| **Fail criterion** | Status unchanged; wrong count; exception |

### P8-04 · Recent session is not expired `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Create a session with `last_active` = 1 hour ago |
| **Input** | `expire_stale_sessions(inactivity_hours=24)` |
| **Expected output** | Status remains `'active'`; function returns count of 0 |
| **Pass criterion** | Status is still `'active'`; return value is 0 |
| **Fail criterion** | Session incorrectly expired |

### P8-05 · `get_recent_transcripts` excludes active session `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Create 1 active session + 2 closed sessions for `user_123`, each with 1 transcript row linked via `user_id` |
| **Input** | `get_recent_transcripts("user_123", limit=3)` (default: `exclude_active=True`) |
| **Expected output** | Exactly 2 transcripts (from the 2 closed sessions); active session's transcript excluded |
| **Pass criterion** | `len(result) == 2` and none of the returned `transcript_id` values belong to the active session |
| **Fail criterion** | Active session transcript appears; count wrong |

### P8-06 · `exclude_active=False` includes active session transcript `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Same as P8-05 |
| **Input** | `get_recent_transcripts("user_123", limit=3, exclude_active=False)` |
| **Expected output** | 3 transcripts (all three sessions) |
| **Pass criterion** | `len(result) == 3` |
| **Fail criterion** | Count != 3; active session still excluded |

---

## Phase 9 — Agent Orchestrator

### P9-01 · `handle_message()` returns a non-empty string `[INTG]`
| | |
| :--- | :--- |
| **Input** | `handle_message("rahul@acme.com", "I need help with my account")` |
| **Expected output** | Non-empty string response |
| **Pass criterion** | `isinstance(result, str) and len(result.strip()) > 0` |
| **Fail criterion** | Empty string; exception; wrong type |

### P9-02 · Context assembly runs only on first turn of a session `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Spy on `assemble_context()` call count. Call `handle_message()` twice in the same session |
| **Expected behavior** | `assemble_context()` called exactly once (first turn only); second turn reuses cached context |
| **Pass criterion** | `assemble_context_call_count == 1` after 2 messages |
| **Fail criterion** | Called 0 or 2 times |

### P9-03 · Write-path classifier fires after every turn `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Spy on `classify_and_save()` call count. Call `handle_message()` 3 times |
| **Expected behavior** | `classify_and_save()` called exactly 3 times |
| **Pass criterion** | `classify_call_count == 3` |
| **Fail criterion** | Any other count |

### P9-04 · Session is created and activity recorded `[INTG]`
| | |
| :--- | :--- |
| **Input** | `handle_message("rahul@acme.com", "hi")` |
| **Expected behavior** | A session row exists in the `sessions` table for `user_123` with `status = 'active'` and `last_active` updated |
| **Pass criterion** | `SELECT COUNT(*) FROM sessions WHERE user_id = 'user_123' AND status = 'active'` returns ≥ 1 |
| **Fail criterion** | No session row; wrong status; `last_active` not updated |

### P9-05 · End-to-end demo journey: prior issue is recognised `[INTG]`
| | |
| :--- | :--- |
| **Setup** | Run `setup_demo.py` to ingest all four transcripts and populate Mem0/Zep |
| **Input** | `handle_message("rahul@acme.com", "I'm having the rate limiting issue again")` |
| **Expected behavior** | Response references the prior issue or its history |
| **Pass criterion** | Response text contains at least one of: `"rate limit"`, `"rate limiting"`, `"previous"`, `"earlier"`, `"again"`, `"history"` (case-insensitive) |
| **Fail criterion** | Response treats user as entirely new with no context; none of the keywords present |

### P9-06 · End-to-end demo journey: step-by-step preference is applied `[EVAL]`
| | |
| :--- | :--- |
| **Setup** | Demo state populated (P9-05 setup). The `chat_user123_20240615` transcript contains `"walk me through this step by step"` |
| **Input** | `handle_message("rahul@acme.com", "How do I fix this?")` |
| **Expected behavior** | Response is structured as a numbered or step-by-step explanation |
| **Pass criterion** | Response contains numbered steps (e.g., `"1."`, `"2."`) OR contains `"step"` at least twice |
| **Fail criterion** | Response is a flat paragraph with no step structure |

---

## Phase 10 — Frontend Chat Interface

### P10-01 · Server starts and serves `index.html` `[UNIT]`
| | |
| :--- | :--- |
| **Scenario** | Start `server.py`, send `GET /` |
| **Expected output** | HTTP 200 response; response body contains `<!DOCTYPE html>` |
| **Pass criterion** | Status code 200; `"<!DOCTYPE"` in response body |
| **Fail criterion** | Any non-200 status; empty body; exception |

### P10-02 · `POST /chat` returns structured JSON `[INTG]`
| | |
| :--- | :--- |
| **Input** | `POST /chat` with body `{"identifier": "rahul@acme.com", "message": "hello"}` |
| **Expected output** | JSON with `"response"` (string) and `"context_sources"` (dict) keys |
| **Pass criterion** | `"response" in result and "context_sources" in result and isinstance(result["response"], str)` |
| **Fail criterion** | Missing keys; non-200 status; malformed JSON |

### P10-03 · `context_sources` reflects actual store population `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Cold-start user (no data in any store). Call `POST /chat` |
| **Expected behavior** | `context_sources` shows empty or `"None"` for all stores, not hardcoded labels |
| **Pass criterion** | None of the `context_sources` values is a non-empty source label (e.g., `"Mem0"`, `"Zep"`) when stores are empty |
| **Fail criterion** | Hardcoded `"Mem0"` label shown even though Mem0 returned nothing |

### P10-04 · Empty message is rejected at API level `[UNIT]`
| | |
| :--- | :--- |
| **Input** | `POST /chat` with body `{"identifier": "rahul@acme.com", "message": ""}` |
| **Expected output** | HTTP 400 |
| **Pass criterion** | Status code 400 |
| **Fail criterion** | 200 with garbage response; exception passed through as 500 |

---

## Phase 11 — Demo Data & End-to-End Scenario

### P11-01 · `setup_demo.py` runs to completion `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Run `python scripts/setup_demo.py` against a clean database |
| **Expected behavior** | Exits with code 0; prints a summary with non-zero counts for at least one of: Mem0 preferences saved, Zep state updates saved |
| **Pass criterion** | Exit code 0; summary output present |
| **Fail criterion** | Non-zero exit code; exception during ingestion or memory population |

### P11-02 · Demo is resettable `[INTG]`
| | |
| :--- | :--- |
| **Scenario** | Run `setup_demo.py` twice in a row against the same database |
| **Expected behavior** | Second run completes without errors (idempotent via `INSERT OR IGNORE` in SQLite) |
| **Pass criterion** | Exit code 0 on both runs; transcript count = 4 (not 8) |
| **Fail criterion** | Duplicate key error; transcript count doubles |

### P11-03 · All four "demo moment" assertions `[INTG]`

Run `handle_message("rahul@acme.com", "I'm having the rate limiting issue again")` after `setup_demo.py`:

| Assertion | Pass criterion | Fail criterion |
| :--- | :--- | :--- |
| Prior issue recognised | Response contains `"rate"` or `"issue"` | Generic "how can I help" opener only |
| Step-by-step preference applied | Response contains numbered steps or `"step"` (≥2 occurrences) | Flat paragraph, no steps |
| Transcript reference available | Asking `"What did I say in my email?"` returns content from `email_user123_20240612` | Response says it doesn't know |
| Identity resolved from email | `user_id` in session is `"user_123"` not `"unknown_user"` | Unknown user path taken |

---

## Phase 12 — Evals & Testing

### P12-01 · Grounding check: inferred fact → discard `[INTG]`
| | |
| :--- | :--- |
| **Input** | Turn: `[{"role":"user","content":"Can you help?"}]` |
| **Expected output** | `"discarded"` |
| **Pass criterion** | `result == "discarded"` |
| **Fail criterion** | `"mem0"` or `"zep"` returned for a content-free turn |

### P12-02 · Conflict policy — field-level merge with LLM-as-judge tone check `[EVAL]`

**Step 1 — Context object check:**

| | |
| :--- | :--- |
| **Setup** | Seed Mem0: `"prefers verbose, detailed updates"`. Seed Zep: `"account flagged for fast-path resolution"` |
| **Input** | `assemble_context("eval_user_p12", "my issue is still open")` |
| **Pass criterion** | `"verbose"` in `str(result["preferences"])` AND (`"fast-path"` or `"fast path"` or `"priority"`) in `str(result["account_state"])` |
| **Fail criterion** | Either field is empty; one store's data completely absent |

**Step 2 — Factual routing check:**

| | |
| :--- | :--- |
| **Input** | `generate_response()` with context from Step 1 |
| **Pass criterion** | Response text contains at least one of: `"fast-path"`, `"expedited"`, `"priority resolution"`, `"priority"` |
| **Fail criterion** | Response ignores the Zep state fact entirely |

**Step 3 — Tone routing check (LLM-as-judge):**

```python
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
```

| | |
| :--- | :--- |
| **Pass criterion** | `score >= 4` |
| **Fail criterion** | `score <= 3` |
| **Flakiness note** | If this eval is unstable across runs, lower acceptable threshold to `score >= 3` and document the change |

### P12-03 · Issue Log write scope invariant `[INTG]`

| Sub-test | Input | Pass criterion | Fail criterion |
| :--- | :--- | :--- | :--- |
| **Preference turn** | `"Please walk me through things step by step"` | Issue Log count unchanged | Count increases |
| **State/issue turn** | `"I'm still hitting rate limits after upgrading"` | Issue Log count +1; new row has non-empty `issue_type` | Count unchanged; or count +1 but `issue_type` is empty |
| **Discard turn** | `"ok"` | Issue Log count unchanged; Mem0/Zep not called | Either store written |

### P12-04 · Session boundary handling `[UNIT]`
| | |
| :--- | :--- |
| **Setup** | Create a session with `last_active` = 25 hours ago |
| **Steps** | 1. `expire_stale_sessions()` 2. `get_recent_transcripts("user_123", limit=3)` where the expired session has a transcript |
| **Pass criterion** | Session status = `'expired'`; transcript from expired session IS returned (expired sessions contribute to history window); transcript from active-but-not-yet-run session is NOT returned |
| **Fail criterion** | Session not expired; wrong transcript included/excluded |

### P12-05 · Cold-start `[INTG]`
| | |
| :--- | :--- |
| **Input** | `assemble_context("never_seen_user_abc_9999", "hello")` |
| **Expected output** | `{"preferences": {}, "account_state": {}, "issue_history": [], "transcript_excerpts": []}` exactly |
| **Pass criterion** | All four fields are empty; return type is `dict`; no exception |
| **Fail criterion** | Exception raised; non-empty field; wrong schema |

### P12-06 · Cross-user pattern threshold `[UNIT]`

| Sub-test | Setup | Input | Pass criterion |
| :--- | :--- | :--- | :--- |
| **Above threshold** | 10 rows, `issue_type = "api_rate_limit"`, within 7 days, 5 distinct users | `detect_patterns(threshold_count=10, window_days=7)` | `"api_rate_limit"` in result |
| **Below threshold** | 9 rows same setup | Same call | `result == []` |
| **Outside window** | 5 rows in window + 6 rows 8 days ago | Same call | `result == []` |
| **Single-user inflation** | 15 rows, same `user_id`, within 7 days | `detect_patterns(threshold_count=5, window_days=7)` — using `COUNT(DISTINCT user_id)` | `result == []` (only 1 distinct user; threshold on user count not event count) |

---

## Summary — Test Count by Phase

| Phase | Unit | Integration | Eval | Total |
| :--- | :---: | :---: | :---: | :---: |
| Phase 0 | 2 | 3 | 0 | 5 |
| Phase 1 | 6 | 0 | 0 | 6 |
| Phase 2 | 6 | 0 | 0 | 6 |
| Phase 3 | 1 | 2 | 0 | 3 |
| Phase 4 | 1 | 3 | 0 | 4* |
| Phase 5 | 1 | 3 | 0 | 4* |
| Phase 6 | 2 | 4 | 0 | 6 |
| Phase 7 | 4 | 0 | 0 | 4 |
| Phase 8 | 6 | 0 | 0 | 6 |
| Phase 9 | 0 | 5 | 1 | 6 |
| Phase 10 | 2 | 2 | 0 | 4 |
| Phase 11 | 0 | 3 | 0 | 3* |
| Phase 12 | 6 | 4 | 1 | 11 |
| **Total** | **37** | **29** | **2** | **68** |

> \* Some tests in Phases 4, 5, and 11 contain multiple assertions counted as a single scenario.

---

## Running the Full Test Suite

```bash
# Unit tests only (no credentials needed, fast)
pytest tests/unit/ -v

# Integration tests (requires .env with live API keys)
pytest tests/integration/ -v --timeout=60

# Eval tests (requires .env, slower — involves LLM-as-judge calls)
pytest tests/evals/ -v --timeout=120

# Full suite
pytest tests/ -v --timeout=120
```
