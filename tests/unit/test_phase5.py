import sys
import pytest
import pathlib
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.agent import generate_response

@patch("src.agent.anthropic.Anthropic")
def test_p5_05_prompt_contains_headers(mock_class):
    """P5-05 [UNIT] — Prompt contains distinct USER CONTEXT and POLICY CONTEXT sections."""
    mock_client = MagicMock()
    mock_class.return_value = mock_client

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Help response")]
    mock_client.messages.create.return_value = mock_message

    user_message = "I upgraded and see 429 errors."
    context_obj = {
        "preferences": {"communication_style": "concise"},
        "account_state": {"tier": "Pro"},
        "issue_history": [],
        "transcript_excerpts": []
    }
    policy_chunks = ["Resolution step: clear cache."]
    conversation_history = []

    res = generate_response(user_message, context_obj, policy_chunks, conversation_history)

    assert res == "Help response"
    mock_client.messages.create.assert_called_once()
    
    # Verify parameters
    call_args = mock_client.messages.create.call_args
    kwargs = call_args[1]
    
    # Inspect user prompt content in the message array
    messages = kwargs["messages"]
    latest_msg = messages[-1]
    content = latest_msg["content"]
    
    assert "[USER CONTEXT" in content
    assert "[POLICY CONTEXT" in content
