import asyncio
import unittest
from unittest import mock
from unittest.mock import AsyncMock

from proxy import cf_connect
from proxy import bridge
from proxy.balancer import balancer
from proxy.bridge import _cfproxy_fallback, reset_cf_backoff
from proxy.cf_connect import CfAttemptBudget, CfFailureBackoff
from proxy.config import (
    forget_plain_transport, prefers_plain_transport, proxy_config,
    remember_plain_transport, reset_plain_transport_hints,
)
from proxy.raw_websocket import WsHandshakeError


class _PlainFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_plain_transport_hints()
        cf_connect.reset_cf_connect_state()
        self.addCleanup(reset_plain_transport_hints)
        self.addCleanup(cf_connect.reset_cf_connect_state)

    async def _connect(self, *args, **kwargs):
        raise asyncio.TimeoutError()

    async def test_tls_timeout_retries_plain_http_and_remembers_host(self):
        calls = []
        sentinel = object()

        async def connect(host, domain, timeout=10.0, path='/apiws', *,
                          secure=True):
            calls.append((host, path, secure))
            if secure:
                raise asyncio.TimeoutError()
            return sentinel

        with mock.patch.object(cf_connect.RawWebSocket, 'connect',
                               side_effect=connect):
            result = await cf_connect.connect_cf_ws('kws2.example.org')
            self.assertIs(result, sentinel)
            self.assertEqual(calls, [('kws2.example.org', '/apiws', True),
                                     ('kws2.example.org', '/apiws', False)])
            self.assertTrue(prefers_plain_transport('kws2.example.org'))

            calls.clear()
            result = await cf_connect.connect_cf_ws('kws2.example.org')
            self.assertIs(result, sentinel)
            self.assertEqual(calls, [('kws2.example.org', '/apiws', False)])

    async def test_http_error_is_not_downgraded(self):
        async def connect(*args, **kwargs):
            raise WsHandshakeError(301, 'Moved Permanently')

        with mock.patch.object(cf_connect.RawWebSocket, 'connect',
                               side_effect=connect) as connect_mock:
            with self.assertRaises(WsHandshakeError):
                await cf_connect.connect_cf_ws('kws2.example.org')
        self.assertEqual(connect_mock.call_count, 1)
        self.assertFalse(prefers_plain_transport('kws2.example.org'))

    async def test_plain_fallback_can_be_disabled(self):
        with mock.patch.object(proxy_config, 'cf_plain_fallback', False), \
                mock.patch.object(cf_connect.RawWebSocket, 'connect',
                                  side_effect=self._connect) as connect_mock:
            with self.assertRaises(asyncio.TimeoutError):
                await cf_connect.connect_cf_ws('kws2.example.org')
        self.assertEqual(connect_mock.call_count, 1)
        self.assertTrue(connect_mock.call_args.kwargs['secure'])
        self.assertFalse(prefers_plain_transport('kws2.example.org'))

    async def test_no_secure_uses_port_80_directly(self):
        calls = []
        sentinel = object()

        async def connect(host, domain, timeout=10.0, path='/apiws', *,
                          secure=True):
            calls.append(secure)
            return sentinel

        with mock.patch.object(proxy_config, 'disable_secure', True), \
                mock.patch.object(cf_connect.RawWebSocket, 'connect',
                                  side_effect=connect):
            self.assertIs(await cf_connect.connect_cf_ws('kws4.example.org'),
                          sentinel)
        self.assertEqual(calls, [False])

    async def test_plain_route_failure_falls_back_to_tls_next_time(self):
        remember_plain_transport('kws4.example.org')
        states = []

        async def connect(host, domain, timeout=10.0, path='/apiws', *,
                          secure=True):
            states.append(secure)
            if not secure:
                raise ConnectionResetError()
            return 'tls'

        with mock.patch.object(cf_connect.RawWebSocket, 'connect',
                               side_effect=connect):
            with self.assertRaises(ConnectionResetError):
                await cf_connect.connect_cf_ws('kws4.example.org')
            self.assertFalse(prefers_plain_transport('kws4.example.org'))
            self.assertEqual(
                await cf_connect.connect_cf_ws('kws4.example.org'), 'tls')
        self.assertEqual(states, [False, True])

    async def test_plain_hint_is_shared_between_dcs(self):
        remember_plain_transport('kws3.example.co.uk')
        self.assertTrue(prefers_plain_transport('kws3.example.co.uk'))
        self.assertTrue(prefers_plain_transport('kws2.example.co.uk'))
        self.assertFalse(prefers_plain_transport('kws2.other.co.uk'))

        # A rejected host retries TLS, but the base hint stays for other DCs.
        forget_plain_transport('kws2.example.co.uk')
        self.assertFalse(prefers_plain_transport('kws2.example.co.uk'))
        self.assertTrue(prefers_plain_transport('kws3.example.co.uk'))

    async def test_parallel_connects_are_bounded(self):
        active = 0
        peak = 0
        release = asyncio.Event()

        async def connect(*args, secure=True, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1
            return object()

        with mock.patch.object(proxy_config, 'disable_secure', True), \
                mock.patch.object(cf_connect, 'CF_MAX_PARALLEL_CONNECTS', 2), \
                mock.patch.object(cf_connect, '_slots', None), \
                mock.patch.object(cf_connect.RawWebSocket, 'connect',
                                  side_effect=connect):
            tasks = [asyncio.create_task(
                cf_connect.connect_cf_ws('kws%d.example.org' % i))
                for i in range(6)]
            await asyncio.sleep(0.05)
            release.set()
            await asyncio.gather(*tasks)
        self.assertLessEqual(peak, 2)


class _AttemptBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_budget_limits_domain_attempts(self):
        budget = CfAttemptBudget(30.0, 2)
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertFalse(budget.take())
        self.assertEqual(budget.attempts, 2)

    async def test_expired_budget_refuses_attempts(self):
        budget = CfAttemptBudget(0.0, 10)
        await asyncio.sleep(0)
        self.assertFalse(budget.take())
        self.assertTrue(budget.exhausted_by_time)


class _FailureBackoffTest(unittest.IsolatedAsyncioTestCase):
    async def test_failures_back_off_and_recover(self):
        backoff = CfFailureBackoff()
        self.assertTrue(backoff.begin(2))
        self.assertFalse(backoff.begin(2))  # sweep already in progress
        delay = backoff.end(2, success=False)
        self.assertGreater(delay, 0)
        self.assertFalse(backoff.available(2))
        self.assertFalse(backoff.begin(2))
        backoff._retry_after[2] = 0.0
        self.assertTrue(backoff.begin(2))
        self.assertEqual(backoff.end(2, success=True), 0.0)
        self.assertTrue(backoff.available(2))

    async def test_backoff_grows_on_repeated_failures(self):
        backoff = CfFailureBackoff()
        delays = []
        for _ in range(4):
            backoff.begin(4)
            delays.append(backoff.end(4, success=False))
            backoff._retry_after[4] = 0.0
        self.assertEqual(delays, sorted(delays))
        self.assertLess(delays[0], delays[-1])


class _CfProxyFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_cf_backoff()
        old = list(balancer.domains)
        self.addCleanup(balancer.update_domains_list, old)
        self.addCleanup(reset_cf_backoff)
        balancer.update_domains_list(['a.test', 'b.test', 'c.test'])

    async def test_skips_sweep_while_backoff_is_active(self):
        bridge._cf_backoff._retry_after[2] = float('inf')
        with mock.patch.object(bridge, 'connect_cf_ws',
                               new=AsyncMock()) as connect:
            ok = await _cfproxy_fallback(
                None, None, b'init', 'label', mock.Mock(), 2, False)
        self.assertFalse(ok)
        connect.assert_not_called()

    async def test_sweep_is_limited_to_few_domains(self):
        with mock.patch.object(bridge, 'CF_SWEEP_MAX_DOMAINS', 2), \
                mock.patch.object(bridge, 'connect_cf_ws',
                                  new=AsyncMock(
                                      side_effect=asyncio.TimeoutError())):
            ok = await _cfproxy_fallback(
                None, None, b'init', 'label', mock.Mock(), 2, False)
        self.assertFalse(ok)
        self.assertFalse(bridge._cf_backoff.available(2))

    async def test_known_plain_domain_is_tried_first(self):
        ws = mock.Mock()
        ws.send = AsyncMock()
        remember_plain_transport('kws1.beta.test')
        with mock.patch.object(bridge, 'connect_cf_ws',
                               new=AsyncMock(return_value=ws)) as connect, \
                mock.patch.object(bridge, 'bridge_ws_reencrypt',
                                  new=AsyncMock()):
            ok = await _cfproxy_fallback(
                None, None, b'init', 'label', mock.Mock(), 4, False)
        self.assertTrue(ok)
        self.assertEqual(connect.await_args_list[0].args[0], 'kws4.beta.test')

    async def test_successful_connection_resets_backoff(self):
        ws = mock.Mock()
        ws.send = AsyncMock()
        bridge._cf_backoff._retry_after[2] = 0.0
        bridge._cf_backoff._failures[2] = 3
        with mock.patch.object(bridge, 'connect_cf_ws',
                               new=AsyncMock(return_value=ws)), \
                mock.patch.object(bridge, 'bridge_ws_reencrypt',
                                  new=AsyncMock()):
            ok = await _cfproxy_fallback(
                None, None, b'init', 'label', mock.Mock(), 2, False)
        self.assertTrue(ok)
        ws.send.assert_awaited_once_with(b'init')
        self.assertTrue(bridge._cf_backoff.available(2))
        self.assertNotIn(2, bridge._cf_backoff._failures)


if __name__ == '__main__':
    unittest.main()
