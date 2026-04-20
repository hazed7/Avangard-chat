from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check(self, bucket_key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        bucket = self._buckets[bucket_key]

        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()

        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Too many authentication attempts. Try again later.",
            )

        bucket.append(now)


auth_rate_limiter = InMemoryRateLimiter()
