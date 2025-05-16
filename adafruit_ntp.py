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

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_NTP.git"

NTP_TO_UNIX_EPOCH = 2208988800  # 1970-01-01 00:00:00
PACKET_SIZE = const(48)


class NTP:
    """Network Time Protocol (NTP) helper module for CircuitPython.
    This module does not handle daylight savings or local time. It simply requests
    UTC from a NTP server.
    """

    def __init__(
        self,
        socketpool,
        *,
        server: str = "0.adafruit.pool.ntp.org",
        port: int = 123,
        tz_offset: float = 0,
        socket_timeout: int = 10,
        cache_seconds: int = 0,
    ) -> None:
        """
        :param object socketpool: A socket provider such as CPython's `socket` module.
        :param str server: The domain of the ntp server to query.
        :param int port: The port of the ntp server to query.
        :param float tz_offset: Timezone offset in hours from UTC. Only useful for timezone ignorant
            CircuitPython. CPython will determine timezone automatically and adjust (so don't use
            this.) For example, Pacific daylight savings time is -7.
        :param int socket_timeout: UDP socket timeout, in seconds.
        :param int cache_seconds: how many seconds to use a cached result from NTP server
            (default 0, which respects NTP server's minimum).
        """
        self._pool = socketpool
        self._server = server
        self._port = port
        self._socket_address = None
        self._packet = bytearray(PACKET_SIZE)
        self._tz_offset = int(tz_offset * 60 * 60)
        self._socket_timeout = socket_timeout
        self._cache_seconds = cache_seconds

        # This is our estimated start time for the monotonic clock. We adjust it based on the ntp
        # responses.
        self._monotonic_start_ns = 0

        self.next_sync = 0

    def _update_time_sync(self) -> None:
        """Update the time sync value. Raises OSError exception if no response
        is received within socket_timeout seconds, ArithmeticError for substantially incorrect
        NTP results."""
        if self._socket_address is None:
            self._socket_address = self._pool.getaddrinfo(self._server, self._port)[0][4]

        self._packet[0] = 0b00100011  # Not leap second, NTP version 4, Client mode
        for i in range(1, PACKET_SIZE):
            self._packet[i] = 0
        with self._pool.socket(self._pool.AF_INET, self._pool.SOCK_DGRAM) as sock:
            sock.settimeout(self._socket_timeout)
            local_send_ns = time.monotonic_ns()  # expanded
            sock.sendto(self._packet, self._socket_address)
            sock.recv_into(self._packet)
            # Get the time in the context to minimize the difference between it and receiving
            # the packet.
            local_recv_ns = time.monotonic_ns()  # was destination

        poll = struct.unpack_from("!B", self._packet, offset=2)[0]

        cache_offset_s = max(2**poll, self._cache_seconds)
        self.next_sync = local_recv_ns + cache_offset_s * 1_000_000_000

        srv_recv_s, srv_recv_f = struct.unpack_from("!II", self._packet, offset=32)
        srv_send_s, srv_send_f = struct.unpack_from("!II", self._packet, offset=40)

        # Convert the server times from NTP to UTC for local use
        srv_recv_ns = (srv_recv_s - NTP_TO_UNIX_EPOCH) * 1_000_000_000 + (
            srv_recv_f * 1_000_000_000 // 2**32
        )
        srv_send_ns = (srv_send_s - NTP_TO_UNIX_EPOCH) * 1_000_000_000 + (
            srv_send_f * 1_000_000_000 // 2**32
        )

        # _round_trip_delay = (local_recv_ns - local_send_ns) - (srv_send_ns - srv_recv_ns)
        # Calculate (best estimate) offset between server UTC and board monotonic_ns time
        clock_offset = ((srv_recv_ns - local_send_ns) + (srv_send_ns - local_recv_ns)) // 2

        self._monotonic_start_ns = clock_offset + self._tz_offset * 1_000_000_000

    @property
    def datetime(self) -> time.struct_time:
        """Current time from NTP server. Accessing this property causes the NTP time request,
        unless there has already been a recent request."""
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
        incorrect NTP results."""
        if time.monotonic_ns() > self.next_sync:
            self._update_time_sync()

        return time.monotonic_ns() + self._monotonic_start_ns
