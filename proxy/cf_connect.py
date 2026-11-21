"""Cloudflare WebSocket helper with a plain-HTTP fallback.

Since 16.11.2026 the default Cloudflare-proxied domains are blocked in Russia
by SNI, so a TLS handshake simply times out. The same route usually keeps
working over port 80 (Cloudflare "Flexible" mode), which is what the
"Disable TLS for CF-proxy and CF-worker" setting does manually.

This helper applies that fallback automatically: after a TLS timeout it
retries the same host over plain HTTP, remembers the host for the rest of the
process and uses port 80 immediately from then on. HTTP-level errors are never
downgraded - only timeouts and connection failures are.
"""

from __future__ import annotations

import asyncio
import logging

from typing import Dict, Optional, Set

from .config import (
    forget_plain_transport, prefers_plain_transport, proxy_config,
    remember_plain_transport,
)
from .raw_websocket import RawWebSocket, WsHandshakeError

log = logging.getLogger('tg-mtproto-proxy')

CF_CONNECT_TIMEOUT = 10.0
CF_PLAIN_CONNECT_TIMEOUT = 6.0
CF_MAX_PARALLEL_CONNECTS = 8

_slots: Optional[asyncio.Semaphore] = None


def reset_cf_connect_state() -> None:
    """Drop the semaphore so it is bound to the new event loop."""
    global _slots
    _slots = None


def _semaphore() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(CF_MAX_PARALLEL_CONNECTS)
    return _slots


def _is_blocking_error(exc: BaseException) -> bool:
    if isinstance(exc, WsHandshakeError):
        # Cloudflare answered; the route is reachable, just refused us.
        return False
    return isinstance(exc, (asyncio.TimeoutError, TimeoutError, OSError))


async def connect_cf_ws(host: str, path: str = '/apiws', *,
                        timeout: float = CF_CONNECT_TIMEOUT) -> RawWebSocket:
    """Open a WS connection to a Cloudflare-proxied host.

    Tries TLS first and falls back to plain HTTP when TLS times out and
    ``proxy_config.cf_plain_fallback`` is enabled.
    """
    plain_only = proxy_config.disable_secure or (
        proxy_config.cf_plain_fallback
        and prefers_plain_transport(host))

    async with _semaphore():
        if plain_only:
            try:
                return await RawWebSocket.connect(
                    host, host, timeout=min(timeout, CF_PLAIN_CONNECT_TIMEOUT),
                    path=path, secure=False)
            except WsHandshakeError:
                raise
            except BaseException as exc:
                if _is_blocking_error(exc) and not proxy_config.disable_secure:
                    # Plain HTTP stopped working: let a later sweep try TLS.
                    forget_plain_transport(host)
                raise

        try:
            return await RawWebSocket.connect(
                host, host, timeout=timeout, path=path, secure=True)
        except WsHandshakeError:
            raise
        except BaseException as exc:
            if not _is_blocking_error(exc) or not proxy_config.cf_plain_fallback:
                raise
            ws = await RawWebSocket.connect(
                host, host,
                timeout=min(timeout, CF_PLAIN_CONNECT_TIMEOUT),
                path=path, secure=False)
            if remember_plain_transport(host):
                log.warning(
                    "TLS to %s looks blocked (%s); switched CF route to "
                    "plain HTTP (port 80)", host, type(exc).__name__)
            return ws


class CfAttemptBudget:
    """Bound how long one fallback sweep may spend on a single DC.

    Without this, a blocked network makes every client connection walk the
    whole domain list (20 domains x 10 s), which piles up sockets and hides
    the proxy from Telegram for minutes.
    """

    __slots__ = ('deadline', 'max_domains', 'attempts')

    def __init__(self, seconds: float, max_domains: int):
        loop = asyncio.get_running_loop()
        self.deadline = loop.time() + seconds
        self.max_domains = max_domains
        self.attempts = 0

    def take(self) -> bool:
        if self.attempts >= self.max_domains:
            return False
        if asyncio.get_running_loop().time() >= self.deadline:
            return False
        self.attempts += 1
        return True

    @property
    def exhausted_by_time(self) -> bool:
        return asyncio.get_running_loop().time() >= self.deadline


class CfFailureBackoff:
    """Per-DC exponential backoff shared by all client connections."""

    INITIAL = 5.0
    MAX = 120.0

    def __init__(self):
        self._failures: Dict[int, int] = {}
        self._retry_after: Dict[int, float] = {}
        self._inflight: Set[int] = set()
        self._finished: Dict[int, asyncio.Event] = {}

    def reset(self) -> None:
        self._failures.clear()
        self._retry_after.clear()
        self._inflight.clear()
        for event in self._finished.values():
            event.set()
        self._finished.clear()

    def available(self, dc: int) -> bool:
        if dc in self._inflight:
            return False
        return asyncio.get_running_loop().time() >= self._retry_after.get(dc, 0.0)

    def begin(self, dc: int) -> bool:
        """Mark a sweep as running; False if one is already running."""
        if dc in self._inflight or not self.available(dc):
            return False
        self._inflight.add(dc)
        self._finished[dc] = asyncio.Event()
        return True

    async def wait(self, dc: int, timeout: float) -> bool:
        """Wait for an in-flight sweep to finish; False on timeout."""
        event = self._finished.get(dc)
        if event is None:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    def end(self, dc: int, success: bool) -> float:
        """Finish a sweep and return the next retry delay (0 on success)."""
        self._inflight.discard(dc)
        finished = self._finished.pop(dc, None)
        if finished is not None:
            finished.set()
        if success:
            recovered = self._failures.pop(dc, 0) > 0
            self._retry_after.pop(dc, None)
            if recovered:
                log.info("CF proxy recovered for DC%d", dc)
            return 0.0
        failures = self._failures.get(dc, 0) + 1
        self._failures[dc] = failures
        delay = min(self.INITIAL * (2 ** min(failures - 1, 8)), self.MAX)
        self._retry_after[dc] = asyncio.get_running_loop().time() + delay
        log.info("CF proxy unavailable for DC%d, next attempt in %.0fs",
                 dc, delay)
        return delay
