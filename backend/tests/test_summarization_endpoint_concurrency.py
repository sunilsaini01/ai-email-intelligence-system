"""
Regression test for a real bug found and fixed in this phase: the
abstractive path's model warm-up (`get_abstractive_summarizer()`) was
called directly in the async route body instead of via
`run_in_threadpool`. On a cold process, that call does ~115s of blocking
work (model download + deserialization) — called directly, it would
freeze the ENTIRE event loop for that whole window, hanging every other
concurrent request this worker is serving (health checks, spam/priority/
category predictions, everything), not just the one abstractive request.

Why this test checks WHICH THREAD the call actually ran on, rather than
racing a concurrent request against it on timing: an earlier version of
this test tried exactly that (fire an abstractive request, then a
"concurrent" health check, assert the health check comes back fast). It
was unreliable in both directions — a version using a bare `client.post()`
without `asyncio.create_task()` passed regardless of whether the bug was
present (the "concurrent" request was never actually started concurrently
at all), and even after fixing that, FastAPI's own dependency-resolution
await points before the route body executes meant the health check could
race ahead of the abstractive task reaching its blocking call by sheer
scheduling luck — passing even with the bug reintroduced. Asserting which
OS thread the warm-up call executed on is deterministic and has no such
race: `run_in_threadpool` always dispatches to a worker thread, so a
passing test here is direct evidence the call is (still) wrapped, not a
probabilistic inference from timing.
"""

import threading

import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_abstractive_warmup_runs_on_a_worker_thread_not_the_event_loop():
    main_thread_id = threading.get_ident()
    observed_thread_ids = []

    def _fake_warmup():
        observed_thread_ids.append(threading.get_ident())
        raise RuntimeError("stand-in for a real model — not actually returning one")

    import app.nlp.abstractive_summarizer as abstractive_module

    original = abstractive_module.get_abstractive_summarizer
    abstractive_module.get_abstractive_summarizer = _fake_warmup
    try:
        from httpx import ASGITransport, AsyncClient

        app = create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/summarization/predict",
                json={
                    "body": ". ".join(f"filler sentence number {i} here today" for i in range(40)) + ".",
                    "summary_type": "abstractive",
                },
            )
    finally:
        abstractive_module.get_abstractive_summarizer = original

    assert response.status_code == 503  # the fake warmup's RuntimeError, surfaced cleanly
    assert len(observed_thread_ids) == 1, "get_abstractive_summarizer() should have been called exactly once"
    assert observed_thread_ids[0] != main_thread_id, (
        "get_abstractive_summarizer() ran on the event loop's own thread, not a worker thread -- "
        "it is no longer wrapped in run_in_threadpool in app/api/v1/endpoints/summarization.py. "
        "On a real cold process this call does ~115s of blocking work; called directly like this, "
        "it would freeze every other concurrent request this worker is serving, not just this one."
    )
