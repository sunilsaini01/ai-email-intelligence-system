"""
Smoking-gun test: a minimal FastAPI app with the exact real-endpoint
sequence (run_in_threadpool -> asyncio.wait_for(hung SQLAlchemy call)),
run twice via real Uvicorn subprocesses -- once WITH
RequestLoggingMiddleware (a BaseHTTPMiddleware subclass) registered, once
WITHOUT -- to prove or disprove that BaseHTTPMiddleware is what breaks
cancellation on this machine's real Uvicorn/ProactorEventLoop stack.
"""

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
FAKE_DB_PORT = 55494


def run_fake_hanging_server(port: int, stop_event: threading.Event):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)
    server.settimeout(0.5)
    conns = []
    while not stop_event.is_set():
        try:
            conn, _ = server.accept()
            conns.append(conn)
        except socket.timeout:
            continue
    for c in conns:
        c.close()
    server.close()


APP_TEMPLATE = '''
import asyncio
import time
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import create_async_engine

USE_MIDDLEWARE = {use_middleware}

app = FastAPI()

if USE_MIDDLEWARE:
    from starlette.middleware.base import BaseHTTPMiddleware

    class NoopLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            return response

    app.add_middleware(NoopLoggingMiddleware)

engine = create_async_engine(
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:{fake_db_port}/postgres",
    connect_args={{"timeout": 2.0}},
)


def cpu_bound_work():
    return sum(i * i for i in range(200_000))


@app.get("/test")
async def test_endpoint():
    result = await run_in_threadpool(cpu_bound_work)
    start = time.perf_counter()
    try:
        async with asyncio.timeout(3.0):
            async with engine.connect():
                pass
        return {{"status": "connected (unexpected)"}}
    except TimeoutError:
        elapsed = time.perf_counter() - start
        return {{"status": "bounded", "elapsed": elapsed}}
'''


def run_variant(use_middleware: bool) -> None:
    app_code = APP_TEMPLATE.format(use_middleware=use_middleware, fake_db_port=FAKE_DB_PORT)
    app_file = BACKEND_DIR / "scripts" / "_smoking_gun_app.py"
    app_file.write_text(app_code, encoding="utf-8")

    port = 58200 if use_middleware else 58201
    label = "WITH BaseHTTPMiddleware" if use_middleware else "WITHOUT any middleware"
    print(f"\n=== {label} ===")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "_smoking_gun_app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND_DIR / "scripts"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 15
        up = False
        while time.time() < deadline:
            try:
                r = requests.get(f"http://127.0.0.1:{port}/docs", timeout=1)
                up = r.status_code == 200
                if up:
                    break
            except requests.exceptions.RequestException:
                time.sleep(0.3)
        if not up:
            print("  server never started")
            return

        start = time.perf_counter()
        try:
            r = requests.get(f"http://127.0.0.1:{port}/test", timeout=10)
            elapsed = time.perf_counter() - start
            print(f"  RESPONSE after {elapsed:.2f}s: {r.json()}")
        except requests.exceptions.Timeout:
            elapsed = time.perf_counter() - start
            print(f"  CLIENT TIMED OUT after {elapsed:.2f}s -- hang reproduced with this config")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        app_file.unlink(missing_ok=True)


def main():
    stop_event = threading.Event()
    t = threading.Thread(target=run_fake_hanging_server, args=(FAKE_DB_PORT, stop_event), daemon=True)
    t.start()
    time.sleep(0.5)

    run_variant(use_middleware=True)
    run_variant(use_middleware=False)

    stop_event.set()


if __name__ == "__main__":
    main()
