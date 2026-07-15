"""WSGI app served by gunicorn.

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

from flask import Flask

IO_DURATION = 0.1  # seconds, simulated IO latency

app = Flask(__name__)


@app.get("/blocking")
def blocking() -> dict:
    # Same blocking call as in the async app - but in a sync stack this
    # only occupies one worker process, exactly as the model expects.
    time.sleep(IO_DURATION)
    return {"io": "blocking"}
