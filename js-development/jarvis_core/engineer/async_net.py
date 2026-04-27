"""
async_net.py

JARVIS Engineer Layer: Production Async HTTP Client.

Import with:
    from jarvis_core.engineer.async_net import AsyncHttpSession

=============================================================================
THE BIG PICTURE: Non-blocking HTTP for the JARVIS data pipeline
=============================================================================

Without AsyncHttpSession:
    -> requests.get(url) blocks the entire Python process while waiting
    -> Fetching 10 papers takes 10 * avg_latency = ~2,500ms sequentially
    -> The event loop cannot do anything else while one request is pending

With AsyncHttpSession (httpx-backed):
    -> All 10 requests fire concurrently via asyncio.gather()
    -> Total time = max(individual_latency) = ~300ms (parallel)
    -> A Semaphore(n) cap prevents overwhelming the remote API
    -> __aenter__ / __aexit__ guarantee the connection pool closes
       even if an exception fires mid-pipeline

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller enters: async with AsyncHttpSession(max_concurrent=3) as session
        Connection pool opens (httpx.AsyncClient initialized)
        ↓
STEP 2: Caller fires: await session.get(url)
        Semaphore acquired — max 3 concurrent fetches enforced
        ↓
STEP 3: httpx sends the real HTTP GET request (non-blocking)
        ↓
STEP 4: Response parsed and returned as a raw dict
        ↓
STEP 5: Caller exits the async with block
        __aexit__ closes the connection pool regardless of errors

=============================================================================
"""

import asyncio
from typing import Any, Dict, Optional

# httpx is the production-grade async HTTP client.
# Install: pip install httpx
# It is a drop-in replacement for the 'requests' library but async-native.
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


# =============================================================================
# Part 1: THE PRODUCTION HTTP SESSION
# =============================================================================

