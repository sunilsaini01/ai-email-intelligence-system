"""
One-off diagnostic (not a permanent script): does asyncio.wait_for()
successfully cancel a hung TCP connect() at all on this machine's default
event loop (ProactorEventLoop on Windows), with NO asyncpg/SQLAlchemy/
FastAPI/greenlet involved? Isolates whether the Phase 6 Gate 2 hang is a
driver/ORM-layer problem or a lower-level platform one.
"""

import asyncio
import socket
import threading
import time

PORT = 55498


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

    print(f"event loop class: {type(asyncio.get_event_loop()).__name__}")

    async def read_forever():
        reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
        print("connected -- now waiting for data that will never arrive")
        data = await reader.read(100)  # will hang -- server never sends anything
        print("got data (should never print):", data)

    start = time.perf_counter()
    try:
        await asyncio.wait_for(read_forever(), timeout=2.0)
        print(f"UNEXPECTED: completed without raising after {time.perf_counter()-start:.2f}s")
    except TimeoutError:
        elapsed = time.perf_counter() - start
        print(f"CANCELLED CORRECTLY after {elapsed:.2f}s (expected ~2.0s)")
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"UNEXPECTED EXCEPTION after {elapsed:.2f}s: {type(e).__name__}: {e}")

    stop_event.set()


if __name__ == "__main__":
    asyncio.run(main())
