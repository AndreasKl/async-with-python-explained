# Blocking IO in async code, explained

A minimal Django demo proving one thing: **an async stack (uvicorn) gives you
zero benefit — and can even hurt — if your `async def` views make blocking IO
calls.**

## The setup

Two single-file Django apps, each simulating a 100 ms IO call (think: a
database query, an HTTP call to another service):

| File | Interface | Endpoints |
|---|---|---|
| `app_async.py` | Django ASGI | `/blocking` — `time.sleep(0.1)` inside an `async def` view: freezes the event loop. `/non-blocking` — `await asyncio.sleep(0.1)`: yields to the event loop. `/blocking-sync-view` — the same `time.sleep(0.1)` in a plain `def` view: Django runs it in a thread. |
| `app_sync.py` | Django WSGI | `/blocking` — the same `time.sleep(0.1)` in a plain `def` view: normal for a sync worker. |

Both are served by gunicorn with the **same production-style config** — the
only difference is the worker class:

```bash
# ASGI: 3 uvicorn workers (one event loop each)
gunicorn app_async:app \
  --workers=3 \
  --worker-class uvicorn_worker.UvicornWorker \
  --timeout 120 \
  --bind 0.0.0.0:8001 \
  --preload \
  --access-logfile '-'

# WSGI: 3 plain sync workers
gunicorn app_sync:app \
  --workers=3 \
  --timeout 120 \
  --bind 0.0.0.0:8002 \
  --preload \
  --access-logfile '-'
```

## Running the demo

Requires [uv](https://docs.astral.sh/uv/) and [wrk](https://github.com/wg/wrk).

```bash
uv sync
./bench.sh
```

The script starts each server, hits every scenario with
`wrk -t4 -c50 -d10s` (50 concurrent connections for 10 seconds), and prints a
summary. Takes about 45 seconds.

## Results

| Scenario (3 workers each) | Throughput | p99 latency |
|---|---|---|
| ASGI, `async def` view + blocking `time.sleep` | **~20 req/s** (+ timeouts!) | ~1.9 s |
| ASGI, `async def` view + proper `asyncio.sleep` | **~200 req/s** | ~370 ms |
| ASGI, plain `def` view + blocking `time.sleep` | **~350 req/s** | ~310 ms |
| WSGI sync workers, `def` view + blocking `time.sleep` | **~22 req/s** | ~1.6 s |

## What this means

**The math.** Every request "waits on IO" for 100 ms. A single event loop that
is *blocked* during that wait can serve at most 10 req/s — it executes
requests strictly one after another, exactly like a sync worker. So 3 uvicorn
workers running a blocking `async def` view have the same theoretical ceiling
as 3 sync workers: ~30 req/s. All the async machinery buys nothing.

**In practice it's even worse than sync.** The blocking-async run came in at
the same level as the sync run but produced far more request timeouts. Each
uvicorn worker eagerly accepts a batch of connections and *then* freezes on
the blocking call, so accepted requests sit queued behind a dead event loop
and their latencies stack up (p99 ~1.9 s, many past wrk's 2 s timeout). Sync
workers accept only what they can handle; excess connections wait in the
kernel's listen backlog instead of behind a frozen loop.

**Plain sync views are safe under ASGI — by design.** Django's ASGI handler
wraps every request in its own `ThreadSensitiveContext`, so each in-flight
request runs its sync view on its own thread. The identical blocking call
that killed the `async def` view does ~350 req/s in a `def` view. The cost:
one OS thread per concurrent request (unbounded), plus the sync/async
hand-off overhead — fine at this scale, but it is not free concurrency.

**Async pays off when the IO actually yields.** The `async def` view with
`await asyncio.sleep()` — i.e. a driver that cooperates with the event loop,
like `httpx.AsyncClient` or Django's async ORM interface — does ~200 req/s,
limited here by wrk's 50 connections and per-request overhead, not by the
architecture.

## Takeaway

For a Django deployment, the one fatal combination is **blocking IO inside an
`async def` view**: `requests`, `psycopg2`-backed ORM calls, `boto3`, or any
other blocking library freezes the event loop and makes the async stack
perform worse than plain sync workers. The rule:

- Keep views **plain `def`** unless everything inside them is genuinely
  async — Django will thread them safely under ASGI.
- Only write `async def` views that **await all their IO** (async ORM
  queries, `httpx.AsyncClient`, ...). One stray sync call poisons the loop
  for every request on that worker.
