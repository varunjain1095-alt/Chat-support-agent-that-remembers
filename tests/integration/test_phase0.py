import pytest
import config

def test_p0_03_claude_ping():
    """P0-03 [INTG] — Claude client initializes and returns a non-empty response."""
    from anthropic import Anthropic
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_RESPONSE_MODEL,
        max_tokens=5,
        messages=[{"role": "user", "content": "Reply with the single word: OK"}],
    )
    assert response.content is not None
    assert len(response.content) > 0
    text = response.content[0].text.strip()
    assert text != ""


def test_p0_04_mem0_ping():
    """P0-04 [INTG] — Mem0 client initializes and .search() returns a list/dict without raising."""
    from mem0 import MemoryClient
    mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
    result = mem0.search(query="test", filters={"user_id": "smoke_test_phase0"})
    # Accept both list or dict with 'results' key (due to version differences in SDK)
    assert isinstance(result, list) or (isinstance(result, dict) and "results" in result)


def test_p0_05_zep_ping():
    """P0-05 [INTG] — Zep client initializes and .graph.search() completes without raising."""
    from zep_cloud.client import Zep
    zep = Zep(api_key=config.ZEP_API_KEY)
    result = zep.graph.search(query="test", user_id="smoke_test_phase0")
    assert result is not None
