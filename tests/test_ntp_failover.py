# SPDX-FileCopyrightText: 2026 Bob Grant for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""Unit tests for the multi-server failover behavior of adafruit_ntp.

These run under CPython with a mock socket pool — no hardware and no network. The on-device survey
and timing checks live in the separate hardware harness, which cannot run in CI.
"""

import struct

import pytest

from adafruit_ntp import NTP

# An NTP transmit/receive timestamp comfortably after the unix epoch (~2023) so parsing succeeds.
VALID_NTP_SECONDS = 3900000000
ETIMEDOUT = 110


def _fill_valid(packet):
    packet[2] = 6  # poll
    struct.pack_into("!II", packet, 32, VALID_NTP_SECONDS, 0)  # server receive
    struct.pack_into("!II", packet, 40, VALID_NTP_SECONDS, 0)  # server transmit
    return len(packet)


class _MockSocket:
    def __init__(self, pool):
        self._pool = pool

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def settimeout(self, _value):
        pass

    def sendto(self, _data, address):
        self._pool.current = address

    def recv_into(self, packet):
        ip = self._pool.current[0]
        self._pool.queried.append(ip)
        if self._pool.fail_first > 0:
            self._pool.fail_first -= 1
            raise OSError(ETIMEDOUT, "ETIMEDOUT")
        if ip in self._pool.dead:
            raise OSError(ETIMEDOUT, "ETIMEDOUT")
        if self._pool.short:
            return 10  # short read -> triggers the library's ArithmeticError guard
        return _fill_valid(packet)


class MockPool:
    """Stands in for socketpool.SocketPool. `dead` IPs time out; `rotating` names resolve to a fresh
    IP each lookup (anycast-like); `short` returns a truncated packet; `fail_first` times out the
    next N queries regardless of target."""

    AF_INET = 2
    SOCK_DGRAM = 2

    def __init__(self, dead=(), rotating=(), short=False, fail_first=0):
        self.dead = set(dead)
        self.rotating = set(rotating)
        self.short = short
        self.fail_first = fail_first
        self.queried = []
        self.current = None
        self._rot = 0
        self.resolves = []

    def getaddrinfo(self, host, port):
        self.resolves.append(host)
        if host in self.rotating:
            self._rot += 1
            return [(2, 2, 0, "", (f"{host}#{self._rot}", port))]
        return [(2, 2, 0, "", (host, port))]

    def socket(self, _af, _proto):
        return _MockSocket(self)


def _sync(ntp):
    """Force a fresh sync and return the result of the query."""
    ntp.next_sync = 0
    return ntp.utc_ns


# --- constructor / server normalization ---


def test_str_server_normalizes_to_one_tuple():
    assert NTP(MockPool(), server="one.example")._servers == ("one.example",)


def test_sequence_server_accepted():
    assert NTP(MockPool(), server=["a.example", "b.example"])._servers == ("a.example", "b.example")


def test_default_is_four_adafruit_pool_names():
    servers = NTP(MockPool())._servers
    assert len(servers) == 4
    assert all(name.endswith("adafruit.pool.ntp.org") for name in servers)


def test_default_socket_timeout_is_one_second():
    assert NTP(MockPool())._socket_timeout == 1


# --- resolution ---


def test_resolution_is_lazy_no_io_in_init():
    pool = MockPool()
    NTP(pool, server="live.example")
    assert pool.resolves == []  # __init__ did no DNS


def test_duplicate_ips_are_deduped():
    pool = MockPool()
    pool.getaddrinfo = lambda host, port: [(2, 2, 0, "", ("10.0.0.9", port))]
    ntp = NTP(pool, server=("0.example", "1.example"))
    _sync(ntp)
    assert ntp._addresses == [("10.0.0.9", 123)]


# --- failover behavior ---


def test_dead_first_server_fails_over_and_returns_time():
    pool = MockPool(dead={"192.0.2.1"})
    ntp = NTP(pool, server=("192.0.2.1", "live.example", "live2.example"))
    _sync(ntp)  # must not raise
    assert ntp._addresses[0][0] == "live.example"  # working server sticks to the front
    assert ntp._addresses[-1][0] == "192.0.2.1"  # failed server rotated to the back


def test_second_sync_sticks_to_working_server():
    pool = MockPool(dead={"192.0.2.1"})
    ntp = NTP(pool, server=("192.0.2.1", "live.example"))
    _sync(ntp)
    pool.queried.clear()
    _sync(ntp)
    assert pool.queried == ["live.example"]  # no wasted query on the dead server


def test_each_server_tried_once_before_giving_up():
    pool = MockPool(dead={"a.example", "b.example", "c.example"})
    ntp = NTP(pool, server=("a.example", "b.example", "c.example"))
    with pytest.raises(OSError):
        _sync(ntp)
    assert sorted(pool.queried) == ["a.example", "b.example", "c.example"]


def test_all_servers_down_raises_oserror_with_etimedout():
    pool = MockPool(dead={"192.0.2.1", "192.0.2.2"})
    ntp = NTP(pool, server=("192.0.2.1", "192.0.2.2"))
    with pytest.raises(OSError) as info:
        _sync(ntp)
    assert info.value.errno == ETIMEDOUT  # backward-compatible failure surface


# --- single-server (degenerate) case ---


def test_single_server_retries_once_then_succeeds():
    pool = MockPool(fail_first=1)  # first attempt times out, retry succeeds
    ntp = NTP(pool, server="only.example")
    _sync(ntp)
    assert pool.queried == ["only.example", "only.example"]


def test_single_server_both_attempts_fail_raises():
    pool = MockPool(dead={"only.example"})
    ntp = NTP(pool, server="only.example")
    with pytest.raises(OSError):
        _sync(ntp)
    assert pool.queried == ["only.example", "only.example"]  # exactly two attempts


# --- re-resolution ---


def test_no_reresolve_within_interval():
    pool = MockPool()
    ntp = NTP(pool, server="live.example", reresolve_interval=3600)
    _sync(ntp)
    before = len(pool.resolves)
    _sync(ntp)
    assert len(pool.resolves) == before  # cached, no second DNS lookup


def test_reresolve_when_interval_elapsed():
    pool = MockPool()
    ntp = NTP(pool, server="live.example", reresolve_interval=0)  # always stale
    _sync(ntp)
    before = len(pool.resolves)
    _sync(ntp)
    assert len(pool.resolves) > before  # list rebuilt from DNS


# --- response validation ---


def test_short_response_raises_arithmeticerror():
    ntp = NTP(MockPool(short=True), server="live.example")
    with pytest.raises(ArithmeticError):
        _sync(ntp)


def test_datetime_returns_plausible_year():
    ntp = NTP(MockPool(), server="live.example")
    ntp.next_sync = 0
    when = ntp.datetime
    assert 2020 <= when.tm_year <= 2100
