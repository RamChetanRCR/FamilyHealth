# ponytail: stdlib http.server serves the UI and proxies API paths to the
# backend — replaces nginx, no dependencies. Swap to nginx/a real reverse
# proxy when this needs TLS, buffering or concurrent-heavy traffic.
import http.server
import os
import pathlib
import urllib.error
import urllib.request

API = os.getenv("API_URL", "http://127.0.0.1:18100")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "18080"))
ROOT = pathlib.Path(__file__).parent
PREFIXES = (
    "/family-members", "/inventory",
    "/health", "/docs", "/redoc", "/openapi.json",
)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _proxy(self):
        body = None
        if self.command in ("POST", "PUT", "PATCH"):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = urllib.request.Request(API + self.path, data=body, method=self.command)
        for header in ("Content-Type", "Accept"):
            if self.headers.get(header):
                req.add_header(header, self.headers[header])
        try:
            with urllib.request.urlopen(req) as response:
                data, status = response.read(), response.status
                ctype = response.headers.get_content_type()
        except urllib.error.HTTPError as error:
            data, status = error.read(), error.code
            ctype = error.headers.get_content_type()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith(PREFIXES):
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def log_message(self, *args):
        pass  # quiet: no request logging


if __name__ == "__main__":
    print(f"frontend on http://{HOST}:{PORT} -> API {API}")
    http.server.ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
