"""
One-off diagnostic: does asyncio.wait_for() cancel a hung SQLAlchemy async
engine connect/commit, called directly (no FastAPI, no run_in_threadpool)?
If this ALSO hangs past its timeout, the bug is in SQLAlchemy's async
engine / greenlet bridge itself. If this succeeds (unlike the real
end-to-end reproduction in investigate_db_hang.py), the bug is specific to
the FastAPI request-handling context (e.g. an interaction with
run_in_threadpool's anyio worker thread having already run earlier in the
same request).
"""

import asyncio
import socket
import threading
import time

from sqlalchemy.ext.asyncio import create_async_engine

PORT = 55496


def run_fake_hanging_server(stop_event: threading.Event):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", PORT))
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


async def main():
    stop_event = threading.Event()
    t = threading.Thread(target=run_fake_hanging_server, args=(stop_event,), daemon=True)
    t.start()
    time.sleep(0.5)

    engine = create_async_engine(
        f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{PORT}/postgres",
        connect_args={"timeout": 2.0},
    )

    start = time.perf_counter()
    try:
        async with asyncio.timeout(4.0):  # outer safety net, same role as DB_WRITE_TIMEOUT_SECONDS
            async with engine.connect() as conn:
                print("UNEXPECTED: connected")
    except TimeoutError:
        elapsed = time.perf_counter() - start
        print(f"RAISED TimeoutError after {elapsed:.2f}s")
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"RAISED after {elapsed:.2f}s: {type(e).__name__}: {e}")

    stop_event.set()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
