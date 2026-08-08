"""
Phase 6 Gate 2 — one-off investigation script for the documented DB-write
hang (docs/architecture_priority_classification.md "Performance"). NOT a
permanent test (a real subprocess Uvicorn server + a raw fake-Postgres
socket is too slow/flaky for CI) — this is a deliberate, bounded
investigation, run once, with its output captured into
docs/technical_debt/database_write_hang.md.

What test_db_write_timeout.py does NOT prove: it uses Starlette's
TestClient, which runs the ASGI app in-process via a fake ASGI transport —
no real socket, no real Uvicorn event loop. The originally-reported bug was
specifically about the timeout NOT reliably bounding a hang reached via a
REAL Uvicorn request (see the architecture doc's "third, distinct,
NOT-yet-fixed issue"). This script closes that gap by running a real
`uvicorn` subprocess and sending a real HTTP request over a real TCP
socket, against a fake "Postgres" that accepts the TCP connection and then
never responds (the exact failure shape a stuck/firewalled DB host
produces — a connection that neither completes nor is refused).

Usage:
    PYTHONPATH=backend python backend/scripts/investigate_db_hang.py
"""

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

FAKE_DB_PORT = 55499
APP_PORT = 58123


def run_fake_hanging_postgres(port: int, stop_event: threading.Event):
    """
    Accepts TCP connections and then does nothing — never sends the
    Postgres startup response, never closes the connection. This is what a
    genuinely stuck/firewalled DB host looks like at the TCP level: the
    connection is established (so this is NOT a fast "connection refused"),
    but the protocol handshake never completes.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)
    server.settimeout(0.5)
    print(f"[fake-pg] listening on 127.0.0.1:{port}, accepting and then hanging")

    conns = []
    while not stop_event.is_set():
        try:
            conn, addr = server.accept()
            print(f"[fake-pg] accepted connection from {addr} -- holding it open, sending nothing")
            conns.append(conn)
        except socket.timeout:
            continue
    for c in conns:
        c.close()
    server.close()


def main():
    stop_event = threading.Event()
    fake_pg_thread = threading.Thread(
        target=run_fake_hanging_postgres, args=(FAKE_DB_PORT, stop_event), daemon=True
    )
    fake_pg_thread.start()
    time.sleep(0.5)

    env = {
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(FAKE_DB_PORT),
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "POSTGRES_DB": "email_intelligence",
        "PYTHONPATH": str(BACKEND_DIR),
    }
    import os

    full_env = {**os.environ, **env}

    print(f"[investigate] starting real uvicorn subprocess on 127.0.0.1:{APP_PORT}")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(APP_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        # Wait for the server to come up (health check, not the endpoint
        # under test -- avoids conflating startup time with request time).
        deadline = time.time() + 30
        up = False
        while time.time() < deadline:
            try:
                r = requests.get(f"http://127.0.0.1:{APP_PORT}/api/v1/health", timeout=1)
                if r.status_code == 200:
                    up = True
                    break
            except requests.exceptions.RequestException:
                time.sleep(0.5)
        if not up:
            print("[investigate] server never came up -- aborting")
            print(proc.stdout.read() if proc.stdout else "")
            return

        print("[investigate] server is up. Sending POST /api/v1/priority/predict "
              "against the fake hanging DB, with a client-side timeout of 15s "
              "(DB_WRITE_TIMEOUT_SECONDS is 3.0s in code -- expecting ~3s if the "
              "fix works, a 15s client timeout if it does not).")

        start = time.perf_counter()
        try:
            r = requests.post(
                f"http://127.0.0.1:{APP_PORT}/api/v1/priority/predict",
                json={
                    "subject": "URGENT: investigate hang",
                    "body": "Testing whether the DB write timeout bounds a real hang.",
                },
                timeout=15,
            )
            elapsed = time.perf_counter() - start
            print(f"[investigate] RESPONSE RECEIVED after {elapsed:.2f}s -- status {r.status_code}")
            if elapsed < 5:
                print("[investigate] CONCLUSION: timeout bounded the hang correctly on this run.")
            else:
                print("[investigate] CONCLUSION: response took far longer than the 3s configured "
                      "timeout -- the wait_for mechanism did NOT bound this real-request-path hang.")
        except requests.exceptions.Timeout:
            elapsed = time.perf_counter() - start
            print(f"[investigate] CLIENT TIMED OUT after {elapsed:.2f}s waiting for a response.")
            print("[investigate] CONCLUSION: the server never responded within 15s -- "
                  "the documented hang REPRODUCES on this machine.")
    finally:
        stop_event.set()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        remaining_output = proc.stdout.read() if proc.stdout else ""
        if remaining_output.strip():
            print("\n[investigate] server log tail:\n" + remaining_output[-3000:])


if __name__ == "__main__":
    main()
