CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id   TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    channel         TEXT NOT NULL,   -- "email" | "phone" | "chat"
    timestamp       DATETIME NOT NULL,
    content         TEXT NOT NULL,
    session_id      TEXT             -- Link to sessions table
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

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status          TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'closed' | 'expired'
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_status
    ON sessions (user_id, status);
