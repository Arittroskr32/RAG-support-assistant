"""KB-1: per-session sliding-window request counts (Redis, with an in-memory fallback).

Session keys are created server-side by the API (authenticated user id, or client IP for
anonymous callers) — never taken from the request.
"""
import threading
import time
import uuid

from config.settings import MODEL_SETTINGS

_memory_store: dict[str, list[float]] = {}
_memory_lock = threading.Lock()
_last_sweep = 0.0

try:
    import redis
    _r = redis.Redis(host=MODEL_SETTINGS.redis_host, port=MODEL_SETTINGS.redis_port, db=0,
                     decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    _r.ping()
    REDIS_AVAILABLE = True
except Exception:
    _r = None
    REDIS_AVAILABLE = False


def _sweep_memory(now: float, window_s: int) -> None:
    """Drop sessions with no requests inside the window (prevents unbounded growth).
    Caller holds _memory_lock."""
    global _last_sweep
    if now - _last_sweep < window_s:
        return
    _last_sweep = now
    for key in [k for k, ts in _memory_store.items() if not ts or ts[-1] <= now - window_s]:
        del _memory_store[key]


def record_request(session_id: str, window_s: int = 60) -> int:
    """Records one request and returns the request count in the trailing window."""
    key = f"rate:{session_id}"
    now = time.time()
    if REDIS_AVAILABLE:
        # Unique member per request — a timestamp alone would collapse every request in the
        # same second into one sorted-set entry and undercount bursts.
        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
        pipe = _r.pipeline()
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, 0, now - window_s)
        pipe.zcard(key)
        pipe.expire(key, window_s * 2)
        return pipe.execute()[2]
    with _memory_lock:
        bucket = [t for t in _memory_store.get(key, []) if t > now - window_s]
        bucket.append(now)
        _memory_store[key] = bucket
        _sweep_memory(now, window_s)
        return len(bucket)


def get_ip_reputation(ip: str) -> float:
    # Stub — wire up a real threat-intel feed (e.g. AbuseIPDB) here for production.
    return 0.0
