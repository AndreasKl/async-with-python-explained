#!/usr/bin/env bash
# Demo: blocking IO in an async stack (uvicorn workers) removes all benefit
# of async.
#
# Both servers run with the SAME prod-style gunicorn config (3 workers,
# --preload, --timeout 120); the only difference is the worker class.
# Three scenarios, each hammered with wrk (50 connections, 10s):
#
#   1. UvicornWorker, async handler, time.sleep(0.1)    -> ~30 req/s
#   2. UvicornWorker, async handler, asyncio.sleep(0.1) -> ~500 req/s
#   3. sync worker,   sync handler,  time.sleep(0.1)    -> ~30 req/s
#
# Conclusion: with blocking IO, the async stack (1) performs exactly like
# plain sync workers (3) - zero benefit. Only truly non-blocking IO (2)
# delivers what async promises.

set -euo pipefail
cd "$(dirname "$0")"

DURATION=10s
CONNECTIONS=50
WRK_THREADS=4

ASGI_PORT=8001
WSGI_PORT=8002

declare -a NAMES RESULTS

wait_ready() {
    for _ in $(seq 100); do
        curl -sf "$1" > /dev/null && return 0
        sleep 0.1
    done
    echo "server at $1 did not come up" >&2
    exit 1
}

bench() {
    local name=$1 url=$2
    echo
    echo "=== $name ==="
    echo "    wrk -t$WRK_THREADS -c$CONNECTIONS -d$DURATION $url"
    local out
    out=$(wrk -t"$WRK_THREADS" -c"$CONNECTIONS" -d"$DURATION" --latency "$url")
    echo "$out"
    NAMES+=("$name")
    RESULTS+=("$(echo "$out" | awk '/Requests\/sec/ {print $2}')")
}

cleanup() {
    kill $(jobs -p) 2> /dev/null || true
}
trap cleanup EXIT

echo ">>> Starting gunicorn with Uvicorn workers (port $ASGI_PORT)"
echo "    3 workers, each a single event loop - access log in asgi.log"
uv run gunicorn app_async:app \
    --workers=3 \
    --worker-class uvicorn_worker.UvicornWorker \
    --timeout 120 \
    --bind "127.0.0.1:$ASGI_PORT" \
    --preload \
    --access-logfile '-' > asgi.log 2>&1 &
ASGI_PID=$!
wait_ready "http://127.0.0.1:$ASGI_PORT/non-blocking"

bench "async stack + BLOCKING IO (time.sleep in async def)" \
    "http://127.0.0.1:$ASGI_PORT/blocking"
bench "async stack + proper async IO (asyncio.sleep)" \
    "http://127.0.0.1:$ASGI_PORT/non-blocking"

kill $ASGI_PID
wait $ASGI_PID 2> /dev/null || true

echo
echo ">>> Starting gunicorn with sync workers (port $WSGI_PORT)"
echo "    3 workers, plain WSGI - access log in wsgi.log"
uv run gunicorn app_sync:app \
    --workers=3 \
    --timeout 120 \
    --bind "127.0.0.1:$WSGI_PORT" \
    --preload \
    --access-logfile '-' > wsgi.log 2>&1 &
WSGI_PID=$!
wait_ready "http://127.0.0.1:$WSGI_PORT/blocking"

bench "sync stack + BLOCKING IO (time.sleep, 3 sync workers)" \
    "http://127.0.0.1:$WSGI_PORT/blocking"

kill $WSGI_PID
wait $WSGI_PID 2> /dev/null || true

echo
echo "==================== SUMMARY ===================="
for i in "${!NAMES[@]}"; do
    printf "%-55s %10s req/s\n" "${NAMES[$i]}" "${RESULTS[$i]}"
done
echo "================================================="
echo "Every request 'waits on IO' for 100 ms. With blocking calls, each"
echo "uvicorn worker degrades to strictly serial execution: 3 workers ="
echo "~30 req/s, identical to 3 plain sync workers. The async stack buys"
echo "nothing unless the IO is actually non-blocking."
