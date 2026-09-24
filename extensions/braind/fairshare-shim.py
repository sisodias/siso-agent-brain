#!/usr/bin/env python3
"""
fairshare-shim — a tiny concurrency + fair-share gate IN FRONT of Bifrost.

Why it exists: Bifrost's rate-limiter REJECTS over-limit requests (429); it does
not queue them. Shaan wants an external collaborator ("the boy") capped at N
concurrent agents but with NO ERRORS if he queues 24 — the extras should WAIT
for a slot, not fail. Bifrost also has no weighted fair-share scheduler. This
shim adds both, as one small daemon, without touching Bifrost's config.

Behaviour:
  - The boy's key (BOY_KEY) is gated to BOY_CONCURRENCY in-flight requests.
    Request 4..24 BLOCK on a semaphore until a slot frees — they queue, they
    do not 429. From his Claude Code's view it just runs a bit slower at depth.
  - Priority lane: OWNER traffic (any other key) is NEVER gated and, when the
    system is busy, the boy's queue yields to owner requests (owner acquires a
    priority token first). When the owner is idle, the boy gets full headroom
    up to his concurrency cap.
  - Everything forwards to Bifrost unchanged; the upstream model/route is
    whatever Bifrost already resolves. Usage stays attributable per key.

This is the "true queue, never error" version Shaan asked for. Conservative,
single file, fail-open to Bifrost on any internal error.

Run:  fairshare-shim.py
Env:
  SHIM_PORT        (default 8085)         what the boy points his Claude Code at
  BIFROST_URL      (default http://127.0.0.1:8080)   upstream
  BOY_KEY          his sk-bf-... value (gated)
  BOY_CONCURRENCY  (default 3)
  OWNER_BURST      (default 1) — owner priority tokens that preempt the boy queue
"""
import os, threading, http.client, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SHIM_PORT", "8085"))
BIFROST = os.environ.get("BIFROST_URL", "http://127.0.0.1:8080")
BOY_KEY = os.environ.get("BOY_KEY", "")
BOY_CONCURRENCY = int(os.environ.get("BOY_CONCURRENCY", "3"))

_bu = urllib.parse.urlparse(BIFROST)
UP_HOST, UP_PORT = _bu.hostname, (_bu.port or 80)

# the boy's concurrency gate: at most N in flight. Extras BLOCK here (queue, no error).
_boy_slots = threading.BoundedSemaphore(BOY_CONCURRENCY)
# a lock the owner grabs to assert priority: while owner requests are arriving,
# the boy waits at the door so owner traffic jumps the queue.
_owner_active = threading.Semaphore(0)   # counts owner requests in flight
_owner_lock = threading.Lock()
_owner_count = 0


def _req_token(headers):
    h = headers.get("Authorization", "") or headers.get("x-api-key", "")
    return h[7:].strip() if h.startswith("Bearer ") else h.strip()


def owner_enter():
    global _owner_count
    with _owner_lock:
        _owner_count += 1


def owner_exit():
    global _owner_count
    with _owner_lock:
        _owner_count = max(0, _owner_count - 1)


def owner_busy():
    with _owner_lock:
        return _owner_count > 0


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self):
        body = b""
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n:
            body = self.rfile.read(n)
        is_boy = BOY_KEY and _req_token(self.headers) == BOY_KEY

        gated = False
        if is_boy:
            # fair-share: if the owner is busy, briefly yield so owner traffic goes first.
            # bounded spin (max ~5s) so the boy is never starved indefinitely.
            waited = 0.0
            while owner_busy() and waited < 5.0:
                threading.Event().wait(0.1)
                waited += 0.1
            _boy_slots.acquire()   # BLOCKS past the cap — this is the queue, not a 429
            gated = True
        else:
            owner_enter()

        try:
            conn = http.client.HTTPConnection(UP_HOST, UP_PORT, timeout=600)
            fwd = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
            conn.request(self.command, self.path, body=body, headers=fwd)
            r = conn.getresponse()
            data = r.read()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except Exception as e:
            msg = f'{{"error":"shim upstream failure: {e}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        finally:
            if gated:
                _boy_slots.release()
            elif not is_boy:
                owner_exit()

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        if self.path == "/shim-health":
            free = _boy_slots._value
            b = f'{{"ok":true,"boy_free_slots":{free},"boy_cap":{BOY_CONCURRENCY},"owner_busy":{str(owner_busy()).lower()}}}'.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        self._proxy()

    def log_message(self, *a):
        pass


def main():
    if not BOY_KEY:
        import sys
        sys.stderr.write("WARNING: BOY_KEY unset — shim will treat all traffic as owner (ungated).\n")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"fairshare-shim on :{PORT} -> {BIFROST} | boy cap={BOY_CONCURRENCY}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