class AsyncHttpSession:
    """
    LAYER: Engineer (Network I/O) — Async HTTP client with rate limiting.

    Wraps httpx.AsyncClient to provide:
        - Proper async context manager lifecycle (__aenter__ / __aexit__)
        - Semaphore-based concurrency cap to prevent API flooding
        - Retry logic for transient failures (429 rate limit, 502 gateway errors)
        - Request counter for pipeline observability

    It sits BETWEEN:
        - Caller (Brain orchestrator or pipeline runner)
        - External HTTP APIs (arXiv, OpenRouter, internal model endpoints)

    Purpose:
        - Enforce max_concurrent connections at all times
        - Guarantee connection pool cleanup on any error path
        - Make network latency invisible to the caller via async/await

    How it works:
        - asyncio.Semaphore(max_concurrent) acts as a gate:
              If 3 requests are active and a 4th arrives, it waits
              until one of the 3 completes before proceeding.
        - httpx.AsyncClient manages the TCP connection pool.
        - __aexit__ always calls self._client.aclose(), even on exception.
    """

    def __init__(
        self,
        max_concurrent: int = 5,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        """
        Configure the HTTP session parameters.

        Args:
            max_concurrent: Max simultaneous in-flight HTTP requests.
                            Set to 3 for public APIs. Higher for internal endpoints.
            timeout_seconds: Per-request timeout in seconds before giving up.
            max_retries: How many times to retry on transient errors (429, 502, 503).
        """
        self._max_concurrent = max_concurrent
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._client: Optional[Any] = None  # httpx.AsyncClient assigned on __aenter__
        self._request_count: int = 0

    async def __aenter__(self) -> "AsyncHttpSession":
        """
        Open the HTTP connection pool and initialize the concurrency gate.

        EXECUTION FLOW:
        1. Create asyncio.Semaphore with the configured max_concurrent value.
        2. Initialize httpx.AsyncClient with timeout settings.
        3. Return self so the caller can use the session object.

        Returns:
            Self — the open session object.
        """
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        if _HTTPX_AVAILABLE:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
            )
        else:
            # Graceful degradation: warn and operate in simulation mode
            print(
                "[AsyncHttpSession] WARNING: httpx not installed. "
                "Running in simulation mode. pip install httpx to enable real requests."
            )
            self._client = None

        print(
            f"[AsyncHttpSession] Connection pool open "
            f"(max_concurrent={self._max_concurrent}, timeout={self._timeout}s)"
        )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Close the connection pool and flush pending resources.

        This method runs even if an exception fires inside the async with block.
        This is the GUARANTEE — no dangling connections, no leaked file descriptors.

        Returns:
            False — we do not suppress exceptions, we just ensure cleanup.
        """
        if self._client and _HTTPX_AVAILABLE:
            await self._client.aclose()
        print(
            f"[AsyncHttpSession] Connection pool closed "
            f"({self._request_count} requests served)"
        )
        return False  # Never suppress exceptions

    async def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Perform an async HTTP GET request with rate limiting and retry logic.

        EXECUTION FLOW:
        1. Acquire the semaphore — waits if max_concurrent is already reached.
        2. Attempt the HTTP GET (up to max_retries times on transient errors).
        3. Return the parsed response as a dict with status, headers, and body.
        4. Release the semaphore — the next queued request can now proceed.

        Args:
            url:     Full URL to fetch.
            headers: Optional HTTP headers dict (e.g., Authorization tokens).

        Returns:
            Dict with keys: "status" (int), "body" (str), "url" (str).

        Raises:
            RuntimeError: If the session has not been opened (missing async with).
            httpx.HTTPError: On non-retryable HTTP errors.
        """
        if self._semaphore is None:
            raise RuntimeError(
                "AsyncHttpSession is not open. "
                "Use: async with AsyncHttpSession() as session:"
            )

        async with self._semaphore:
            # Semaphore is held for the full duration of the request
            self._request_count += 1

            if not _HTTPX_AVAILABLE or self._client is None:
                # Simulation mode: return a mock success response
                await asyncio.sleep(0.1)  # Simulate network latency
                return {"status": 200, "body": f"SIMULATED response for {url}", "url": url}

            last_error: Optional[Exception] = None

            for attempt in range(1, self._max_retries + 1):
                try:
                    response = await self._client.get(url, headers=headers or {})

                    # Retryable server errors: rate limited or gateway errors
                    if response.status_code in (429, 502, 503) and attempt < self._max_retries:
                        wait_s = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
                        print(
                            f"[AsyncHttpSession] HTTP {response.status_code} on {url}. "
                            f"Retry {attempt}/{self._max_retries} in {wait_s}s..."
                        )
                        await asyncio.sleep(wait_s)
                        continue

                    return {
                        "status": response.status_code,
                        "body": response.text,
                        "url": str(response.url),
                    }

                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < self._max_retries:
                        print(f"[AsyncHttpSession] Timeout on {url}. Retry {attempt}/{self._max_retries}...")
                        await asyncio.sleep(1.0)
                    continue

            raise RuntimeError(
                f"[AsyncHttpSession] All {self._max_retries} retries failed for {url}. "
                f"Last error: {last_error}"
            )


# =============================================================================
# MAIN ENTRY POINT (smoke test)
# =============================================================================

if __name__ == "__main__":
    import time

    async def _smoke_test() -> None:
        print("=" * 55)
        print("  AsyncHttpSession — Smoke Test")
        print("=" * 55)

        urls = [
            "https://httpbin.org/get",  # Public echo API for testing
            "https://httpbin.org/delay/0",
            "https://httpbin.org/status/200",
        ]

        async with AsyncHttpSession(max_concurrent=3, timeout_seconds=10.0) as session:
            t0 = time.perf_counter()
            results = await asyncio.gather(
                *(session.get(url) for url in urls),
                return_exceptions=True,
            )
            elapsed = (time.perf_counter() - t0) * 1000

        for i, result in enumerate(results, 1):
            if isinstance(result, Exception):
                print(f"  [{i}] ERROR: {result}")
            else:
                print(f"  [{i}] HTTP {result['status']} <- {result['url']}")

        print(f"\n  Total time: {elapsed:.0f}ms (concurrent)")
        print("=" * 55)

    asyncio.run(_smoke_test())
