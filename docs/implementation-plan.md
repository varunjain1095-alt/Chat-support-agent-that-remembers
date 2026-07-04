# Implementation Plan — Customer Support Agent with Memory

> **Purpose:** Phase-by-phase build plan derived from `architecture.md` and `context.md`. Each phase has a clear goal, discrete tasks, deliverables, and a definition of done. Phases are ordered so each one produces a testable artifact before the next begins — no phase depends on work from a later phase.

---

## Table of Contents

- [Phase 0 — Environment & Project Scaffold](#phase-0--environment--project-scaffold)
- [Phase 1 — Identity Resolver](#phase-1--identity-resolver)
- [Phase 2 — Transcript Ingestion Pipeline](#phase-2--transcript-ingestion-pipeline)
- [Phase 3 — Memory Store Integration (Mem0 + Zep)](#phase-3--memory-store-integration-mem0--zep)
- [Phase 4 — Context Assembler (Prep State)](#phase-4--context-assembler-prep-state)
- [Phase 5 — Agent Response Generator + RAG Policy Retriever](#phase-5--agent-response-generator--rag-policy-retriever)
- [Phase 6 — Write-Path Classifier](#phase-6--write-path-classifier)
- [Phase 7 — Cross-User Pattern Detector](#phase-7--cross-user-pattern-detector)
- [Phase 8 — Session Lifecycle Management](#phase-8--session-lifecycle-management)
- [Phase 9 — Agent Orchestrator (Full Integration)](#phase-9--agent-orchestrator-full-integration)
- [Phase 10 — Frontend Chat Interface](#phase-10--frontend-chat-interface)
- [Phase 11 — Demo Data & End-to-End Scenario](#phase-11--demo-data--end-to-end-scenario)
- [Phase 12 — Evals & Testing](#phase-12--evals--testing)

---

## Phase 0 — Environment & Project Scaffold

**Goal:** A clean, isolated, reproducible development environment with all dependencies installed and credentials wired up. Nothing is built here — this phase exists so every subsequent phase starts from a known-good baseline.

### Tasks

- [ ] Create a new Docker container with a non-conflicting port (avoid `5433`, already used by existing projects)
- [ ] Create the project directory structure:
  ```
  customer-support-agent/
  ├── .env                      # API credentials (already created)
  ├── .gitignore                # (already created)
  ├── docs/
  │   ├── architecture.md
  │   └── context.md
  ├── data/
  │   ├── raw/                  # Flat file transcript archive
  │   └── policy/               # Company policy docs for RAG
  ├── db/
  │   └── transcripts.db        # SQLite (auto-created on first run)
  ├── src/
  │   ├── identity_resolver.py
  │   ├── ingestion.py
  │   ├── memory.py
  │   ├── context_assembler.py
  │   ├── rag.py
  │   ├── write_classifier.py
  │   ├── pattern_detector.py
  │   ├── session.py
  │   └── orchestrator.py
  ├── frontend/
  │   └── index.html
  ├── tests/
  └── requirements.txt
  ```
- [ ] Create `requirements.txt` with pinned dependencies:
  ```
  anthropic
  mem0ai
  zep-cloud
  openai            # for text-embedding-3-small
  python-dotenv
  ```
- [ ] Install dependencies inside the container: `pip install -r requirements.txt`
- [ ] Create a `config.py` or `settings.py` that loads all env vars via `python-dotenv` and exposes typed constants — all other modules import from here, never directly from `os.environ`
- [ ] Smoke-test all three API connections (Claude, Mem0, Zep) with minimal ping calls — confirm keys are valid and SDKs initialize cleanly

### Deliverable
A runnable Python environment where `python -c "from config import *; print('OK')"` succeeds and all three API clients initialize without errors.

### Definition of Done
- [ ] Docker container starts cleanly
- [ ] `pip install -r requirements.txt` completes with no errors
- [ ] All three API clients (Claude, Mem0, Zep) initialize from `.env` without errors
- [ ] Project directory structure matches the scaffold above

---

## Phase 1 — Identity Resolver

**Goal:** A standalone, tested module that maps any inbound channel identifier to a canonical `user_id`. All other modules depend on this — build it first.

### Tasks

- [ ] Create `src/identity_resolver.py` with the `resolve_user_id(identifier: str) -> str` function
- [ ] Implement the deterministic mapping dict for the demo user (`rahul@acme.com`, `+91-9876543210`, `sess_abc_789` → `user_123`)
- [ ] Add `logging.info()` on every resolution call (the log is the visible proof the seam exists)
- [ ] Return `"unknown_user"` for any identifier not in the mapping
- [ ] Write unit tests in `tests/test_identity_resolver.py`:
  - Known email resolves correctly
  - Known phone resolves correctly
  - Known session token resolves correctly
  - Unknown identifier returns `"unknown_user"`

### Deliverable
`identity_resolver.py` + passing unit tests.

### Definition of Done
- [ ] All four unit test cases pass
- [ ] Resolution events appear in logs with the format: `Identity resolved: <identifier> → <user_id>`

---

## Phase 2 — Transcript Ingestion Pipeline

**Goal:** A two-layer transcript storage system: raw JSON flat files on disk + a queryable SQLite index. This is the fallback data source and the source of "the exact email from June 12" references.

### Tasks

#### 2.1 SQLite Schema
- [ ] Create `db/schema.sql` with the `transcripts` and `issue_log` DDL:
  ```sql
  CREATE TABLE IF NOT EXISTS transcripts (
      transcript_id   TEXT PRIMARY KEY,
      user_id         TEXT NOT NULL,
      channel         TEXT NOT NULL,   -- "email" | "phone" | "chat"
      timestamp       DATETIME NOT NULL,
      content         TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_transcripts_user_ts
      ON transcripts (user_id, timestamp DESC);

  CREATE TABLE IF NOT EXISTS issue_log (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id     TEXT NOT NULL,
      issue_type  TEXT NOT NULL,
      timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_issue_log_type_ts
      ON issue_log (issue_type, timestamp DESC);
  ```
- [ ] Create `db/init_db.py` that runs the DDL against `db/transcripts.db`

#### 2.2 Synthetic Raw Transcripts (Demo Data)
- [ ] Create the four hand-crafted demo transcript JSON files in `data/raw/`:
  - `email_user123_20240612.json` — user reports the initial issue
  - `phone_user123_20240614.json` — user escalates via phone call
  - `chat_user123_20240615.json` — user states the step-by-step preference
  - `chat_user123_20240620.json` — follow-up chat (the demo moment)
- [ ] Each file follows the schema: `{ "transcript_id", "user_id", "channel", "timestamp", "content" }`

#### 2.3 Ingestion Script
- [ ] Create `src/ingestion.py`:
  - `ingest_transcript(filepath: str)` — reads a flat file, calls `resolve_user_id()`, writes a row to SQLite
  - `get_recent_transcripts(user_id: str, limit: int = 3) -> list[dict]` — returns the last N transcript rows for a user, ordered by timestamp DESC
- [ ] Write tests:
  - Ingest a transcript file → row appears in SQLite with correct fields
  - `get_recent_transcripts` returns ≤ 3 rows, ordered correctly
  - Re-ingesting the same `transcript_id` does not create a duplicate (PRIMARY KEY constraint)

### Deliverable
`db/transcripts.db` (initialized), all four raw JSON transcript files, `ingestion.py` with passing tests.

### Definition of Done
- [ ] `python db/init_db.py` creates the database with both tables and indexes
- [ ] All four transcript files can be ingested without errors
- [ ] `get_recent_transcripts("user_123", limit=3)` returns exactly 3 rows in descending timestamp order

---

## Phase 3 — Memory Store Integration (Mem0 + Zep)

**Goal:** Thin, tested wrappers around the Mem0 and Zep SDKs. The rest of the system only calls these wrappers — never the SDKs directly.

### Tasks

#### 3.1 Mem0 Wrapper
- [ ] Create `src/memory.py` with:
  ```python
  def search_preferences(user_id: str, query: str) -> dict
  def save_preference(user_id: str, turn: list[dict]) -> None
  ```
- [ ] `search_preferences` calls `mem0.search(query=query, user_id=user_id)` and returns a normalized dict
- [ ] `save_preference` calls `mem0.add(messages=turn, user_id=user_id)`

#### 3.2 Zep Wrapper
- [ ] Add to `src/memory.py`:
  ```python
  def search_state(user_id: str, query: str) -> dict
  def save_state(session_id: str, messages: list[dict]) -> None
  ```
- [ ] `search_state` calls `zep.graph.search(query=query, user_id=user_id)` and returns a normalized dict
- [ ] `save_state` calls `zep.memory.add(session_id=session_id, messages=messages)`

#### 3.3 Live Integration Test
- [ ] Write a script `tests/test_memory_live.py` (marked as integration, not unit):
  - Save a test preference for `user_test_001` → search for it → assert it is returned
  - Save a test state entry for `user_test_001` → search for it → assert it is returned
  - Clean up test user entries after the test

### Deliverable
`memory.py` with both wrappers + passing live integration tests against real Mem0 and Zep Cloud endpoints.

### Definition of Done
- [ ] Both wrappers initialize from config without errors
- [ ] Save → search round-trip works for both Mem0 and Zep
- [ ] No raw SDK calls exist anywhere outside `memory.py`

---

## Phase 4 — Context Assembler (Prep State)

**Goal:** The prep-state engine that fans out three parallel reads (Mem0 + Zep + SQLite) and synthesizes them into the fixed Structured Context Object via a constrained Claude call.

### Tasks

- [ ] Create `src/context_assembler.py` with:
  ```python
  def assemble_context(user_id: str, query: str) -> dict
  ```
- [ ] Inside `assemble_context`:
  1. Fire three parallel reads (use `concurrent.futures.ThreadPoolExecutor` or `asyncio.gather`):
     - `search_preferences(user_id, query)` → preferences block
     - `search_state(user_id, query)` → account_state + issue_history block
     - `get_recent_transcripts(user_id, limit=3)` → transcript_excerpts block
  2. Pass all three blocks to a constrained Claude call with the system prompt:
     > *"Fill this schema from the inputs provided. Return JSON only. Do not add narrative, do not infer beyond what is given."*
  3. Parse and validate the response against the fixed schema:
     ```json
     {
       "preferences": {},
       "account_state": {},
       "issue_history": [],
       "transcript_excerpts": []
     }
     ```
  4. Return the validated dict

- [ ] Implement cold-start handling: if all three reads return empty, return the empty schema — no special branch, the schema handles it
- [ ] Implement the field-level conflict merge rule in the synthesizer prompt: explicitly instruct Claude that `preferences` fields come from Mem0 and factual fields (`account_state`, `issue_history`) come from Zep. Both must be populated in the same output object
- [ ] Write tests:
  - With all stores populated: output schema contains data in all four fields
  - Cold-start (all stores empty): output schema returns with all fields empty
  - Conflict scenario: Mem0 preference data and Zep factual data both appear in their respective fields of the output (neither is discarded)

### Deliverable
`context_assembler.py` with passing tests including the conflict scenario.

### Definition of Done
- [ ] Parallel reads execute concurrently (not sequentially)
- [ ] Output always conforms to the fixed four-field schema
- [ ] Cold-start returns empty schema without errors
- [ ] Conflict test confirms both Mem0 style fields and Zep factual fields coexist in the output

---

## Phase 5 — Agent Response Generator + RAG Policy Retriever

**Goal:** The agent's response generation capability, grounded in both the user's memory context and company policy documents retrieved via RAG.

### Tasks

#### 5.1 Policy Documents
- [ ] Create hand-crafted policy docs in `data/policy/`:
  - `refund_policy.md`
  - `escalation_rules.md`
  - `known_issues_resolutions.md` (covers the rate-limiting issue in the demo)

#### 5.2 RAG Retriever
- [ ] Create `src/rag.py` with:
  ```python
  def build_index() -> None          # chunks docs, embeds with text-embedding-3-small, stores index
  def retrieve(query: str, top_k: int = 3) -> list[str]   # returns relevant chunks
  ```
- [ ] Chunking: simple fixed-size character chunks with overlap (no LLM needed for chunking)
- [ ] Embedding: `openai.embeddings.create(model="text-embedding-3-small", input=...)`
- [ ] Index storage: `vector_store/` directory (already in `.gitignore`)
- [ ] `retrieve()` embeds the query and returns the top-k most similar chunks

#### 5.3 Agent Response Generator
- [ ] Create `src/agent.py` with:
  ```python
  def generate_response(
      user_message: str,
      context_obj: dict,
      policy_chunks: list[str],
      conversation_history: list[dict]
  ) -> str
  ```
- [ ] Assemble the two-section prompt:
  ```
  [USER CONTEXT — from Memory]
    preferences: ...
    account_state: ...
    issue_history: ...
    transcript_excerpts: ...

  [POLICY CONTEXT — from RAG]
    <retrieved chunks>
  ```
- [ ] Call `claude.messages.create(...)` and return the response text
- [ ] Test: given a synthetic context object and policy chunks, the response is a non-empty string

### Deliverable
`rag.py` (with built index), `agent.py`, policy docs in `data/policy/`, passing tests.

### Definition of Done
- [ ] `build_index()` runs without errors and populates `vector_store/`
- [ ] `retrieve("rate limiting after upgrade")` returns at least one relevant chunk from `known_issues_resolutions.md`
- [ ] `generate_response()` returns a coherent, non-empty reply
- [ ] The assembled prompt keeps `[USER CONTEXT]` and `[POLICY CONTEXT]` as distinct sections

---

## Phase 6 — Write-Path Classifier

**Goal:** The post-turn memory routing component. After every agent turn, it extracts any new memory signals, passes them through a grounding check, and routes them to the correct store — or discards them.

### Tasks

- [ ] Create `src/write_classifier.py` with:
  ```python
  def classify_and_save(
      user_id: str,
      session_id: str,
      conversation_turn: list[dict]
  ) -> str   # returns "mem0" | "zep" | "discarded"
  ```
- [ ] Implement the two-gate evaluation via a single Claude call that returns structured JSON:
  ```json
  {
    "action": "save_mem0" | "save_zep" | "discard",
    "content": "...",
    "issue_type": "..."   // only present when action = save_zep and content is an issue
  }
  ```
- [ ] Gate 1 — Grounding check: the extracted content must be explicitly present in the turn text. If Claude cannot point to it verbatim → discard
- [ ] Gate 2 — Destination check: preference/style → Mem0; state/fact/issue → Zep
- [ ] On `save_mem0`: call `save_preference(user_id, conversation_turn)`. **Do not write to Issue Log.**
- [ ] On `save_zep`: call `save_state(session_id, conversation_turn)`. **Also write `issue_type` to `issue_log` table in SQLite** (only if `issue_type` is present in the classifier response).
- [ ] On `discard`: do nothing, log the discard decision
- [ ] Write tests:
  - Turn containing an explicit preference → classified as `save_mem0`, Issue Log not written
  - Turn containing an explicit state fact → classified as `save_zep`, Issue Log written with correct `issue_type`
  - Turn containing no new information → classified as `discard`
  - Turn where classifier tries to infer a fact not stated → classified as `discard` (grounding check fails)

### Deliverable
`write_classifier.py` with passing tests. The Issue Log write scope invariant must be verified by the tests.

### Definition of Done
- [ ] All four test cases pass
- [ ] Preference turns never produce an Issue Log write (verified in test)
- [ ] State/issue turns always produce both a Zep save and an Issue Log write (verified in test)
- [ ] No raw SDK calls exist outside `memory.py`; the classifier only calls the wrappers

---

## Phase 7 — Cross-User Pattern Detector

**Goal:** A backend-only analytics query that flags when the same issue type crosses a frequency threshold across multiple users. Completely decoupled from the agent.

### Tasks

- [ ] Create `src/pattern_detector.py` with:
  ```python
  def detect_patterns(
      threshold_count: int = 10,
      window_days: int = 7
  ) -> list[dict]   # returns list of {issue_type, count, window_start}
  ```
- [ ] Query: `SELECT issue_type, COUNT(*) FROM issue_log WHERE timestamp > ? GROUP BY issue_type HAVING COUNT(*) >= ?`
- [ ] Output: a list of dicts, logged to console/file — never returned to the agent or injected into any user-facing prompt
- [ ] Write tests:
  - Seed `issue_log` with 11 entries of the same `issue_type` within 7 days → detected
  - Seed with 9 entries → not detected (below threshold)
  - Mix of issue types: only the one above threshold appears in output

### Deliverable
`pattern_detector.py` with passing tests.

### Definition of Done
- [ ] Threshold and window are configurable parameters, not hardcoded
- [ ] Output is never surfaced to the user (verified by inspection — no call path from orchestrator to this function during a chat turn)
- [ ] All three test cases pass

---

## Phase 8 — Session Lifecycle Management

**Goal:** Clean session boundary logic. Sessions are the unit that defines the 3-session token budget window. They must be created, tracked, and closed/expired correctly.

### Tasks

- [ ] Create `src/session.py` with:
  ```python
  def create_session(user_id: str) -> str          # returns session_id
  def get_active_session(user_id: str) -> str | None
  def close_session(session_id: str) -> None       # explicit close
  def expire_stale_sessions(inactivity_hours: int = 24) -> int  # returns count expired
  def record_activity(session_id: str) -> None     # updates last_active timestamp
  ```
- [ ] Add a `sessions` table to `db/schema.sql`:
  ```sql
  CREATE TABLE IF NOT EXISTS sessions (
      session_id      TEXT PRIMARY KEY,
      user_id         TEXT NOT NULL,
      created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      last_active     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      status          TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'closed' | 'expired'
  );
  ```
- [ ] `expire_stale_sessions()` sets `status = 'expired'` for all sessions where `last_active < now - 24h` and `status = 'active'`
- [ ] **Update `get_recent_transcripts` to filter by session status** — this is the Phase 8 task that closes the gap between Phase 2 (which ships the function without session awareness) and Phase 12.4 (which asserts only closed/expired sessions are counted):
  - Modify the query in `ingestion.py` to `JOIN sessions ON transcripts.user_id = sessions.user_id` and add `WHERE sessions.status IN ('closed', 'expired')`
  - The currently active session is explicitly excluded — its transcripts are already in memory as `conversation_history` and must not be double-counted
  - Update the function signature to accept an optional `exclude_active: bool = True` parameter for testability
- [ ] Write tests:
  - New session created → appears in DB with `status = 'active'`
  - `close_session()` → status changes to `'closed'`
  - Session with `last_active` > 24h ago → `expire_stale_sessions()` marks it `'expired'`
  - Session with `last_active` < 24h ago → not expired
  - `get_recent_transcripts(user_id, limit=3)` with one active + two closed sessions → returns only transcripts from the two closed sessions (active session excluded)
  - `get_recent_transcripts(user_id, limit=3, exclude_active=False)` → returns transcripts from all three sessions (used for testing only)

### Deliverable
`session.py` + updated `schema.sql` + updated `ingestion.py` (`get_recent_transcripts` with session-status filter) + passing tests.

### Definition of Done
- [ ] All six test cases pass (four session lifecycle + two `get_recent_transcripts` filter cases)
- [ ] `expire_stale_sessions()` is safe to run repeatedly without double-expiring sessions
- [ ] `get_recent_transcripts` never returns transcripts from an active session by default

---

## Phase 9 — Agent Orchestrator (Full Integration)

**Goal:** Wire all components together into the single runtime coordinator. This is the first phase where the full end-to-end flow runs.

### Tasks

- [ ] Create `src/orchestrator.py` with:
  ```python
  def handle_message(
      raw_identifier: str,
      user_message: str,
      session_id: str | None = None
  ) -> str   # returns agent response
  ```
- [ ] Implement the full message handling flow:
  1. `resolve_user_id(raw_identifier)` → `user_id`
  2. Get or create session: `get_active_session(user_id)` or `create_session(user_id)`
  3. `record_activity(session_id)`
  4. If first message in session: `assemble_context(user_id, user_message)` → context object
  5. `retrieve(user_message)` → policy chunks
  6. `generate_response(user_message, context_obj, policy_chunks, history)` → response
  7. Append turn to in-memory conversation history
  8. `classify_and_save(user_id, session_id, conversation_turn)` (async / non-blocking)
  9. Return response
- [ ] Run `expire_stale_sessions()` on orchestrator startup (or on a background thread)
- [ ] Integration test — simulate the full demo journey:
  1. Ingest the four demo transcripts
  2. Send a chat message as `rahul@acme.com`
  3. Assert the response references the prior issue (from Zep/SQLite)
  4. Assert a preference expressed in the turn gets saved to Mem0 (verify via `search_preferences`)

### Deliverable
`orchestrator.py` + end-to-end integration test.

### Definition of Done
- [ ] Single call to `handle_message()` produces a coherent response
- [ ] Context assembly runs before the first response in a session
- [ ] Write classifier fires after every response
- [ ] Session is tracked and activity is recorded

---

## Phase 10 — Frontend Chat Interface

**Goal:** A local HTML interface that renders the chat conversation and — crucially — shows a live panel indicating which memory source each piece of context came from (Mem0 / Zep / SQLite / RAG).

### Tasks

- [ ] Create a minimal Python HTTP server in `src/server.py` that:
  - Serves `frontend/index.html` on `http://localhost:<port>`
  - Exposes a `POST /chat` endpoint that calls `handle_message()` and returns JSON:
    ```json
    {
      "response": "...",
      "context_sources": {
        "preferences": "Mem0",
        "account_state": "Zep",
        "issue_history": "Zep",
        "transcript_excerpts": "SQLite",
        "policy_chunks": "RAG"
      }
    }
    ```
- [ ] Create `frontend/index.html` with:
  - Chat message thread (user bubbles left, agent bubbles right)
  - Input box + send button
  - **Memory Source Panel** (sidebar or drawer): displays the `context_sources` for the most recent turn, showing which store each field came from
  - Source labels styled distinctly per store (e.g., Mem0 = purple, Zep = blue, SQLite = teal, RAG = amber)
- [ ] No external CSS frameworks — vanilla CSS only

### Deliverable
`server.py` + `frontend/index.html`, running on localhost.

### Definition of Done
- [ ] Page loads without errors
- [ ] Sending a message returns a response and populates the Memory Source Panel
- [ ] The source panel correctly reflects which stores contributed to the context (not hardcoded)

---

## Phase 11 — Demo Data & End-to-End Scenario

**Goal:** Fully populate the demo state so the single deep user journey (email → phone → chat → return chat) can be demonstrated without any manual setup steps.

### Tasks

- [ ] Create `scripts/setup_demo.py` that:
  1. Initializes the database (`init_db.py`)
  2. Ingests all four transcript files in chronological order
  3. Runs the write-path classifier on each transcript to populate Mem0 and Zep
  4. Prints a summary: how many preferences saved to Mem0, how many state updates saved to Zep, how many Issue Log entries written
- [ ] Verify the demo state manually by running `handle_message("rahul@acme.com", "I'm having the rate limiting issue again")` and confirming the response:
  - References the prior issue from history
  - Applies step-by-step guidance (from the Mem0 preference saved during the chat session)
  - Can reference the June 12 email if asked
- [ ] Document the exact demo script in `docs/demo_script.md` (the sequence of messages to send during a live demo)

### Deliverable
`scripts/setup_demo.py` + verified demo state + `docs/demo_script.md`.

### Definition of Done
- [ ] `python scripts/setup_demo.py` runs to completion without errors
- [ ] The four "demo moment" assertions hold (prior issue recognized, step-by-step style applied, transcript reference available)
- [ ] Demo can be reset and re-run by calling `setup_demo.py` again

---

## Phase 12 — Evals & Testing

**Goal:** Validate correctness of all critical behaviors before the project is considered complete. Covers all three eval scenarios from Section 11 of the architecture doc.

### Tasks

#### 12.1 Grounding Check (Eval 11.1)
- [ ] Construct a turn where a preference is **not stated** but could be inferred (e.g., user asks a short question — classifier must not save a verbose-preference that wasn't expressed)
- [ ] Run `classify_and_save()` on it
- [ ] Assert result is `"discarded"`

#### 12.2 Conflict Policy (Eval 11.2)
- [ ] Seed Mem0 with a stale preference: `"prefers verbose, detailed updates"` for `user_123`
- [ ] Seed Zep with a current state fact: `"account flagged for fast-path resolution"`
- [ ] Run `assemble_context("user_123", "my issue is still open")`
- [ ] Assert the returned context object has:
  - `preferences.communication_style` containing the verbose preference (from Mem0)
  - `account_state` containing the fast-path flag (from Zep)
  - Both fields populated — neither discarded
- [ ] Run `generate_response()` with this context and capture the response text
- [ ] Assert factual routing (Zep wins): response text contains a keyword from the fast-path resolution path (e.g., `"fast-path"`, `"expedited"`, or `"priority resolution"` — seeded into the policy doc so it is detectable)
- [ ] Assert tone routing (Mem0 wins) using **LLM-as-judge**:
  ```python
  # Concrete automated tone check — not manual inspection
  judge_prompt = f"""
  You are evaluating whether a support response matches a "verbose, detailed" communication style.
  Score the response on a scale of 1–5:
    1 = very terse / bullet-points only
    5 = verbose, detailed, multi-sentence explanations
  Respond with JSON only: {{"score": <int>, "reason": "<one sentence>"}}

  Response to evaluate:
  {response_text}
  """
  judge_result = claude.messages.create(
      model="claude-sonnet-4-5-20250929",   # cheapest model — judge calls don't need power
      max_tokens=100,
      messages=[{"role": "user", "content": judge_prompt}]
  )
  score = json.loads(judge_result.content[0].text)["score"]
  assert score >= 4, f"Tone check failed: expected verbose style (score >= 4), got {score}"
  ```
  - Pass threshold: **score ≥ 4 out of 5**
  - Judge model: `claude-sonnet-4-5-20250929` (cheap, fast — this is a scoring call, not a generation call)
  - The judge call is deterministic enough at this granularity; if it is flaky across runs, lower the threshold to ≥ 3 and document the decision

#### 12.3 Issue Log Write Scope (Eval from Section 3.9)
- [ ] Run the classifier on a preference turn → assert Issue Log count does not increase
- [ ] Run the classifier on a state/issue turn → assert Issue Log count increases by exactly 1 with the correct `issue_type`

#### 12.4 Session Boundary (Eval 11.3)
- [ ] Create a session, set `last_active` to 25 hours ago in the DB
- [ ] Run `expire_stale_sessions()` → assert session status is `'expired'`
- [ ] Verify `get_recent_transcripts(limit=3)` correctly counts only closed/expired sessions

#### 12.5 Cold-Start (Eval 11.3)
- [ ] Call `assemble_context()` for a brand-new user ID with no data in any store
- [ ] Assert all four fields are empty but the schema is valid JSON

#### 12.6 Cross-User Pattern Threshold (Eval 11.3)
- [ ] Seed `issue_log` with 10 entries of `"rate_limiting"` within 7 days
- [ ] `detect_patterns(threshold_count=10, window_days=7)` → asserts `"rate_limiting"` is returned
- [ ] Seed with 9 entries → not returned

### Deliverable
All eval scripts in `tests/evals/`, all passing.

### Definition of Done
- [ ] All 6 eval scenarios pass
- [ ] No eval result is manually verified — all assertions are in code
- [ ] Results are printed with pass/fail labels when running `python -m pytest tests/`

---

## Build Order Summary

```
Phase 0  → Environment & Scaffold
Phase 1  → Identity Resolver                  (standalone, no deps)
Phase 2  → Transcript Ingestion + SQLite      (depends on Phase 1)
Phase 3  → Memory Store Wrappers (Mem0 + Zep) (standalone)
Phase 4  → Context Assembler                  (depends on Phases 2, 3)
Phase 5  → RAG Retriever + Response Generator (depends on Phase 4)
Phase 6  → Write-Path Classifier              (depends on Phases 2, 3)
Phase 7  → Pattern Detector                   (depends on Phase 2)
Phase 8  → Session Lifecycle                  (depends on Phase 2)
Phase 9  → Orchestrator                       (depends on Phases 1–8)
Phase 10 → Frontend                           (depends on Phase 9)
Phase 11 → Demo Data & Scenario               (depends on Phases 1–10)
Phase 12 → Evals & Testing                    (depends on all phases)
```
