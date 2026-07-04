"""
config.py — Central configuration loader.

All modules import credentials and settings from here.
No module should ever call os.environ directly.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (one directory above src/ if running from src/,
# or the project root if running from the project root).
load_dotenv()

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
MEM0_API_KEY: str      = os.environ.get("MEM0_API_KEY", "")
ZEP_API_KEY: str       = os.environ.get("ZEP_API_KEY", "")
OPENAI_API_KEY: str    = os.environ.get("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Validation — fail loudly at import time if required keys are missing
# ---------------------------------------------------------------------------

_REQUIRED = {
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "MEM0_API_KEY":      MEM0_API_KEY,
    "ZEP_API_KEY":       ZEP_API_KEY,
    "OPENAI_API_KEY":    OPENAI_API_KEY,
}

_missing = [name for name, value in _REQUIRED.items() if not value.strip()]
if _missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing)}\n"
        "Ensure your .env file is present and contains all required keys."
    )

# ---------------------------------------------------------------------------
# Database paths
# ---------------------------------------------------------------------------

import pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
DB_PATH: pathlib.Path      = PROJECT_ROOT / "db" / "transcripts.db"
DATA_RAW_DIR: pathlib.Path = PROJECT_ROOT / "data" / "raw"
DATA_POLICY_DIR: pathlib.Path = PROJECT_ROOT / "data" / "policy"
VECTOR_STORE_DIR: pathlib.Path = PROJECT_ROOT / "vector_store"

# ---------------------------------------------------------------------------
# Memory / context settings
# ---------------------------------------------------------------------------

# Maximum number of completed sessions to include in the context window.
MAX_SESSIONS_IN_CONTEXT: int = 3

# Maximum characters to include per transcript excerpt (prevents context overflow).
MAX_EXCERPT_CHARS: int = 1500

# Session inactivity timeout in hours before auto-expiry.
SESSION_INACTIVITY_HOURS: int = 24

# Minimum turn character length before the write-path classifier is invoked.
MIN_TURN_LENGTH_FOR_CLASSIFIER: int = 10

# ---------------------------------------------------------------------------
# RAG settings
# ---------------------------------------------------------------------------

EMBEDDING_MODEL: str = "text-embedding-3-small"
RAG_TOP_K: int = 3
RAG_SIMILARITY_THRESHOLD: float = 0.35   # minimum cosine similarity to include a chunk

# ---------------------------------------------------------------------------
# LLM settings
# ---------------------------------------------------------------------------

CLAUDE_RESPONSE_MODEL: str  = "claude-sonnet-4-5-20250929"   # main agent + context assembly
CLAUDE_JUDGE_MODEL: str     = "claude-sonnet-4-5-20250929"       # write-path classifier + eval judge
