"""ASGI app served by uvicorn.

Two endpoints simulating a 100 ms IO call (database query, HTTP request, ...):

- /blocking      uses time.sleep()    -> blocks the event loop
- /non-blocking  uses asyncio.sleep() -> yields control to the event loop

Run (mirrors prod config):
    uv run gunicorn app_async:app \
        --workers=3 \
        --worker-class uvicorn_worker.UvicornWorker \
        --timeout 120 \
        --bind 0.0.0.0:8001 \
        --preload \
        --access-logfile '-'
"""

import asyncio
import time

from fastapi import FastAPI

IO_DURATION = 0.1  # seconds, simulated IO latency

app = FastAPI()


@app.get("/blocking")
async def blocking() -> dict:
    # Simulates blocking IO inside an async handler, e.g. requests.get(),
    # psycopg2 queries, boto3 calls. The entire event loop is frozen for
    # the duration - no other request makes progress.
    time.sleep(IO_DURATION)
    return {"io": "blocking"}


@app.get("/non-blocking")
async def non_blocking() -> dict:
    # Simulates proper async IO, e.g. httpx.AsyncClient, asyncpg.
    # The event loop is free to serve other requests while waiting.
    await asyncio.sleep(IO_DURATION)
    return {"io": "non-blocking"}
