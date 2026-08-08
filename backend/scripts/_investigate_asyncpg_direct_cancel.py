"""
One-off diagnostic: does asyncio.wait_for() cancel a hung asyncpg.connect()
call directly (asyncpg only, no SQLAlchemy, no greenlet bridging)? Narrows
whether the Gate 2 hang is inside asyncpg itself or introduced by
SQLAlchemy's greenlet-based sync/async bridge on top of it.
"""

import asyncio
import socket
import threading
import time

import asyncpg

PORT = 55497


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

    start = time.perf_counter()
    try:
        # asyncpg.connect's own `timeout` kwarg -- same one wired into
        # session.py's connect_args this phase.
        conn = await asyncio.wait_for(
            asyncpg.connect(host="127.0.0.1", port=PORT, user="postgres",
                             password="postgres", database="postgres", timeout=2.0),
            timeout=3.0,
        )
        print(f"UNEXPECTED: connected after {time.perf_counter()-start:.2f}s")
        await conn.close()
    except (TimeoutError, asyncpg.exceptions.PostgresError, OSError) as e:
        elapsed = time.perf_counter() - start
        print(f"RAISED after {elapsed:.2f}s: {type(e).__name__}: {e}")
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"UNEXPECTED after {elapsed:.2f}s: {type(e).__name__}: {e}")

    stop_event.set()


if __name__ == "__main__":
    asyncio.run(main())
