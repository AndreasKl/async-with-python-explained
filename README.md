# Blocking IO in async code, explained

A minimal demo proving one thing: **an async stack (uvicorn) gives you zero
benefit — and can even hurt — if your handlers make blocking IO calls.**

## The setup

Two tiny apps, each simulating a 100 ms IO call (think: a database query, an
HTTP call to another service):

| File | Framework | Endpoints |
|---|---|---|
| `app_async.py` | FastAPI (ASGI) | `/blocking` uses `time.sleep(0.1)` inside `async def` — freezes the event loop. `/non-blocking` uses `await asyncio.sleep(0.1)` — yields to the event loop. |
| `app_sync.py` | Flask (WSGI) | `/blocking` uses the same `time.sleep(0.1)` — normal for a sync worker. |

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
summary. Takes about 35 seconds.

## Results

| Scenario (3 workers each) | Throughput | p99 latency |
|---|---|---|
| uvicorn workers + blocking `time.sleep` | **~15 req/s** (+ timeouts!) | ~1.9 s |
| uvicorn workers + proper `asyncio.sleep` | **~400 req/s** | ~170 ms |
| sync workers + blocking `time.sleep` | **~29 req/s** | ~1.6 s |

## What this means

**The math.** Every request "waits on IO" for 100 ms. A single event loop that
is *blocked* during that wait can serve at most 10 req/s — it executes
requests strictly one after another, exactly like a sync worker. So 3 uvicorn
workers with blocking calls have the same theoretical ceiling as 3 sync
workers: ~30 req/s. All the async machinery buys nothing.

**In practice it's even worse than sync.** The async run came in *below* the
sync run (~15 vs ~29 req/s) and produced request timeouts. Why: each uvicorn
worker eagerly accepts a batch of connections and *then* freezes on the
blocking call, so accepted requests sit queued behind a dead event loop and
their latencies stack up (p99 ~1.9 s, some past wrk's 2 s timeout). Sync
workers accept only what they can handle; excess connections wait in the
kernel's listen backlog instead of behind a frozen loop.

**Async only pays off when the IO actually yields.** The identical stack with
`await asyncio.sleep()` — i.e. a driver that cooperates with the event loop,
like `httpx.AsyncClient` or `asyncpg` — does ~400 req/s at ~120 ms median
latency, limited here only by wrk's 50 connections.

## Takeaway

Switching to uvicorn/ASGI is not a performance upgrade by itself. If handlers
still call `requests`, `psycopg2`, `boto3`, or any other blocking library,
the event loop serializes everything and you end up **no better — often
worse — than plain gunicorn sync workers**. Either go async all the way down
(async drivers for every IO call), or stay sync and scale with workers.
Half-async is the worst of both worlds.
