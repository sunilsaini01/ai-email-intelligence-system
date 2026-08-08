"""
One-off diagnostic: the SMOKING-GUN test. Reproduces the exact sequence
the real endpoint performs -- await run_in_threadpool(sync_fn) THEN
await asyncio.wait_for(sqlalchemy_call) -- with everything else (FastAPI,
the ML model, the real DB) removed, to prove or disprove that this specific
sequence is what breaks cancellation on Windows ProactorEventLoop.
"""

import asyncio
import socket
import threading
import time

from anyio.to_thread import run_sync as run_in_threadpool
from sqlalchemy.ext.asyncio import create_async_engine

PORT = 55495


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


def cpu_bound_work():
    """Stands in for SpamService/PriorityService/CategoryService.classify()
    -- a plain synchronous function run via run_in_threadpool."""
    total = sum(i * i for i in range(200_000))
    return total


async def handle_one_request(engine):
    """Mirrors app/api/v1/endpoints/priority.py's predict_priority():
    run_in_threadpool for the sync inference call, THEN asyncio.wait_for
    around the DB write."""
    result = await run_in_threadpool(cpu_bound_work)
    print(f"  threadpool result: {result}")

    start = time.perf_counter()
    try:
        async with asyncio.timeout(3.0):
            async with engine.connect():
                print("  UNEXPECTED: connected")
    except TimeoutError:
        elapsed = time.perf_counter() - start
        print(f"  DB call raised TimeoutError after {elapsed:.2f}s (correctly bounded)")
        return True
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"  DB call raised after {elapsed:.2f}s: {type(e).__name__}: {e}")
        return True
    print(f"  DB call NEVER RAISED -- hung past its 3.0s timeout "
          f"({time.perf_counter()-start:.2f}s elapsed and counting when this line ran)")
    return False


async def main():
    stop_event = threading.Event()
    t = threading.Thread(target=run_fake_hanging_server, args=(stop_event,), daemon=True)
    t.start()
    time.sleep(0.5)

    engine = create_async_engine(
        f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{PORT}/postgres",
        connect_args={"timeout": 2.0},
    )

    print("Run 1: threadpool call THEN DB call (mirrors the real endpoint sequence)")
    try:
        bounded = await asyncio.wait_for(handle_one_request(engine), timeout=10.0)
        if not bounded:
            print("  (would have hung indefinitely without the outer 10s test harness timeout)")
    except TimeoutError:
        print("  OUTER HARNESS TIMEOUT (10s) HIT -- the DB call's own 3.0s timeout "
              "did NOT fire. REPRODUCED.")

    stop_event.set()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
