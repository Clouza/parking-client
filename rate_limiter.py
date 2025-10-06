#!/usr/bin/env python3
"""
rate limiting module
prevents abuse and manages request rates
"""

import time
from collections import defaultdict, deque
from typing import Dict, Deque
from threading import Lock

class RateLimiter:
    """token bucket rate limiter"""

    def __init__(self, requests_per_second: int = 10, burst_size: int = 20):
        """
        initialize rate limiter

        args:
            requests_per_second: allowed requests per second
            burst_size: maximum burst requests
        """
        self.rate = requests_per_second
        self.burst_size = burst_size
        self.buckets: Dict[str, Dict] = defaultdict(lambda: {
            'tokens': burst_size,
            'last_update': time.time()
        })
        self.lock = Lock()

    def allow_request(self, client_id: str) -> bool:
        """
        check if request is allowed for client

        args:
            client_id: unique client identifier

        returns:
            True if request allowed, False otherwise
        """
        with self.lock:
            now = time.time()
            bucket = self.buckets[client_id]

            # refill tokens based on time elapsed
            elapsed = now - bucket['last_update']
            tokens_to_add = elapsed * self.rate
            bucket['tokens'] = min(self.burst_size, bucket['tokens'] + tokens_to_add)
            bucket['last_update'] = now

            # check if request can be allowed
            if bucket['tokens'] >= 1:
                bucket['tokens'] -= 1
                return True

            return False

    def reset(self, client_id: str):
        """
        reset rate limit for client

        args:
            client_id: client to reset
        """
        with self.lock:
            if client_id in self.buckets:
                del self.buckets[client_id]


class SlidingWindowRateLimiter:
    """sliding window rate limiter"""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        """
        initialize sliding window rate limiter

        args:
            max_requests: maximum requests in window
            window_seconds: time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, Deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allow_request(self, client_id: str) -> bool:
        """
        check if request is allowed

        args:
            client_id: unique client identifier

        returns:
            True if request allowed, False otherwise
        """
        with self.lock:
            now = time.time()
            window_start = now - self.window_seconds

            # remove old requests outside window
            request_times = self.requests[client_id]
            while request_times and request_times[0] < window_start:
                request_times.popleft()

            # check if under limit
            if len(request_times) < self.max_requests:
                request_times.append(now)
                return True

            return False

    def get_remaining(self, client_id: str) -> int:
        """
        get remaining requests for client

        args:
            client_id: client identifier

        returns:
            number of remaining requests
        """
        with self.lock:
            now = time.time()
            window_start = now - self.window_seconds

            # count requests in window
            request_times = self.requests[client_id]
            valid_requests = sum(1 for t in request_times if t >= window_start)

            return max(0, self.max_requests - valid_requests)

    def reset(self, client_id: str):
        """
        reset rate limit for client

        args:
            client_id: client to reset
        """
        with self.lock:
            if client_id in self.requests:
                del self.requests[client_id]