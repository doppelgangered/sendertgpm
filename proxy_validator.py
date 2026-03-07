"""
SOCKS5 proxy validator.

Checks each proxy by opening a TCP connection through it to Telegram DC1.
All I/O is blocking (PySocks), so tests run in a thread-pool executor.
"""
import asyncio
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import socks

# Telegram DC1 — reliable, always reachable target
_TARGET_HOST = "149.154.167.51"
_TARGET_PORT = 443
_TIMEOUT = 10  # seconds per proxy

# Shared executor — reused across calls
_executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="proxy_check")


def _test_sync(proxy: dict) -> tuple[bool, float, str]:
    """Blocking test. Returns (ok, latency_ms, error_msg)."""
    s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
    s.set_proxy(
        socks.SOCKS5,
        proxy["host"],
        proxy["port"],
        username=proxy.get("username"),
        password=proxy.get("password"),
    )
    s.settimeout(_TIMEOUT)
    t0 = time.monotonic()
    try:
        s.connect((_TARGET_HOST, _TARGET_PORT))
        latency = (time.monotonic() - t0) * 1000
        return True, round(latency, 1), ""
    except socks.ProxyError as e:
        return False, 0.0, f"ProxyError: {e}"
    except OSError as e:
        return False, 0.0, str(e)
    finally:
        try:
            s.close()
        except Exception:
            pass


async def test_proxy(proxy: dict) -> tuple[bool, float, str]:
    """Async wrapper around the blocking test."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _test_sync, proxy)


async def validate_proxies(
    proxies: list[dict],
    concurrency: int = 30,
    on_result=None,
) -> list[tuple[dict, bool, float, str]]:
    """
    Validate a list of proxies concurrently.

    Returns list of (proxy, ok, latency_ms, error) in completion order.
    on_result(proxy, ok, latency, error, done, total) — called after each proxy.
    """
    semaphore = asyncio.Semaphore(concurrency)
    total = len(proxies)
    done_count = 0
    results: list[tuple[dict, bool, float, str]] = []

    async def _check(proxy: dict) -> tuple[dict, bool, float, str]:
        nonlocal done_count
        async with semaphore:
            ok, latency, err = await test_proxy(proxy)
            done_count += 1
            result = (proxy, ok, latency, err)
            results.append(result)
            if on_result:
                on_result(proxy, ok, latency, err, done_count, total)
            return result

    await asyncio.gather(*[_check(p) for p in proxies])
    return results
