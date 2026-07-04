"""
server.py — Built-in http.server exposing POST /chat and serving the frontend.
"""

import sys
import json
import logging
import pathlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# Ensure project root is in sys.path
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config
from src.orchestrator import (
    handle_message,
    handle_message_stream,
    _SESSION_CONTEXT_CACHE,
    _SESSION_RAG_CACHE
)
from src.identity_resolver import resolve_user_id
from src.session import get_active_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path in ("/", "/index.html"):
            index_path = project_root / "frontend" / "index.html"
            if index_path.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(index_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "frontend/index.html not found")
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/chat":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception as e:
                self.send_error(400, f"Invalid JSON: {e}")
                return

            identifier = data.get("identifier")
            message = data.get("message")
            session_id = data.get("session_id")

            if not identifier or not message:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing identifier or message"}).encode('utf-8'))
                return

            # Resolve user_id and session_id before handling
            user_id = resolve_user_id(identifier)
            session_id_to_use = session_id or get_active_session(user_id)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                for chunk in handle_message_stream(identifier, message, session_id=session_id_to_use):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode('utf-8'))
                    self.wfile.flush()
            except Exception as e:
                logger.error(f"Error streaming chat response: {e}")
        else:
            self.send_error(404, "Not Found")

def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, ChatServerHandler)
    logger.info(f"Starting server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        logger.info("Server stopped.")

if __name__ == '__main__':
    run()
