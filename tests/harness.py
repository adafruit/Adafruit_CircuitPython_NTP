# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""Test harness reproducing adafruit/Adafruit_CircuitPython_NTP issue #35.

Issue #35: `OverflowError: overflow converting long int to machine word` raised
from `NTP.datetime`. Root cause reported by the filer: the NTP response packet
came back with a transmit-timestamp seconds field of 0, so the computed unix
timestamp became roughly -2208988800 (i.e. NTP epoch minus unix epoch). On a
32-bit CircuitPython board `time.localtime()` takes a *machine word*, and
-2208988800 does not fit in int32, hence the OverflowError.

To reproduce deterministically under CPython we substitute the module's `time`
with a fake that (a) has a controllable monotonic clock and (b) enforces the
int32 machine-word limit on `localtime()` exactly like a 32-bit MCU does.
"""

import contextlib
import struct
import time as _real_time

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1

NTP_TO_UNIX_EPOCH = 2208988800
PACKET_SIZE = 48


class FakeTime:
    """Stand-in for CircuitPython's `time` on a 32-bit board.

    `localtime()` on such a board converts its argument to a machine word, so
    anything outside int32 raises OverflowError with this exact message.
    """

    def __init__(self, monotonic_s=90_000):
        self.monotonic_s = monotonic_s
        self.localtime_calls = []

    def monotonic_ns(self):
        return int(self.monotonic_s * 1_000_000_000)

    def localtime(self, secs):
        self.localtime_calls.append(secs)
        if not INT32_MIN <= secs <= INT32_MAX:
            raise OverflowError("overflow converting long int to machine word")
        return _real_time.gmtime(secs)

    # struct_time type is referenced only in annotations
    struct_time = _real_time.struct_time


def make_packet(*, transmit_s, recv_s=None, poll=6, frac=0):
    """Build a 48-byte NTP server response."""
    if recv_s is None:
        recv_s = transmit_s
    pkt = bytearray(PACKET_SIZE)
    pkt[0] = 0b00100100  # LI=0, VN=4, mode=4 (server)
    pkt[1] = 2  # stratum
    pkt[2] = poll
    struct.pack_into("!II", pkt, 32, recv_s, frac)  # receive timestamp
    struct.pack_into("!II", pkt, 40, transmit_s, frac)  # transmit timestamp
    return pkt


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = []

    def settimeout(self, t):
        pass

    def sendto(self, packet, addr):
        self.sent.append((bytes(packet), addr))

    def recv_into(self, buf):
        if self.response is None:
            # Simulates a recv that writes nothing: the caller's buffer keeps
            # whatever it held (adafruit_ntp zeroes it before sending).
            return 0
        n = min(len(buf), len(self.response))
        buf[:n] = self.response[:n]
        return n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    """Minimal socketpool stand-in."""

    AF_INET = 2
    SOCK_DGRAM = 2

    def __init__(self, responses):
        # responses: list of packets (or None) returned by successive requests
        self.responses = list(responses)
        self.request_count = 0

    def getaddrinfo(self, host, port):
        return [(2, 2, 0, "", ("10.0.0.1", port))]

    def socket(self, family, type_):
        idx = min(self.request_count, len(self.responses) - 1)
        self.request_count += 1
        return FakeSocket(self.responses[idx])


@contextlib.contextmanager
def board_time(module, monotonic_s=90_000):
    """Swap the module's `time` for the 32-bit-board fake."""
    fake = FakeTime(monotonic_s)
    original = module.time
    module.time = fake
    try:
        yield fake
    finally:
        module.time = original


def valid_unix_seconds(when=1_720_915_505):
    """A real-world unix timestamp (2024-07-14, when issue #35 was filed)."""
    return when + NTP_TO_UNIX_EPOCH
