"""
In-memory cache for full SQL result sets, keyed by a UUID cache_key.

Populated during initial chart generation so that the /api/rechart endpoint
can access the full dataset (not just the 200-row preview sent to the UI).
Entries auto-expire after TTL_SECONDS to prevent unbounded memory growth.
"""

import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

TTL_SECONDS = 1800  # 30 minutes

_lock = threading.Lock()
_store: Dict[str, Tuple[float, List[str], List[Dict[str, Any]]]] = {}


def put(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    """Store a result set and return a unique cache key."""
    key = uuid.uuid4().hex
    with _lock:
        _store[key] = (time.monotonic(), columns, rows)
    return key


def get(key: str) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    """Retrieve a cached result set. Returns None if missing or expired."""
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        ts, columns, rows = entry
        if time.monotonic() - ts > TTL_SECONDS:
            del _store[key]
            return None
        return columns, rows


def evict_expired() -> int:
    """Remove all expired entries. Returns count of evicted keys."""
    now = time.monotonic()
    with _lock:
        expired = [k for k, (ts, _, _) in _store.items() if now - ts > TTL_SECONDS]
        for k in expired:
            del _store[k]
    return len(expired)
