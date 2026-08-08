# Technical Debt — DB Write Hang Under the Live Request Path (Windows)

**Status: MITIGATED, NOT ROOT-CAUSED.** This is Gate 2 of Phase 6's
engineering gates, applied against an issue first documented in
`docs/architecture_priority_classification.md` "Performance." That
document already stated `asyncio.wait_for` "is not yet proven to bound a
hang encountered via the full real request path on Windows" — this
document is the follow-up investigation the prior session flagged as
needed, not a first report of a new bug.

## Observed Behavior

When the DB connection an endpoint's audit-log write depends on can be
established at the TCP level but never completes the application-level
handshake (a stuck/firewalled/unresponsive host — not a fast
"connection refused"), the request hangs indefinitely instead of returning
within the configured `DB_WRITE_TIMEOUT_SECONDS` (3.0s). The ML prediction
itself completes and is logged; the HTTP response is simply never sent.

## Reproduction Status: **REPRODUCED**, reliably, with a minimal harness

`backend/scripts/investigate_db_hang.py` reproduces this on demand:
1. Starts a raw TCP server that accepts connections and then sends nothing
   (the exact shape of "connected but stuck," not "refused")
2. Points the real app's `POSTGRES_HOST`/`POSTGRES_PORT` at it
3. Starts a **real `uvicorn` subprocess** (not `TestClient` — see "Why the
   existing regression test didn't catch this" below)
4. Sends a real HTTP request over a real socket and measures response time

Result on this machine: the client (15s timeout) never receives a
response. Confirmed twice, before and after the mitigation attempt below.

### Why the existing regression test (`tests/test_db_write_timeout.py`) didn't catch this

That test uses Starlette's `TestClient`, which drives the ASGI app
in-process through a fake ASGI transport — no real socket, no real Uvicorn
event-loop setup. It correctly proves `asyncio.wait_for()` can cancel a
plain hanging coroutine *in that harness*. It cannot, by construction,
exercise whatever is different about a real Uvicorn-served request that
makes the same mechanism fail here. This gap is exactly what
`investigate_db_hang.py` closes — it is a deliberate one-off investigation
script, not a replacement for the existing fast unit-level test.

## Investigation Performed

Seven bounded, scripted experiments, each isolating one variable, run in
this order (all reproducible — see `backend/scripts/`):

| # | Script | What it tests | Result |
|---|---|---|---|
| 1 | `investigate_db_hang.py` | Full real app, real Uvicorn, real HTTP request | **Hangs** (reproduced) |
| 2 | *(session.py change)* | Add `connect_args={"timeout": 3.0}` to asyncpg via SQLAlchemy, re-run #1 | **Still hangs** — the fix was kept anyway as defense-in-depth (see "Mitigation Applied" below) because it's safe and correct in isolation, but it does NOT resolve this specific failure mode |
| 3 | `_investigate_bare_asyncio_cancel.py` | `asyncio.wait_for()` around a hung raw-socket read, bare asyncio, no asyncpg/SQLAlchemy/FastAPI | **Cancels correctly** at ~2.0s — rules out a fundamental Windows `ProactorEventLoop` cancellation defect |
| 4 | `_investigate_asyncpg_direct_cancel.py` | `asyncio.wait_for()` around a hung `asyncpg.connect()`, no SQLAlchemy | **Cancels correctly** at ~2.0s — rules out asyncpg itself |
| 5 | `_investigate_sqlalchemy_direct_cancel.py` | `asyncio.timeout()` around a hung SQLAlchemy async engine `connect()`, no FastAPI, no threadpool | **Cancels correctly** at ~2.0s — rules out SQLAlchemy's greenlet bridge in isolation |
| 6 | `_investigate_threadpool_then_sqlalchemy.py` | The exact real-endpoint sequence (`run_in_threadpool(sync_fn)` then `wait_for`-wrapped SQLAlchemy call), bare `asyncio.run()`, no FastAPI | **Cancels correctly** at ~2.0s — rules out the threadpool-then-DB-call sequence in isolation |
| 7 | `_investigate_middleware_smoking_gun.py` | Minimal FastAPI app, real Uvicorn, same sequence as #6, run once **with** `RequestLoggingMiddleware`-equivalent (`BaseHTTPMiddleware`) and once **without** | **Cancels correctly in both variants** at ~2.0s — rules out `BaseHTTPMiddleware` (a real, independently-documented Starlette footgun for cancellation, and the strongest prior hypothesis going in) |
| 8 | *(endpoint code change)* | Replace `asyncio.wait_for(coro, timeout=N)` with `async with asyncio.timeout(N):` in the real endpoint, re-run #1 | **Still hangs** — rules out the specific timeout API as the differentiator; reverted, not shipped, since it fixed nothing and would otherwise be an unexplained diff |

**Every individually-isolated piece of the real request's DB-write path
works correctly under `asyncio.wait_for`/`asyncio.timeout` when tested on
its own, including the exact sequence and the exact middleware class used
in production. Only the full, real application — real trained ML models
loaded, real `PriorityPredictionLog`/`GUID` TypeDecorator ORM model, real
`create_app()` assembly with its full middleware/exception-handler stack —
reproduces the hang.**

## Suspected Root Cause

**Not confirmed.** The investigation above rules out every individually
plausible single-component explanation. The remaining, untested candidates
— genuinely narrowed from "somewhere in async Windows networking" to a
much smaller list — are:

1. **The real ORM write path specifically** (`session.add()` →
   `await session.commit()` → `await session.refresh()`) versus the
   simpler `engine.connect()` used in experiments 5–8. `commit()` and
   `refresh()` involve additional internal SQLAlchemy state (identity map,
   flush process) that `engine.connect()` alone doesn't exercise.
2. **The `GUID` `TypeDecorator`** (`app/models/spam_prediction_log.py`) —
   custom type decorators run extra Python code during flush; untested in
   isolation.
3. **Something specific to `create_app()`'s full assembly** — the real app
   has three ML services warmed at startup (spam, priority, category, each
   loading joblib/spaCy state), the real exception-handling middleware
   (`register_exception_handlers`), and the real `RequestLoggingMiddleware`
   together, not the single minimal middleware used in experiment 7.
4. A genuinely intermittent/timing-dependent failure that experiments 3–8
   simply didn't run enough iterations to catch, even though each was run
   at least twice during this investigation with consistent results.

**No further avenue was pursued this session** — this is a deliberate stop,
not an exhausted one. See "Recommended Next Investigation" below for where
to pick this up.

## Mitigation Applied (this phase)

- **`DB_CONNECT_TIMEOUT_SECONDS` (new, `app/database/session.py`)**: bounds
  asyncpg's own connection-establishment phase via `connect_args={"timeout":
  3.0}`. Verified correct and effective in experiments 4–7 above (every
  isolated scenario). **Verified NOT sufficient on its own** for the full
  reproduced hang (experiment #2). Kept anyway: it is a real, safe,
  independently-correct improvement — a connection that fails at the
  driver level surfaces a clear `TimeoutError`/`OSError` instead of relying
  purely on an outer `wait_for` to reach in and cancel it, which is exactly
  the class of mechanism proven reliable in isolation. Two independent
  layers of the same defense are better than one, even though neither
  alone is proven sufficient for the full failure mode.
- **`DB_WRITE_TIMEOUT_SECONDS` (existing, unchanged)**: still wraps the
  full repository write. **Confirmed, again this phase, NOT sufficient** to
  bound the full real-request-path hang. Retained because it *is* effective
  against every failure mode that isn't this specific one (a raised
  exception, a slow-but-finite query) and removing it would be strictly
  worse, not better.

## Remaining Risk

**Real and unresolved.** A DB host that is reachable at the TCP level but
never completes its handshake (firewall silently dropping packets, a
half-dead Postgres process, certain network partition scenarios) can still
hang a request indefinitely on this specific Windows/Uvicorn configuration,
regardless of the timeouts configured in this codebase. This is a genuine
production risk, not a cosmetic one — Gate 2 explicitly forbids describing
this as solved, and it is not described as solved anywhere in this
repository.

## Production Impact

- **Likelihood**: Requires a specific network failure mode (connects but
  never responds) rather than the more common "connection refused" or
  "DNS failure," both of which already fail fast and are unaffected by
  this issue. Lower likelihood than a generic "DB is down" scenario, but
  not negligible — exactly this shape of failure is a known real-world
  symptom of misconfigured security groups, half-open TCP states behind
  NAT, and split-brain failover scenarios.
- **Blast radius**: Per-request, not global — one hung request does not
  block others (each gets its own connection-pool slot up to `pool_size=5
  + max_overflow=10`), but enough concurrent hung requests could exhaust
  the pool and degrade the whole service.
- **User-facing effect**: The caller's HTTP client eventually times out on
  its own (or never does, if unbounded) — from the caller's perspective,
  this looks identical to the server being completely unresponsive, not a
  clean 503.

## Recommended Next Investigation

In priority order, cheapest/highest-signal first:

1. **Isolate the real ORM write** (experiment 5's scenario, but with an
   actual `session.add(SomeTestModel()); await session.commit()` instead
   of a bare `engine.connect()`) — the single untested variable most
   likely to matter, per "Suspected Root Cause" #1.
2. **Run experiment 7 (middleware smoking gun) with the FULL real
   middleware/exception-handler stack** instead of a single minimal
   `BaseHTTPMiddleware` subclass, to rule in/out cumulative interaction
   effects from `register_exception_handlers` + `RequestLoggingMiddleware`
   together.
3. **Capture a Python-level stack trace of the hung request** (e.g. via
   `faulthandler.dump_traceback()` triggered by a signal, or `py-spy dump`
   against the live Uvicorn worker process) during an active reproduction
   — this would show exactly which line the request is stuck on, which is
   more direct evidence than continuing to isolate by elimination.
4. Only if 1–3 don't resolve it: escalate to asking on the SQLAlchemy or
   Uvicorn issue trackers with the minimal reproduction scripts in this
   directory attached — the investigation here has already done the work
   of ruling out the obvious causes, which is exactly what a well-formed
   upstream bug report needs.

## Explicit Gate 2 Conclusion

**Outcome: B/C hybrid — root cause narrowed substantially but not
identified; a defense-in-depth mitigation was added and verified
individually correct but NOT verified to resolve the full failure mode.**
The timeout mitigations provide bounded failure behavior for every DB
failure mode this codebase has tested EXCEPT the specific "connects but
never completes handshake" case documented here, which remains an accepted,
disclosed, unresolved risk. Phase 6 proceeds on this basis, per Gate 2's
explicit instruction that a phase may continue when "the timeout provides
bounded failure behavior and the remaining risk is explicitly accepted" —
accepted here, in writing, not silently.
