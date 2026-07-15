# Notes: threads, the GIL, and thread-safety in Django

## Who provides the thread

- ASGI + sync view: the `ASGIHandler` wraps each request in its own
  `ThreadSensitiveContext` and runs the view via `sync_to_async` on a
  thread created for that request. The whole request is guaranteed to
  stay on that one thread. Threads are unbounded: one per in-flight
  request.
- WSGI gthread: a thread from gunicorn's fixed pool owns the whole
  request - HTTP parsing, handler, middleware, view, response. No
  asgiref machinery involved; pool size = hard concurrency cap.
- async view under WSGI: runs via `async_to_sync` - a per-request event
  loop on the worker thread. Works, but nothing to yield to; no
  concurrency gained. Avoid.

## GIL

- Only one thread executes Python bytecode at a time per process.
- Blocking IO calls (sockets, `time.sleep`, DB drivers, `requests`)
  release the GIL while waiting -> threads overlap fine for IO-bound
  work.
- The GIL only bites on CPU work (template rendering, big JSON,
  tokenizing) - that serializes within a process. Scale CPU with worker
  processes, not threads.
- CPU work in an async view is worst: blocks the event loop AND holds
  the GIL.

## Thread-safety

- Django assumes threaded servers since forever; the contract is
  "one request = one thread, share nothing between requests":
  - request-scoped state lives on the `request` object
  - ORM connections are thread-local
  - views, middleware, forms are instantiated per request
- Danger zone is module-level mutable state, same in every threaded
  setup:
  - global dicts used as caches
  - lazy singletons (`if _client is None: _client = Client()` is a race)
  - counters
  - non-thread-safe library objects (shared `sqlite3` connection, some
    C-extension clients)
- Rule of thumb: code that is correct on threaded WSGI is correct on
  ASGI sync views. No extra "thread awareness" needed.

## Thread lifetime (the actual difference)

- gthread reuses pool threads:
  - persistent DB connections (`CONN_MAX_AGE > 0`) work
  - custom `threading.local()` state leaks into the next request if not
    cleared
- ASGI sync views get a fresh thread per request:
  - custom thread-locals cannot leak (thread dies)
  - thread-local DB connections die too -> `CONN_MAX_AGE` buys nothing
    and can leak connections; Django docs say use `CONN_MAX_AGE=0` in
    async contexts
  - if per-request connection setup hurts: Django 5.1+ psycopg pool
    (`"OPTIONS": {"pool": True}`, shared across threads) or pgbouncer

## Takeaway

- GIL: non-issue for IO-bound views, in both models.
- Thread-safety: same discipline threaded WSGI always required.
- Real difference: thread lifetime -> revisit DB connection pooling
  under ASGI, `CONN_MAX_AGE` reuse silently stops working.
