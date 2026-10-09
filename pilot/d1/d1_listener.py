"""Stand-in 'attacker' server for the D1 test. Logs every request it receives.

  python pilot/d1/d1_listener.py            # listens on 127.0.0.1:9999

The payloads point here instead of attacker.example, so an exfiltration attempt is
*observed*, not inferred. A different port is a different origin, so CSP 'self' must
block it. Zero lines in out/listener.log after the test = no request left the browser.
"""
import datetime
import http.server
import pathlib

LOG = pathlib.Path(__file__).resolve().parent / "out" / "listener.log"
LOG.parent.mkdir(exist_ok=True)
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4f50000000049454e44ae426082")


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        line = f"{datetime.datetime.now().isoformat()} {self.client_address[0]} GET {self.path} referer={self.headers.get('Referer')}"
        print(line, flush=True)
        with open(LOG, "a") as fh:
            fh.write(line + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"listening on http://127.0.0.1:9999, logging to {LOG}")
    http.server.HTTPServer(("127.0.0.1", 9999), H).serve_forever()
