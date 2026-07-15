"""Django WSGI app served by gunicorn sync workers.

One endpoint with the same simulated 100 ms blocking IO call. Blocking is
normal here: the sync worker parks on the call, and the other workers
keep serving requests.

Run (mirrors prod config):
    uv run gunicorn app_sync:app \
        --workers=3 \
        --timeout 120 \
        --bind 0.0.0.0:8002 \
        --preload \
        --access-logfile '-'
"""

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


def blocking(request: HttpRequest) -> JsonResponse:
    # Same blocking call as in the async app - but in a sync stack this
    # only occupies one worker process, exactly as the model expects.
    time.sleep(IO_DURATION)
    return JsonResponse({"io": "blocking"})


urlpatterns = [
    path("blocking", blocking),
]

# Imported lazily so settings.configure() above runs first.
from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
