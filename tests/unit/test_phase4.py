import sys
import time
import pytest
import pathlib
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.context_assembler import assemble_context

@pytest.fixture
def mock_anthropic():
    with patch("src.context_assembler.anthropic.Anthropic") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client
        yield mock_client

@patch("src.context_assembler.search_preferences")
@patch("src.context_assembler.search_state")
@patch("src.context_assembler.get_recent_transcripts")
def test_p4_01_mocked_all_stores_populated(
    mock_get_trans, mock_search_state, mock_search_pref, mock_anthropic
):
    """P4-01 [UNIT] — Populated stores contribute to the synthesized context object."""
    mock_search_pref.return_value = [{"memory": "prefers step-by-step guidance", "id": "mem_1"}]
    mock_search_state.return_value = {"nodes": [{"id": "User", "fact": "Tier: Pro"}], "edges": []}
    mock_get_trans.return_value = [
        {"transcript_id": "tr_1", "channel": "email", "timestamp": "2024-06-12T10:30:00Z", "content": "Hello."}
    ]

    # Mock Claude response
    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(text="""
        {
          "preferences": {"communication_style": "step-by-step guidance"},
          "account_state": {"plan": "Pro"},
          "issue_history": [],
          "transcript_excerpts": [
            {
              "transcript_id": "tr_1",
              "channel": "email",
              "timestamp": "2024-06-12T10:30:00Z",
              "content": "Hello."
            }
          ]
        }
        """)
    ]
    mock_anthropic.messages.create.return_value = mock_message

    result = assemble_context("user_123", "need help")
    
    assert result["preferences"] == {"communication_style": "step-by-step guidance"}
    assert result["account_state"] == {"plan": "Pro"}
    assert len(result["transcript_excerpts"]) == 1
    assert result["transcript_excerpts"][0]["transcript_id"] == "tr_1"
    mock_anthropic.messages.create.assert_called_once()


@patch("src.context_assembler.search_preferences")
@patch("src.context_assembler.search_state")
@patch("src.context_assembler.get_recent_transcripts")
def test_p4_02_mocked_cold_start_handling(
    mock_get_trans, mock_search_state, mock_search_pref, mock_anthropic
):
    """P4-02 [UNIT] — Cold start returns empty schema directly, without LLM call."""
    mock_search_pref.return_value = []
    mock_search_state.return_value = {}
    mock_get_trans.return_value = []

    result = assemble_context("brand_new_user", "hello")
    
    assert result == {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }
    # LLM should not be called in cold start
    mock_anthropic.messages.create.assert_not_called()


@patch("src.context_assembler.search_preferences")
@patch("src.context_assembler.search_state")
@patch("src.context_assembler.get_recent_transcripts")
def test_p4_03_mocked_conflict_scenario(
    mock_get_trans, mock_search_state, mock_search_pref, mock_anthropic
):
    """P4-03 [UNIT] — Conflict scenario where both stores contribute to their designated fields."""
    mock_search_pref.return_value = [{"memory": "prefers verbose responses"}]
    mock_search_state.return_value = {"nodes": [{"id": "User", "fact": "Tier: Pro plan"}], "edges": []}
    mock_get_trans.return_value = []

    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(text="""
        {
          "preferences": {"communication_style": "verbose style"},
          "account_state": {"plan": "Pro plan"},
          "issue_history": [],
          "transcript_excerpts": []
        }
        """)
    ]
    mock_anthropic.messages.create.return_value = mock_message

    result = assemble_context("user_conflict", "status")
    
    assert "verbose" in str(result["preferences"])
    assert "Pro" in str(result["account_state"])
    mock_anthropic.messages.create.assert_called_once()


@patch("src.context_assembler.search_preferences")
@patch("src.context_assembler.search_state")
@patch("src.context_assembler.get_recent_transcripts")
def test_p4_04_mocked_conformance_and_error_fallback(
    mock_get_trans, mock_search_state, mock_search_pref, mock_anthropic
):
    """P4-04 [UNIT] — Ensures the output always conforms to the fixed schema even if Claude output is malformed or partial."""
    mock_search_pref.return_value = [{"memory": "some_pref"}]
    mock_search_state.return_value = {}
    mock_get_trans.return_value = []

    # Case 1: Partial JSON missing fields
    mock_message_partial = MagicMock()
    mock_message_partial.content = [
        MagicMock(text='{"preferences": {"tone": "polite"}}')
    ]
    mock_anthropic.messages.create.return_value = mock_message_partial
    
    result = assemble_context("user_partial", "hi")
    assert set(result.keys()) == {"preferences", "account_state", "issue_history", "transcript_excerpts"}
    assert result["preferences"] == {"tone": "polite"}
    assert result["account_state"] == {}
    assert result["issue_history"] == []
    assert result["transcript_excerpts"] == []

    # Case 2: Malformed JSON syntax error
    mock_message_malformed = MagicMock()
    mock_message_malformed.content = [
        MagicMock(text="This is not valid JSON string.")
    ]
    mock_anthropic.messages.create.return_value = mock_message_malformed

    result2 = assemble_context("user_malformed", "hi")
    assert result2 == {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }


@patch("src.context_assembler.search_preferences")
@patch("src.context_assembler.search_state")
@patch("src.context_assembler.get_recent_transcripts")
def test_p4_05_parallel_execution_timing(
    mock_get_trans, mock_search_state, mock_search_pref, mock_anthropic
):
    """P4-05 [UNIT] — Parallel fetch is concurrent, completing three 1-second sleeps in < 2 seconds."""
    def slow_pref(*args, **kwargs):
        time.sleep(1.0)
        return [{"memory": "some_pref"}]

    def slow_state(*args, **kwargs):
        time.sleep(1.0)
        return {"nodes": []}

    def slow_trans(*args, **kwargs):
        time.sleep(1.0)
        return []

    mock_search_pref.side_effect = slow_pref
    mock_search_state.side_effect = slow_state
    mock_get_trans.side_effect = slow_trans

    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(text='{"preferences": {}, "account_state": {}, "issue_history": [], "transcript_excerpts": []}')
    ]
    mock_anthropic.messages.create.return_value = mock_message

    start_time = time.time()
    result = assemble_context("user_123", "query")
    elapsed_time = time.time() - start_time

    assert elapsed_time < 2.0, f"Execution took too long: {elapsed_time:.2f}s (should be parallel ~1s)"
    assert set(result.keys()) == {"preferences", "account_state", "issue_history", "transcript_excerpts"}
