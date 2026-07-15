"""Django ASGI app served by uvicorn workers.

Three endpoints simulating a 100 ms IO call (database query, HTTP request, ...):

- /blocking           async view + time.sleep()    -> blocks the event loop
- /non-blocking       async view + asyncio.sleep() -> yields to the event loop
- /blocking-sync-view SYNC view + time.sleep()     -> Django wraps each request
                      in its own ThreadSensitiveContext, so every in-flight
                      request gets its own thread: blocking is absorbed.

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

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.urls import path

IO_DURATION = 0.1  # seconds, simulated IO latency

settings.configure(
    DEBUG=False,
    SECRET_KEY="bench-only",
    ALLOWED_HOSTS=["*"],
    ROOT_URLCONF=__name__,
)


async def blocking(request: HttpRequest) -> JsonResponse:
    # Simulates blocking IO inside an async view, e.g. requests.get(),
    # psycopg2 queries, boto3 calls, or the sync Django ORM. The entire
    # event loop is frozen for the duration - no other request progresses.
    time.sleep(IO_DURATION)
    return JsonResponse({"io": "blocking"})


async def non_blocking(request: HttpRequest) -> JsonResponse:
    # Simulates proper async IO, e.g. httpx.AsyncClient, the async ORM
    # on an async-capable backend. The event loop stays free.
    await asyncio.sleep(IO_DURATION)
    return JsonResponse({"io": "non-blocking"})


def blocking_sync_view(request: HttpRequest) -> JsonResponse:
    # Same blocking call in a plain sync view. Django's ASGI handler runs
    # each request in its own ThreadSensitiveContext (one thread per
    # in-flight request), so blocking here does NOT stall other requests -
    # at the cost of one OS thread per concurrent request.
    time.sleep(IO_DURATION)
    return JsonResponse({"io": "blocking-sync-view"})


urlpatterns = [
    path("blocking", blocking),
    path("non-blocking", non_blocking),
    path("blocking-sync-view", blocking_sync_view),
]

# Imported lazily so settings.configure() above runs first.
from django.core.asgi import get_asgi_application  # noqa: E402

app = get_asgi_application()
