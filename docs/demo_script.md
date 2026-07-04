# AI Customer Support Agent — Live Demo Script

This document details the step-by-step conversational scenario to demonstrate the complete identity resolution, memory routing, and parallel RAG capabilities of the Customer Support Agent.

---

## 1. Setup Instructions
Before starting the demo, clean and seed the database by running the setup script from the app root:
```powershell
docker-compose run --rm app python scripts/setup_demo.py
```
This script:
- Resets SQLite tables.
- Wipes and prepares the Zep graph/threads and Mem0 user spaces for `user_123`.
- Ingests all 4 raw customer transcripts in chronological order.
- Runs the classifier turn-by-turn to extract historical context (saving Pro tier upgrades and HTTP 429 issues to Zep, and the step-by-step guidance preferences to Mem0).

---

## 2. E2E Chat Scenario Walkthrough

### Step 1: Open the live console
- Navigate to **[http://localhost:8000](http://localhost:8000)** in your browser.
- Ensure the user selected in the header configuration bar is **`rahul@acme.com`**.
- Click **New Session** in the top-right configuration bar to start a clean session.

### Step 2: Greet the Assistant (Greeting Filtering)
- **Send message:** `"Hi!"`
- **Expected response:** A friendly greeting (e.g., `"Hi there! How can I help you today?"`).
- **Memory Source Panel status:**
  - The Memory Source Panel on the right should display **Empty Sources** (no cards visible).
  - This confirms that short greeting messages **do not trigger** the heavy context assembly/retrieval engine.

### Step 3: Trigger Context Retrieval
- **Send message:** `"I'm having the rate limiting issue again."`
- **Expected response:**
  - The agent identifies that the user is running a **Pro plan**.
  - The agent references the previous support ticket (`ticket 4872`) and their previous chat session on **June 15th**.
  - The agent adopts the **step-by-step communication style** (rather than listing all resolution steps at once, it asks the user to confirm each step sequentially, starting with clearing the local cache).
- **Memory Source Panel expected card content:**
  - **Mem0 (Preferences) Card:**
    ```json
    {
      "communication_style": "step-by-step",
      "technical_level": "non-technical",
      "instruction_delivery": "one_step_at_time",
      "information_accuracy": "high_accuracy_required_for_relay_to_developer",
      "pacing": "slow_and_deliberate",
      "avoidance": "multiple_steps_at_once",
      "appreciation": "walking_through_process_rather_than_listing"
    }
    ```
  - **Zep (Account State) Card:**
    ```json
    {
      "user_id": "user_123",
      "account_email": "rahul@acme.com",
      "plan_tier": "Pro",
      "upgrade_date": "2024-06-12",
      "current_status": "rate_limit_issue_resolved"
    }
    ```
  - **SQLite (Issue Log) Card:**
    ```json
    [
      {
        "id": 1,
        "user_id": "user_123",
        "issue_type": "rate limit error 429",
        "timestamp": "2024-06-12 10:30:00"
      },
      {
        "id": 2,
        "user_id": "user_123",
        "issue_type": "rate limit error 429",
        "timestamp": "2024-06-14 14:15:00"
      },
      {
        "id": 3,
        "user_id": "user_123",
        "issue_type": "rate limit",
        "timestamp": "2024-06-20 09:15:00"
      }
    ]
    ```
  - **SQLite (Transcripts) Card:**
    ```json
    [
      {
        "transcript_id": "chat_user123_20240620",
        "channel": "chat",
        "timestamp": "2024-06-20T09:15:00Z",
        "content": "hey, so this is going to sound familiar but I'm getting the rate limit thing again"
      },
      {
        "transcript_id": "chat_user123_20240615",
        "channel": "chat",
        "timestamp": "2024-06-15T11:40:00Z",
        "content": "Rahul: hey, following up again on the rate limiting thing..."
      },
      {
        "transcript_id": "phone_user123_20240614",
        "channel": "phone",
        "timestamp": "2024-06-14T14:15:00Z",
        "content": "Agent: Thank you for calling support, this is Priya, how can I help you today?..."
      }
    ]
    ```
  - **RAG Card:**
    ```json
    [
      "## Known Issues & Resolutions\n### Rate-Limiting / HTTP 429\n- **Issue**: Users reporting HTTP 429 rate limit errors immediately after upgrading to a Pro plan.\n- **Root Cause**: Stale CDN/caching layer mapping for API gateway keys (engineering ticket #9921).\n- **Fix**: Engineering cache-flush (deployed June 15, 2024)..."
    ]
    ```

### Step 4: Follow up (Session Cache Test)
- **Send message:** `"Yes, clearing the cache didn't work. What is step 2?"`
- **Expected response:** The agent moves to step 2 (regenerating the API key) in a friendly tone.
- **Memory Source Panel status:**
  - The panel cards remain active and unchanged, demonstrating that the context object is cached for the duration of the active session.
