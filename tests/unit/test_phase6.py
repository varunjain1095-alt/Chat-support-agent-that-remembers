import sys
import pytest
import pathlib
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.write_classifier import classify_and_save

@pytest.fixture
def mock_anthropic():
    with patch("src.write_classifier.anthropic.Anthropic") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client
        yield mock_client

def test_p6_05_classifier_invalid_json_fallback(mock_anthropic):
    """P6-05 [UNIT] — Classifier handles invalid JSON response from Claude gracefully by discarding."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="This response is not a valid JSON structure.")]
    mock_anthropic.messages.create.return_value = mock_message

    turn = [{"role": "user", "content": "This is a long user message that will pass the character check."}]
    res = classify_and_save("user_123", "sess_123", turn)
    
    assert res == "discarded"
    mock_anthropic.messages.create.assert_called_once()

def test_p6_06_short_turn_skips_classifier(mock_anthropic):
    """P6-06 [UNIT] — Skips the Claude API call entirely if user content is under MIN_TURN_LENGTH_FOR_CLASSIFIER."""
    turn = [{"role": "user", "content": "ok"}]  # 2 characters, < 10 threshold
    res = classify_and_save("user_123", "sess_123", turn)
    
    assert res == "discarded"
    # Claude messages API should not be called
    mock_anthropic.messages.create.assert_not_called()
