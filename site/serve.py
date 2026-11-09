"""Serve the site locally with caching off, so an edited page or data file always shows up.

Run:  python site/serve.py [--port 8770]   then open http://localhost:8770/web/
Only this computer can reach it (it listens on 127.0.0.1). Errors (status 400 and up) are logged; the rest is quiet.
"""
import argparse
import functools
import http.server
import sys
from pathlib import Path


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        # Browsers fetch audio ranges and favicons all the time: only a failed request is worth a line.
        if isinstance(code, int) and code >= 400:  # code: an HTTPStatus (an int) or "-"
            super().log_request(code, size)

    def log_error(self, fmt, *args):
        pass  # the failed request's own line (log_request) already says it


class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 128     # the default listen backlog (5) drops connections when a page asks for many files at once
    allow_reuse_address = False  # a port another server holds is an error, not shared (Windows would allow both)


def main():
    ap = argparse.ArgumentParser(description="Serve the FUS Forward site on this computer, with caching off.")
    ap.add_argument("--port", type=int, default=8770, help="port to listen on (default 8770)")
    port = ap.parse_args().port
    handler = functools.partial(NoCache, directory=str(Path(__file__).parent))
    try:
        server = Server(("127.0.0.1", port), handler)
    except OSError as e:
        sys.exit(f"Could not serve on port {port}: {e.strerror or e}. Is the site already running? "
                 f"Stop it, or pick another port: python site/serve.py --port {port + 1}")
    print(f"Serving FUS Forward at http://localhost:{port}/web/ (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
