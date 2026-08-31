# SPDX-FileCopyrightText: 2022 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_ntp`
================================================================================

Network Time Protocol (NTP) helper for CircuitPython

 * Author(s): Scott Shawcroft

Implementation Notes
--------------------
**Hardware:**
**Software and Dependencies:**

 * Adafruit CircuitPython firmware for the supported boards:
   https://github.com/adafruit/circuitpython/releases

"""

import struct
import time

from micropython import const

try:
    from typing import Sequence, Union
except ImportError:
    pass

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_NTP.git"

NTP_TO_UNIX_EPOCH = 2208988800  # 1970-01-01 00:00:00
PACKET_SIZE = const(48)
# RFC 5905 constrains the poll interval to 2**4 through 2**17 seconds.
NTP_MINPOLL = const(4)
NTP_MAXPOLL = const(17)

_DEFAULT_SERVERS = (
    "0.adafruit.pool.ntp.org",
    "1.adafruit.pool.ntp.org",
    "2.adafruit.pool.ntp.org",
    "3.adafruit.pool.ntp.org",
)


class NTP:
    """Network Time Protocol (NTP) helper module for CircuitPython.
    This module does not handle daylight savings or local time. It simply requests
    UTC from a NTP server.

    :param object socketpool: A socket provider such as CPython's `socket` module.
    :param server: One NTP server hostname, or a sequence of them. Each name is resolved to a
        single IP and the client fails over between them: on a failed query it moves to the next
        server and rotates the failed one to the back of the list. Defaults to Adafruit's four
        pool names.  For most reliable performance it is recommended to have 3+ pool names.
    :type server: str or Sequence[str]
    :param int port: The port of the ntp server to query.
    :param float tz_offset: Timezone offset in hours from UTC. Only useful for timezone ignorant
        CircuitPython. CPython will determine timezone automatically and adjust (so don't use
        this.) For example, Pacific daylight savings time is -7.
    :param float socket_timeout: UDP socket timeout, in seconds (default 1.0).
    :param int cache_seconds: how many seconds to use a cached result from NTP server
        (default 0, which respects NTP server's minimum).
    :param int reresolve_interval: how often, in seconds, to rebuild the server IP list from DNS,
        for long-running programs whose resolved members may go stale. The NTP Pool asks vendors
        not to re-resolve more than once per hour, so keep this >= 3600 (default 3600).

    """

    def __init__(
        self,
        socketpool,
        *,
        server: Union[str, Sequence[str]] = _DEFAULT_SERVERS,
        port: int = 123,
        tz_offset: float = 0,
        socket_timeout: float = 1.0,
        cache_seconds: int = 0,
        reresolve_interval: int = 3600,
    ) -> None:
        self._pool = socketpool
        self._servers = (server,) if isinstance(server, str) else tuple(server)
        self._port = port
        self._packet = bytearray(PACKET_SIZE)
        self._tz_offset = int(tz_offset * 60 * 60)
        self._socket_timeout = socket_timeout
        self._cache_seconds = cache_seconds
        self._reresolve_interval = reresolve_interval

        self._addresses = None
        self._last_resolve_ns = 0

        # This is our estimated start time for the monotonic clock. We adjust it based on the ntp
        # responses.
        self._monotonic_start_ns = 0

        self.next_sync = 0

    def _resolve_servers(self) -> None:
        """Rebuild the cached IP list from DNS on first use and every reresolve_interval."""
        now = time.monotonic_ns()
        fresh = self._addresses is not None
        if fresh and (now - self._last_resolve_ns) < self._reresolve_interval * 1_000_000_000:
            return

        addresses = []
        for name in self._servers:
            try:
                address = self._pool.getaddrinfo(name, self._port)[0][4]
            except OSError:
                continue
            if address not in addresses:
                addresses.append(address)

        if addresses:
            self._addresses = addresses
            self._last_resolve_ns = now
        elif self._addresses is not None:
            self._last_resolve_ns = now  # keep the stale list; rate-limit re-resolve during outages
        else:
            raise OSError("NTP: could not resolve any server")

    def _query_server(self, address) -> None:
        """Send one request to a single server and update the clock, or raise on failure."""
        self._packet[0] = 0b00100011  # Not leap second, NTP version 4, Client mode
        for i in range(1, PACKET_SIZE):
            self._packet[i] = 0
        with self._pool.socket(self._pool.AF_INET, self._pool.SOCK_DGRAM) as sock:
            sock.settimeout(self._socket_timeout)
            local_send_ns = time.monotonic_ns()
            sock.sendto(self._packet, address)
            received = sock.recv_into(self._packet)
            local_recv_ns = time.monotonic_ns()

        # A short read leaves timestamp fields reading as our own pre-send zeros.
        if received is None or received < PACKET_SIZE:
            raise ArithmeticError(f"NTP response was {received} bytes, expected {PACKET_SIZE}")

        # Clamp poll to the RFC 5905 range so a corrupt byte can't derail the next sync.
        poll = min(
            max(struct.unpack_from("!B", self._packet, offset=2)[0], NTP_MINPOLL), NTP_MAXPOLL
        )

        srv_recv_s, srv_recv_f = struct.unpack_from("!II", self._packet, offset=32)
        srv_send_s, srv_send_f = struct.unpack_from("!II", self._packet, offset=40)

        # A pre-epoch timestamp is a zeroed or truncated field, not a real time.
        if srv_recv_s < NTP_TO_UNIX_EPOCH or srv_send_s < NTP_TO_UNIX_EPOCH:
            raise ArithmeticError("NTP response has an invalid timestamp")

        # Convert the server times from NTP to UTC for local use
        srv_recv_ns = (srv_recv_s - NTP_TO_UNIX_EPOCH) * 1_000_000_000 + (
            srv_recv_f * 1_000_000_000 // 2**32
        )
        srv_send_ns = (srv_send_s - NTP_TO_UNIX_EPOCH) * 1_000_000_000 + (
            srv_send_f * 1_000_000_000 // 2**32
        )

        # Best estimate of the offset between server UTC and board monotonic_ns time.
        clock_offset = ((srv_recv_ns - local_send_ns) + (srv_send_ns - local_recv_ns)) // 2
        cache_offset_s = max(2**poll, self._cache_seconds)

        # Assign session state only after the response has fully validated.
        self.next_sync = local_recv_ns + cache_offset_s * 1_000_000_000
        self._monotonic_start_ns = clock_offset + self._tz_offset * 1_000_000_000

    def _update_time_sync(self) -> None:
        """Query servers with failover. Raises OSError if none respond within socket_timeout
        seconds, ArithmeticError for substantially incorrect NTP results."""
        self._resolve_servers()

        # Try each server once, rotating a failure to the back; retry once if there is only one.
        attempts = 2 if len(self._addresses) == 1 else 1
        timeout_exc = None
        response_exc = None
        for _server in range(len(self._addresses)):
            address = self._addresses[0]
            for _attempt in range(attempts):
                try:
                    self._query_server(address)
                    return
                except OSError as exc:
                    timeout_exc = exc
                except ArithmeticError as exc:
                    response_exc = exc
                    break
            self._addresses.append(self._addresses.pop(0))

        # Prefer the timeout (ETIMEDOUT) so an all-servers-down result stays backward compatible.
        raise timeout_exc or response_exc or OSError("NTP: no server responded")

    @property
    def datetime(self) -> time.struct_time:
        """Current time from NTP server. Accessing this property causes the NTP time request,
        unless there has already been a recent request.

        :return: The current UTC time.
        :rtype: time.struct_time
        """
        if time.monotonic_ns() > self.next_sync:
            self._update_time_sync()

        # Calculate the current time based on the current and start monotonic times
        current_time_s = (time.monotonic_ns() + self._monotonic_start_ns) // 1_000_000_000

        return time.localtime(current_time_s)

    @property
    def utc_ns(self) -> int:
        """UTC (unix epoch) time in nanoseconds. Accessing this property causes the NTP time
        request, unless there has already been a recent request. Raises OSError exception if
        no response is received within socket_timeout seconds, ArithmeticError for substantially
        incorrect NTP results.

        :return: UTC time in nanoseconds since the unix epoch.
        :rtype: int
        """
        if time.monotonic_ns() > self.next_sync:
            self._update_time_sync()

        return time.monotonic_ns() + self._monotonic_start_ns
