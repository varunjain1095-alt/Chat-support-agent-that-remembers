# Edge Cases — Customer Support Agent with Memory

> **Purpose:** A comprehensive catalogue of corner scenarios, boundary conditions, and failure modes across every component of the system. Each case documents the trigger, expected behavior, risk if unhandled, and the recommended mitigation. Use this document as the secondary test backlog after Phase 12 evals are complete.

---

## Table of Contents

1. [Identity Resolver](#1-identity-resolver)
2. [Transcript Ingestion](#2-transcript-ingestion)
3. [Memory Stores — Mem0](#3-memory-stores--mem0)
4. [Memory Stores — Zep](#4-memory-stores--zep)
5. [Context Assembler (Prep State)](#5-context-assembler-prep-state)
6. [Write-Path Classifier](#6-write-path-classifier)
7. [Session Lifecycle](#7-session-lifecycle)
8. [RAG Policy Retriever](#8-rag-policy-retriever)
9. [Agent Response Generator](#9-agent-response-generator)
10. [Cross-User Pattern Detector](#10-cross-user-pattern-detector)
11. [Orchestrator](#11-orchestrator)
12. [Frontend & API Layer](#12-frontend--api-layer)

---

## 1. Identity Resolver

### EC-IR-01 — Unknown identifier
| | |
| :--- | :--- |
| **Trigger** | An inbound identifier (email, phone, session token) is not in the mapping dict |
| **Expected behavior** | Returns `"unknown_user"`. System treats this as a cold-start new user — all memory stores return empty, no crash |
| **Risk if unhandled** | `None` key propagated to Mem0/Zep queries; SDK throws an error mid-session |
| **Mitigation** | Explicit `"unknown_user"` fallback already in the mapping. Orchestrator must guard against `user_id == "unknown_user"` and optionally route to a new-user onboarding flow |

### EC-IR-02 — Same identifier in multiple formats
| | |
| :--- | :--- |
| **Trigger** | User contacts via `+91-9876543210` (with country code) in one channel, and `09876543210` (local format) in another |
| **Expected behavior** | Both resolve to the same `user_id`. If either format is missing from the mapping, they resolve to different users |
| **Risk if unhandled** | Split user identity — two separate Mem0/Zep profiles built for the same person; preference from one session not visible in another |
| **Mitigation** | Normalise all phone numbers to E.164 format before mapping lookup. Document this normalisation step in `identity_resolver.py` |

### EC-IR-03 — Identifier is None or empty string
| | |
| :--- | :--- |
| **Trigger** | Inbound message arrives with a missing or null identifier field |
| **Expected behavior** | Function raises a `ValueError` (or returns `"unknown_user"` + logs a warning) — never crashes silently |
| **Risk if unhandled** | `None.get(...)` call causes `AttributeError`; unhandled exception crashes the orchestrator |
| **Mitigation** | Add an explicit guard at the top of `resolve_user_id()`: `if not identifier: return "unknown_user"` |

### EC-IR-04 — Case sensitivity in email identifiers
| | |
| :--- | :--- |
| **Trigger** | User sends `Rahul@Acme.com` but mapping key is `rahul@acme.com` |
| **Expected behavior** | Resolves to `user_123` (case-insensitive match) |
| **Risk if unhandled** | Resolution fails; user treated as new; split identity |
| **Mitigation** | Lowercase the identifier before the mapping lookup: `identifier = identifier.strip().lower()` |

---

## 2. Transcript Ingestion

### EC-TI-01 — Duplicate transcript ingestion
| | |
| :--- | :--- |
| **Trigger** | `ingest_transcript()` is called twice for the same file (e.g., re-running the ingestion script) |
| **Expected behavior** | SQLite PRIMARY KEY constraint on `transcript_id` prevents the duplicate row; function logs a warning and continues |
| **Risk if unhandled** | Duplicate rows inflate transcript counts; `get_recent_transcripts(limit=3)` may return duplicate entries instead of three distinct sessions |
| **Mitigation** | Use `INSERT OR IGNORE` instead of plain `INSERT`. Log a warning on ignore. |

### EC-TI-02 — Malformed flat file JSON
| | |
| :--- | :--- |
| **Trigger** | A raw transcript JSON file is truncated or invalid (e.g., disk write interrupted mid-file) |
| **Expected behavior** | `ingest_transcript()` raises a `json.JSONDecodeError`, logs the filename, and skips it — does not crash the whole ingestion run |
| **Risk if unhandled** | One bad file stops the entire ingestion script; subsequent transcripts never load |
| **Mitigation** | Wrap each file read in a `try/except json.JSONDecodeError`. Log the bad file path. Return a failure status per file rather than raising |

### EC-TI-03 — Transcript with missing required fields
| | |
| :--- | :--- |
| **Trigger** | JSON file is valid but missing `channel` or `timestamp` fields |
| **Expected behavior** | Validation raises a clear error before attempting the INSERT; file is skipped and logged |
| **Risk if unhandled** | `NOT NULL` SQLite constraint throws an unhandled exception; or a `None` timestamp corrupts ordering |
| **Mitigation** | Validate required fields after JSON parse, before INSERT. Required fields: `transcript_id`, `user_id`, `channel`, `timestamp`, `content` |

### EC-TI-04 — Transcript for an unknown user
| | |
| :--- | :--- |
| **Trigger** | A transcript file contains an identifier that `resolve_user_id()` cannot map |
| **Expected behavior** | Logged under `user_id = "unknown_user"`. Orchestrator never surfaces `unknown_user` records in context assembly |
| **Risk if unhandled** | `unknown_user` transcripts accumulate silently and could be returned as context for any new user hitting the cold-start path |
| **Mitigation** | Filter `WHERE user_id != 'unknown_user'` in `get_recent_transcripts()` |

### EC-TI-05 — Transcripts arrive out of chronological order
| | |
| :--- | :--- |
| **Trigger** | Ingestion script processes files in filesystem order rather than timestamp order |
| **Expected behavior** | `get_recent_transcripts()` orders by `timestamp DESC` regardless of ingestion order — correct results |
| **Risk if unhandled** | If ordering relies on rowid/insertion order rather than `timestamp`, the "last 3 sessions" window is wrong |
| **Mitigation** | Always order by `timestamp DESC` in the SQL query, not `rowid DESC` |

### EC-TI-06 — Very large transcript (token length)
| | |
| :--- | :--- |
| **Trigger** | A phone transcript is extremely long (e.g., 2-hour call, >100K tokens of content) |
| **Expected behavior** | Content is stored in full in SQLite. When returned as a `transcript_excerpt`, the orchestrator truncates it to a reasonable excerpt length before including it in the context object |
| **Risk if unhandled** | Full transcript injected into the context object blows the Claude context window budget |
| **Mitigation** | `get_recent_transcripts()` truncates `content` to a configurable `max_excerpt_chars` (e.g., 1500 chars) when building the `transcript_excerpts` block |

---

## 3. Memory Stores — Mem0

### EC-M0-01 — Mem0 API timeout / unavailable
| | |
| :--- | :--- |
| **Trigger** | Mem0 platform returns a timeout or 5xx error during `search_preferences()` |
| **Expected behavior** | `search_preferences()` catches the exception, logs a warning, and returns an empty dict. Context assembly continues with `preferences: {}` |
| **Risk if unhandled** | Unhandled exception crashes the prep-state parallel fetch; entire session init fails |
| **Mitigation** | Wrap Mem0 calls in `try/except` with a specific timeout. Return empty dict on failure. Log the error with enough context to debug |

### EC-M0-02 — Mem0 returns stale / conflicting preference
| | |
| :--- | :--- |
| **Trigger** | User expressed two contradictory preferences in different sessions (e.g., `"prefer concise"` then later `"prefer step-by-step"`) and Mem0 returns both |
| **Expected behavior** | Mem0's own deduplication should handle this; if both are returned, the Context Assembler's synthesizer LLM picks the most recent signal (using timestamps if available in Mem0's output, or the last-written entry) |
| **Risk if unhandled** | Contradictory style signals in the prompt cause the agent to apply inconsistent tone within a single response |
| **Mitigation** | Instruct the synthesizer LLM: *"If multiple preferences conflict for the same attribute, use the most recently recorded one"* |

### EC-M0-03 — Mem0 `add()` called with an empty turn
| | |
| :--- | :--- |
| **Trigger** | Write-path classifier calls `save_preference()` with an empty or whitespace-only messages list |
| **Expected behavior** | `save_preference()` validates the input and skips the Mem0 call; logs a warning |
| **Risk if unhandled** | Mem0 SDK may throw a validation error or store an empty memory entry |
| **Mitigation** | Guard: `if not turn or not any(m.get("content", "").strip() for m in turn): return` |

### EC-M0-04 — Mem0 search returns no results (first-time user)
| | |
| :--- | :--- |
| **Trigger** | A new user has no stored preferences; `search_preferences()` returns an empty list |
| **Expected behavior** | Returns `{}`. Context Assembler puts `"preferences": {}` in the schema. Agent responds with neutral, default tone |
| **Risk if unhandled** | Code tries to access `preferences["communication_style"]` before checking for emptiness; `KeyError` |
| **Mitigation** | All downstream code must use `.get()` for accessing preference fields, never direct key access |

---

## 4. Memory Stores — Zep

### EC-ZEP-01 — Zep API timeout / unavailable
| | |
| :--- | :--- |
| **Trigger** | Zep Cloud returns a timeout or 5xx error during `search_state()` |
| **Expected behavior** | `search_state()` returns empty dict. Context assembly continues with `account_state: {}` and `issue_history: []` |
| **Risk if unhandled** | Same as EC-M0-01 — entire prep state crashes |
| **Mitigation** | Same pattern — `try/except`, empty return, log warning |

### EC-ZEP-02 — Zep returns fact that has since been superseded
| | |
| :--- | :--- |
| **Trigger** | User upgraded from Free to Pro, but Zep graph still surfaces the Free plan node alongside the Pro node due to graph traversal returning both |
| **Expected behavior** | Synthesizer LLM is instructed to use the most recent timestamped fact when two versions of the same attribute exist |
| **Risk if unhandled** | Agent tells a Pro user they're on Free plan; erodes trust immediately |
| **Mitigation** | Instruct synthesizer: *"For account_state fields, prefer the node with the most recent timestamp if duplicates exist for the same attribute"* |

### EC-ZEP-03 — Zep `session_id` collision
| | |
| :--- | :--- |
| **Trigger** | Two concurrent sessions for the same user have overlapping `session_id` values (e.g., if IDs are generated without sufficient entropy) |
| **Expected behavior** | `save_state()` writes to the correct session. Cross-contamination between sessions does not occur |
| **Risk if unhandled** | Memory from Session B written under Session A's ID; user sees someone else's conversation history |
| **Mitigation** | Generate `session_id` as `f"{user_id}_{uuid4()}"` — combine user scope with UUID to prevent collision |

### EC-ZEP-04 — Zep graph search returns unrelated entities
| | |
| :--- | :--- |
| **Trigger** | `graph.search(query="my issue", user_id=user_id)` returns nodes from a broad semantic match that are not related to the current query |
| **Expected behavior** | Synthesizer LLM is constrained to only populate `account_state` and `issue_history` fields from the Zep output — it cannot invent or expand on it |
| **Risk if unhandled** | Irrelevant Zep nodes inflate the context object with noise; agent hallucinates issue history that doesn't apply |
| **Mitigation** | The synthesizer prompt's "no inference beyond what is given" constraint is the primary guard. Secondary: score and filter Zep results by relevance threshold before passing to synthesizer |

---

## 5. Context Assembler (Prep State)

### EC-CA-01 — All three stores return empty (cold-start)
| | |
| :--- | :--- |
| **Trigger** | Brand new user; Mem0, Zep, and SQLite all return empty for `user_id` |
| **Expected behavior** | Context object returned: `{"preferences": {}, "account_state": {}, "issue_history": [], "transcript_excerpts": []}`. Agent treats user as new |
| **Risk if unhandled** | Code errors on empty inputs before reaching the synthesizer; or agent behaves unexpectedly with an empty prompt block |
| **Mitigation** | Tested explicitly in Phase 12.5. Synthesizer must handle empty inputs gracefully — the schema is already the correct empty structure |

### EC-CA-02 — Synthesizer LLM returns invalid JSON
| | |
| :--- | :--- |
| **Trigger** | Claude's scoped synthesis call returns malformed JSON (e.g., trailing comma, truncated output, or preamble text before the JSON) |
| **Expected behavior** | `assemble_context()` catches the JSON parse error, logs it, and returns the empty schema as a safe fallback |
| **Risk if unhandled** | `json.loads()` raises `JSONDecodeError`; prep state crashes; no response is generated |
| **Mitigation** | Wrap `json.loads()` in `try/except`. On failure, log the raw output for debugging and return the empty schema |

### EC-CA-03 — Synthesizer LLM adds fields not in the schema
| | |
| :--- | :--- |
| **Trigger** | Claude adds an extra field (e.g., `"sentiment"`) not in the fixed four-field schema |
| **Expected behavior** | The extra field is stripped. Only the four canonical fields are passed downstream |
| **Risk if unhandled** | Unknown fields in the context object may confuse the agent prompt or downstream code expecting only the fixed schema |
| **Mitigation** | After parsing, filter the output dict to only the four known keys: `preferences`, `account_state`, `issue_history`, `transcript_excerpts` |

### EC-CA-04 — Parallel fetch: one store hangs, others complete
| | |
| :--- | :--- |
| **Trigger** | Mem0 takes >10s to respond while Zep and SQLite complete in <1s |
| **Expected behavior** | A per-source timeout (e.g., 5s) causes the slow source to return an empty result. Context assembly proceeds with partial data |
| **Risk if unhandled** | Session init hangs indefinitely; user sees no response |
| **Mitigation** | Each parallel fetch task runs with an explicit timeout. `ThreadPoolExecutor` with `timeout=` in `.result()` call or `asyncio.wait_for()` |

### EC-CA-05 — Context object exceeds token budget
| | |
| :--- | :--- |
| **Trigger** | Three very large transcript excerpts + verbose Zep graph output together push the context object over Claude's context window limit |
| **Expected behavior** | The `transcript_excerpts` block is the last-priority truncation target — trim longest excerpts first. `preferences` and `account_state` are never truncated |
| **Risk if unhandled** | Claude API returns a `context_length_exceeded` error; session fails |
| **Mitigation** | Measure assembled context token count before the generation call. If over budget, progressively truncate `transcript_excerpts` content (not the number of entries) |

---

## 6. Write-Path Classifier

### EC-WC-01 — Classifier LLM returns invalid JSON
| | |
| :--- | :--- |
| **Trigger** | The classifier Claude call returns malformed JSON or missing required fields (`action`, `content`) |
| **Expected behavior** | Parse failure → treat as `"discard"`. Log the raw output for debugging |
| **Risk if unhandled** | `KeyError` on `result["action"]`; write-path crashes; session hangs |
| **Mitigation** | Wrap classifier output parsing in `try/except`. Default to `discard` on any parse failure |

### EC-WC-02 — Classifier action is `save_zep` but `issue_type` is absent
| | |
| :--- | :--- |
| **Trigger** | Classifier correctly routes to Zep (state/fact) but doesn't return an `issue_type` because the turn describes an account change, not an issue |
| **Expected behavior** | Zep save proceeds normally. Issue Log write is skipped (only write to Issue Log when `issue_type` is present) |
| **Risk if unhandled** | Attempt to write `None` to `issue_log.issue_type` violates the `NOT NULL` constraint |
| **Mitigation** | Issue Log write is guarded: `if result.get("issue_type"): write_to_issue_log(...)` |

### EC-WC-03 — Classifier hallucinates a preference not in the turn
| | |
| :--- | :--- |
| **Trigger** | User says `"Ok thanks"`. Classifier incorrectly extracts `"prefers short acknowledgements"` |
| **Expected behavior** | Grounding check fails — the extracted preference cannot be pointed to verbatim in the turn → discard |
| **Risk if unhandled** | Hallucinated preferences accumulate in Mem0 and drift the agent's behavior away from what the user actually expressed |
| **Mitigation** | The grounding check is the primary control. If flaky, make the grounding check a separate, stricter Claude call with a lower temperature |

### EC-WC-04 — Same fact extracted and saved on every turn
| | |
| :--- | :--- |
| **Trigger** | User's account state is `"Pro plan"` and Zep already has this fact. The classifier re-extracts it from every message that mentions the account |
| **Expected behavior** | Zep's graph is idempotent for unchanged facts — saving the same fact again should not create a duplicate node |
| **Risk if unhandled** | Issue Log accumulates duplicate `issue_type` entries, inflating pattern detection counts |
| **Mitigation** | Issue Log write should check if the same `(user_id, issue_type)` was already written in the current session before writing again |

### EC-WC-05 — Classifier runs on a very short turn
| | |
| :--- | :--- |
| **Trigger** | User sends `"ok"` or `"yes"` |
| **Expected behavior** | Classifier returns `discard` — no preference or fact expressible from a single-word acknowledgement |
| **Risk if unhandled** | Classifier attempts to save something meaningless; Mem0 accumulates noise |
| **Mitigation** | Add a pre-check: if turn content length < 10 characters, skip the classifier call entirely and return `discard` |

### EC-WC-06 — Write-path runs during transcript ingestion on policy-neutral content
| | |
| :--- | :--- |
| **Trigger** | An ingested email transcript contains only pleasantries (greetings, sign-offs) and no memory-worthy signals |
| **Expected behavior** | Classifier returns `discard` for these segments. No Mem0/Zep writes. No Issue Log entry |
| **Risk if unhandled** | Pleasantries like `"Best regards"` trigger a Mem0 save with a hallucinated preference |
| **Mitigation** | Same grounding check applies during async ingestion as during live chat |

---

## 7. Session Lifecycle

### EC-SL-01 — Concurrent messages in the same session
| | |
| :--- | :--- |
| **Trigger** | User sends two messages in rapid succession before the first response is generated |
| **Expected behavior** | Second message queued or rejected until first turn completes. Conversation history remains consistent |
| **Risk if unhandled** | Race condition: both messages trigger prep-state simultaneously; duplicate context assembly; write-path fires twice on partial history |
| **Mitigation** | Per-session mutex or queue in the orchestrator. Only one `handle_message()` executes at a time per session |

### EC-SL-02 — Session expiry fires mid-conversation
| | |
| :--- | :--- |
| **Trigger** | `expire_stale_sessions()` runs on a background thread and marks a session `expired` while the user is mid-turn (e.g., user left the tab open but didn't send a message for 24h+) |
| **Expected behavior** | The session is expired. The next `handle_message()` call from that user creates a new session and runs prep-state fresh |
| **Risk if unhandled** | Orchestrator continues writing turns to an expired `session_id` in Zep; state gets written to a ghost session |
| **Mitigation** | `handle_message()` always calls `get_active_session()` before processing. If the session it has in memory is no longer `active`, it creates a new one |

### EC-SL-03 — User closes session, then immediately re-opens
| | |
| :--- | :--- |
| **Trigger** | User closes the chat (marking issue resolved), then sends a new message within seconds |
| **Expected behavior** | A new session is created. The closed session's data is now in the historical window for prep-state. Context assembler picks it up in `transcript_excerpts` if it's within the last 3 sessions |
| **Risk if unhandled** | Old session accidentally reactivated; state writes go to the closed session |
| **Mitigation** | `close_session()` is irreversible. `get_active_session()` will return `None` after a close, forcing a new session |

### EC-SL-04 — `get_recent_transcripts` called when user has only active sessions (no closed/expired yet)
| | |
| :--- | :--- |
| **Trigger** | Brand new user sends their very first message. No closed or expired sessions exist — the filter `WHERE status IN ('closed', 'expired')` returns nothing |
| **Expected behavior** | Returns `[]`. Context Assembler proceeds with `transcript_excerpts: []`. Handled as cold-start |
| **Risk if unhandled** | None from the query itself, but downstream code must handle an empty list gracefully |
| **Mitigation** | Covered by the cold-start path. No special handling needed beyond an empty list return |

### EC-SL-05 — Clock skew between server and DB
| | |
| :--- | :--- |
| **Trigger** | System clock is adjusted (e.g., NTP sync) while a session is active, causing `last_active` timestamps to be inconsistent |
| **Expected behavior** | `expire_stale_sessions()` uses `CURRENT_TIMESTAMP` from SQLite consistently; expiry calculation is stable |
| **Risk if unhandled** | A session could be expired prematurely or never expire if the clock jumps |
| **Mitigation** | Use SQLite's `CURRENT_TIMESTAMP` for all time calculations rather than Python's `datetime.now()` — keeps the clock source consistent |

---

## 8. RAG Policy Retriever

### EC-RAG-01 — Query has no relevant policy match
| | |
| :--- | :--- |
| **Trigger** | User asks something completely outside the policy docs (e.g., `"What's the weather?"`) |
| **Expected behavior** | `retrieve()` returns an empty list or very low-scoring chunks. Agent responds from memory context only, without hallucinating a policy |
| **Risk if unhandled** | Agent invents a policy that doesn't exist; presents it confidently to the user |
| **Mitigation** | Set a minimum cosine similarity threshold. If no chunk exceeds it, pass an empty `[POLICY CONTEXT]` section rather than low-quality chunks |

### EC-RAG-02 — Embedding model API unavailable
| | |
| :--- | :--- |
| **Trigger** | OpenAI embedding API returns a 503 during query-time retrieval |
| **Expected behavior** | `retrieve()` returns an empty list. Agent responds from memory context only, without RAG grounding |
| **Risk if unhandled** | Unhandled exception crashes the response generation path |
| **Mitigation** | Wrap embedding calls in `try/except`. Return `[]` on failure. Log the error |

### EC-RAG-03 — Vector index is missing or corrupt
| | |
| :--- | :--- |
| **Trigger** | `vector_store/` directory is empty or the index file is corrupt (e.g., first run before `build_index()` was called) |
| **Expected behavior** | `retrieve()` detects missing index, logs an error, and returns `[]` — does not crash |
| **Risk if unhandled** | `FileNotFoundError` or index load exception crashes the server on startup |
| **Mitigation** | On startup, check if the index exists. If not, run `build_index()` automatically or raise a clear startup error with instructions |

### EC-RAG-04 — Policy doc updated but index not rebuilt
| | |
| :--- | :--- |
| **Trigger** | `refund_policy.md` is edited but `build_index()` is not re-run |
| **Expected behavior** | RAG continues to serve stale chunks. This is a known limitation — not a crash, but stale behavior |
| **Risk if unhandled** | Agent gives outdated policy answers after a policy change |
| **Mitigation** | Document that `build_index()` must be re-run after any policy doc change. Optionally: hash the policy files and auto-detect staleness on startup |

### EC-RAG-05 — Top-k chunks are all from the same document
| | |
| :--- | :--- |
| **Trigger** | Query closely matches one policy doc, causing all `top_k` results to come from it, missing relevant content from other docs |
| **Expected behavior** | Agent answer is grounded in that one doc, which may be correct. No crash |
| **Risk if unhandled** | A nuanced issue that requires both the refund policy and escalation rules gets only one perspective |
| **Mitigation** | Consider max-marginal relevance (MMR) retrieval or per-document retrieval caps as a future improvement. Out of scope for initial build |

---

## 9. Agent Response Generator

### EC-AG-01 — Claude API rate limit hit
| | |
| :--- | :--- |
| **Trigger** | A burst of concurrent sessions hits the Anthropic rate limit; API returns 429 |
| **Expected behavior** | Orchestrator catches the 429, waits with exponential backoff, retries up to 3 times |
| **Risk if unhandled** | Unhandled exception; session crashes; user gets an error instead of a response |
| **Mitigation** | Implement retry logic with exponential backoff: `[1s, 2s, 4s]`. After 3 failures, return a graceful error message to the user |

### EC-AG-02 — Response generation produces an empty string
| | |
| :--- | :--- |
| **Trigger** | Claude API call succeeds but returns an empty `content` block (rare but documented edge case) |
| **Expected behavior** | Orchestrator detects empty response, logs the event, and returns a fallback message: `"I'm sorry, I wasn't able to generate a response. Please try again."` |
| **Risk if unhandled** | Empty string returned to the user; confusing UI state |
| **Mitigation** | Post-generation guard: `if not response.strip(): return FALLBACK_MESSAGE` |

### EC-AG-03 — Response references a fact not in the context object
| | |
| :--- | :--- |
| **Trigger** | Claude hallucinates a detail (e.g., a specific ticket number) not present in `account_state` or `issue_history` |
| **Expected behavior** | This is a known LLM limitation. The system does not have an automated hallucination detector at response time |
| **Risk if unhandled** | Agent presents fabricated information as fact; erodes user trust |
| **Mitigation** | Prompt engineering: *"Only state facts that appear in the [USER CONTEXT] block. Do not infer or invent ticket numbers, dates, or account details not provided."* |

### EC-AG-04 — Context window overflow at generation time
| | |
| :--- | :--- |
| **Trigger** | The assembled prompt (context object + policy chunks + conversation history + current message) exceeds Claude's max context length |
| **Expected behavior** | Truncation priority: conversation history oldest turns first, then `transcript_excerpts`, then policy chunks. `preferences` and `account_state` are never truncated |
| **Risk if unhandled** | API returns `context_length_exceeded`; response fails |
| **Mitigation** | Token-count the full prompt before sending. Apply truncation in priority order until under limit |

---

## 10. Cross-User Pattern Detector

### EC-PD-01 — Issue Log write during a preference-classified turn
| | |
| :--- | :--- |
| **Trigger** | A bug causes the write-path classifier to write to the Issue Log even when the classification is `save_mem0` |
| **Expected behavior** | Issue Log must not receive any entries from the preference branch. Enforced by branch-level guard in classifier |
| **Risk if unhandled** | Preference data pollutes the Issue Log; `detect_patterns()` fires false positives on non-issue signals |
| **Mitigation** | EC-WC-02 mitigation applies. Additionally, Phase 12.3 eval verifies this invariant at the integration level |

### EC-PD-02 — Pattern detection query runs during a write
| | |
| :--- | :--- |
| **Trigger** | `detect_patterns()` runs concurrently with an active Issue Log insert |
| **Expected behavior** | SQLite's serialized write model means reads see a consistent snapshot. No partial-write reads |
| **Risk if unhandled** | In WAL mode, readers may see data mid-transaction |
| **Mitigation** | Use default SQLite journal mode (DELETE) for this project's scale. WAL is unnecessary |

### EC-PD-03 — All issues from a single user inflate the pattern count
| | |
| :--- | :--- |
| **Trigger** | One very active user opens 15 tickets for the same `issue_type` within 7 days, triggering a threshold that should represent a multi-user pattern |
| **Expected behavior** | Pattern detection query should ideally count distinct users, not raw event counts |
| **Risk if unhandled** | A single power user's activity triggers a false cross-user pattern alert |
| **Mitigation** | Update the query to count `COUNT(DISTINCT user_id)` rather than `COUNT(*)`. Flag as a known limitation in the initial build; fix in a follow-up |

### EC-PD-04 — `issue_type` keyword is too generic
| | |
| :--- | :--- |
| **Trigger** | Classifier extracts `issue_type = "error"` for wildly different problems (billing error, API error, login error) |
| **Expected behavior** | Pattern detection aggregates on a generic term; every issue appears to cluster |
| **Risk if unhandled** | False positive alert for a pattern that doesn't exist |
| **Mitigation** | Define a controlled vocabulary of `issue_type` values in the classifier system prompt (e.g., `"billing_error"`, `"api_rate_limit"`, `"login_failure"`). Classifier must return one of these values, not free text |

---

## 11. Orchestrator

### EC-OR-01 — Orchestrator receives a message for an unknown user mid-conversation
| | |
| :--- | :--- |
| **Trigger** | Session was started as `user_123` but a subsequent message arrives with an unrecognised identifier |
| **Expected behavior** | Identity resolver returns `"unknown_user"`. Orchestrator creates a new session for `"unknown_user"`. Existing `user_123` session is unaffected |
| **Risk if unhandled** | Cross-user context leak if the orchestrator reuses the existing session |
| **Mitigation** | Session is always looked up by `user_id` after resolution — different `user_id` = different session |

### EC-OR-02 — Write-path classifier fails after a successful response
| | |
| :--- | :--- |
| **Trigger** | The agent generates a response successfully, but the async classifier call throws an uncaught exception |
| **Expected behavior** | The response is already returned to the user. The classifier failure is logged. Memory is not updated for this turn |
| **Risk if unhandled** | Crash propagates back to the response layer; user sees an error despite the response being generated |
| **Mitigation** | Run the classifier in a fire-and-forget async wrapper with its own `try/except`. Classifier failures must never affect the user-facing response |

### EC-OR-03 — Prep state assembles context, but user sends a follow-up before context is ready
| | |
| :--- | :--- |
| **Trigger** | Context assembly takes 3 seconds; user sends a follow-up message at 1 second |
| **Expected behavior** | Follow-up message is queued. Context assembly completes first. Both messages are processed in order using the same context object |
| **Risk if unhandled** | Second message triggers another prep-state run; two context assembly calls run in parallel |
| **Mitigation** | Context assembly result is cached in memory for the duration of the session. After the first prep-state, subsequent turns reuse the cached context object (updated incrementally via write-path) |

### EC-OR-04 — Server restarts mid-session
| | |
| :--- | :--- |
| **Trigger** | The Python HTTP server crashes and restarts while a user is in an active session |
| **Expected behavior** | In-memory conversation history is lost. Session status in SQLite remains `'active'` (unless the restart takes >24h). User's next message triggers a fresh prep-state run, which recovers context from Mem0, Zep, and SQLite |
| **Risk if unhandled** | Stale session ID from the client hits a fresh server that has no in-memory history; orchestrator creates a new session while old one is still `'active'` in DB |
| **Mitigation** | On orchestrator startup: run `expire_stale_sessions()`. For shorter restarts: treat `get_active_session()` returning an existing session as valid and re-run prep-state |

---

## 12. Frontend & API Layer

### EC-FE-01 — `/chat` endpoint receives a malformed request body
| | |
| :--- | :--- |
| **Trigger** | Frontend sends a request with missing `message` field or invalid JSON |
| **Expected behavior** | Server returns HTTP 400 with a clear error message. Does not crash |
| **Risk if unhandled** | `KeyError` on `request.json["message"]`; unhandled exception returns HTTP 500 |
| **Mitigation** | Validate request body fields before calling `handle_message()`. Return structured error JSON |

### EC-FE-02 — User submits an empty message
| | |
| :--- | :--- |
| **Trigger** | User clicks Send with no text (or only whitespace) |
| **Expected behavior** | Frontend prevents submission (client-side guard). Server-side also rejects: returns HTTP 400 if an empty message reaches the API |
| **Risk if unhandled** | Empty message passed to Claude; response is nonsensical or API throws an error |
| **Mitigation** | Client-side: disable Send button when input is empty. Server-side: `if not user_message.strip(): return 400` |

### EC-FE-03 — Memory Source Panel shows wrong sources
| | |
| :--- | :--- |
| **Trigger** | `context_sources` in the API response is hardcoded or stale rather than reflecting actual sources used for the current turn |
| **Expected behavior** | `context_sources` reflects which fields in the context object were actually populated vs. empty for this specific turn |
| **Risk if unhandled** | User sees "Zep" in the source panel for a cold-start session where Zep returned nothing — misleading |
| **Mitigation** | Build `context_sources` dynamically: for each field in the context object, label it with its source only if the field is non-empty. Empty fields are shown as `"None"` or omitted from the panel |

### EC-FE-04 — Long agent response causes UI overflow
| | |
| :--- | :--- |
| **Trigger** | Claude generates a very long step-by-step response (e.g., 800 words) |
| **Expected behavior** | Chat bubble expands with a scrollable area. Page layout does not break |
| **Risk if unhandled** | Message bubble overflows its container; text spills outside the chat window |
| **Mitigation** | CSS: `overflow-y: auto; max-height: <value>` on message bubbles. Test with a 1000-word response during frontend development |

### EC-FE-05 — API response latency > 10 seconds
| | |
| :--- | :--- |
| **Trigger** | Context assembly + RAG + Claude generation takes longer than expected (e.g., slow Mem0/Zep response + long response generation) |
| **Expected behavior** | Frontend shows a typing indicator / loading state. User is not left staring at a blank chat |
| **Risk if unhandled** | User thinks the app has frozen; sends duplicate messages; triggers multiple overlapping requests |
| **Mitigation** | Show a loading spinner on Send click. Disable input field until response arrives. Implement a 30s client-side timeout with a friendly error if exceeded |
