import json
import socket
import threading
import urllib.request
import urllib.error
import pytest
import pathlib
import sys
from unittest.mock import patch, MagicMock
from http.server import HTTPServer

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.server import ChatServerHandler

def get_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

@pytest.fixture(scope="module")
def local_server():
    port = get_free_port()
    server = HTTPServer(('127.0.0.1', port), ChatServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()

def test_p10_01_get_index(local_server):
    """P10-01 [UNIT] — Server hosts frontend index.html on GET /."""
    url = f"{local_server}/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        html = response.read().decode('utf-8')
        assert "Memory Source Panel" in html
        assert "AI Support Assistant" in html

@patch("src.server.handle_message")
@patch("src.server.resolve_user_id")
def test_p10_02_03_04_post_chat(mock_resolve, mock_handle, local_server):
    """P10-02, P10-03, P10-04 [UNIT] — POST /chat resolves identities, calls orchestrator and yields response JSON."""
    mock_resolve.return_value = "user_123"
    mock_handle.return_value = "Hello back!"
    
    url = f"{local_server}/chat"
    payload = {
        "identifier": "rahul@acme.com",
        "message": "Hello!",
        "session_id": "test_session_123"
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        res_data = json.loads(response.read().decode('utf-8'))
        
        assert res_data["response"] == "Hello back!"
        assert res_data["session_id"] == "test_session_123"
        assert "context" in res_data
        assert res_data["context"]["preferences"]["source"] == "Mem0"
        
        # Verify resolution called (P10-03)
        mock_resolve.assert_called_with("rahul@acme.com")
        # Verify handle_message called with resolved context parameters (P10-04)
        mock_handle.assert_called_with("rahul@acme.com", "Hello!", session_id="test_session_123")


@patch("src.server.handle_message")
@patch("src.server.resolve_user_id")
def test_p10_07_cold_start_empty_sources(mock_resolve, mock_handle, local_server):
    """P10-03 / P10-07 [UNIT] — Server response reflects actual empty store population for a cold-start user."""
    mock_resolve.return_value = "cold_user"
    mock_handle.return_value = "Welcome to cold start!"
    
    # Inject empty caches
    from src.orchestrator import _SESSION_CONTEXT_CACHE, _SESSION_RAG_CACHE
    session_id = "cold_session_123"
    _SESSION_CONTEXT_CACHE[session_id] = {
        "preferences": {},
        "account_state": {},
        "issue_history": [],
        "transcript_excerpts": []
    }
    _SESSION_RAG_CACHE[session_id] = []
    
    url = f"{local_server}/chat"
    payload = {
        "identifier": "cold@acme.com",
        "message": "Hi",
        "session_id": session_id
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        res_data = json.loads(response.read().decode('utf-8'))
        
        # Verify that it matches actual empty structures, not hardcoded placeholders
        assert res_data["context"]["preferences"]["data"] == {}
        assert res_data["context"]["account_state"]["data"] == {}
        assert res_data["context"]["issue_history"]["data"] == []
        assert res_data["context"]["transcript_excerpts"]["data"] == []
        assert res_data["context"]["policy_context"]["data"] == []
