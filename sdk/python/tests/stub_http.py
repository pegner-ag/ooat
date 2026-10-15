"""A scripted HTTP server on a loopback port for the client's tests: each request gets the next reply."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Stub:
    """Replies are (status, body), (status, body, content type) or a callable that writes the reply itself; a dict
    body is sent as JSON. Every request is kept in `requests` with its method, path, headers and body."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                stub.requests.append({"method": self.command, "path": self.path, "headers": self.headers,
                                      "body": self.rfile.read(length)})
                reply = stub.replies.pop(0)
                if callable(reply):
                    reply(self)
                    return
                status, body, *rest = reply
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", rest[0] if rest else "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_DELETE = serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
