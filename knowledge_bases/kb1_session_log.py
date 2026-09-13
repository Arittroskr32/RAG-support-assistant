import time

try:
    import redis
    _r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    _r.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False
    _memory_store = {}


def record_request(session_id: str) -> int:
    """Returns request count in the trailing 60s window for this session."""
    key = f"rate:{session_id}"
    now = int(time.time())
    if REDIS_AVAILABLE:
        _r.zadd(key, {str(now): now})
        _r.zremrangebyscore(key, 0, now - 60)
        _r.expire(key, 120)
        return _r.zcard(key)
    bucket = _memory_store.setdefault(key, [])
    bucket.append(now)
    _memory_store[key] = [t for t in bucket if t > now - 60]
    return len(_memory_store[key])


def get_ip_reputation(ip: str) -> float:
    # Stub — wire up a real threat-intel feed (e.g. AbuseIPDB) here for production.
    return 0.0
