"""
identity_resolver.py — Maps inbound channel identifiers to canonical user_id.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Deterministic mapping dict for the demo user
_IDENTITY_MAP = {
    "rahul@acme.com": "user_123",
    "+91-9876543210": "user_123",
    "sess_abc_789": "user_123",
    "user_123": "user_123"
}

def resolve_user_id(identifier: Optional[str]) -> str:
    """
    resolve_user_id — Maps any inbound channel identifier to a canonical user_id.
    
    If the identifier is already a canonical user_id (starts with 'user_'), returns it.
    If the identifier is not in the mapping (or is empty/None), returns "unknown_user".
    Logs the resolution event with the format: Identity resolved: <identifier> → <user_id>
    """
    if not identifier:
        user_id = "unknown_user"
    elif identifier.startswith("user_"):
        user_id = identifier
    else:
        user_id = _IDENTITY_MAP.get(identifier, "unknown_user")
    
    logger.info(f"Identity resolved: {identifier} → {user_id}")
    return user_id
