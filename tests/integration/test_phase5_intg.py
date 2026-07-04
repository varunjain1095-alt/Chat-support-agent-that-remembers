import os
import shutil
import pytest
import pathlib
import sys

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.rag import build_index, retrieve
from src.agent import generate_response

@pytest.fixture(scope="module", autouse=True)
def setup_rag_index():
    # Back up existing index if any
    index_path = config.VECTOR_STORE_DIR / "index.json"
    backup_path = config.VECTOR_STORE_DIR / "index.json.bak"
    has_backup = False
    
    if index_path.exists():
        shutil.copy(index_path, backup_path)
        has_backup = True

    try:
        # Build clean index for testing
        build_index()
        yield
    finally:
        # Restore backup
        if has_backup:
            if backup_path.exists():
                shutil.copy(backup_path, index_path)
                os.remove(backup_path)
        else:
            if index_path.exists():
                os.remove(index_path)


def test_p5_01_intg_build_index():
    """P5-01 [INTG] — build_index() creates the vector store index.json."""
    index_path = config.VECTOR_STORE_DIR / "index.json"
    assert index_path.exists()
    assert index_path.stat().st_size > 0


def test_p5_02_intg_retrieve_relevant():
    """P5-02 [INTG] — retrieve() returns relevant chunks from policy documentation."""
    query = "rate limiting after upgrading to Pro plan"
    results = retrieve(query, top_k=3)
    
    assert len(results) >= 1
    # Check that rate limiting / 429 resolution steps are present
    assert any("429" in text or "rate" in text.lower() or "cache" in text.lower() for text in results)


def test_p5_03_intg_retrieve_irrelevant_returns_empty():
    """P5-03 [INTG] — retrieve() with query below similarity threshold returns empty list."""
    query = "What is the weather like in Paris?"
    results = retrieve(query, top_k=3)
    
    assert len(results) == 0


def test_p5_04_intg_generate_response():
    """P5-04 [INTG] — generate_response() returns a non-empty grounded response string from Claude."""
    user_message = "I upgraded to Pro, but my API calls are still rate limited with 429 errors. What do I do?"
    context_obj = {
        "preferences": {"communication_style": "step-by-step instructions"},
        "account_state": {"tier": "Pro"},
        "issue_history": [],
        "transcript_excerpts": []
    }
    
    # Retrieve relevant policy documents
    policy_chunks = retrieve(user_message, top_k=2)
    assert len(policy_chunks) > 0
    
    # Generate response
    response = generate_response(user_message, context_obj, policy_chunks, [])
    
    assert isinstance(response, str)
    assert len(response.strip()) > 0
    # Check that the response adopts the tone/resolution steps
    assert "cache" in response.lower() or "key" in response.lower()
