# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""What `NTP` does with a response that is short, zeroed, or otherwise unusable.

A well-formed 48-byte datagram must still parse; anything that does not carry a
real transmit timestamp must raise `ArithmeticError` rather than crash, or --
worse -- return a plausible-looking wrong time. See the comment above the
rejection tests for the underlying defect.

`harness.board_time()` substitutes a `time` whose `localtime()` enforces the
32-bit machine-word limit a real board has and whose monotonic clock is
controllable. CPython's `localtime()` has no such limit, so without the shim
the board-only crash is invisible on a laptop.

Run from the repo root:

    python3 -m venv .venv && .venv/bin/pip install pytest
    .venv/bin/python -m pytest tests/ -v
"""

import pytest
from harness import (
    FakePool,
    board_time,
    make_packet,
    valid_unix_seconds,
)

import adafruit_ntp


# --------------------------------------------------------------------------
# Well-formed responses still work.
# --------------------------------------------------------------------------
def test_valid_response_returns_correct_time():
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds())])
    with board_time(adafruit_ntp) as clock:
        stamp = adafruit_ntp.NTP(pool).datetime
    assert stamp.tm_year == 2024
    assert clock.localtime_calls[-1] == pytest.approx(1_720_915_505, abs=2)


def test_response_longer_than_48_bytes_is_accepted():
    """recv_into fills the 48-byte buffer and reports 48, so an NTS or
    extension-field response must not be mistaken for a short read."""
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds()) + b"\xaa" * 20])
    with board_time(adafruit_ntp):
        assert adafruit_ntp.NTP(pool).datetime.tm_year == 2024


# --------------------------------------------------------------------------
# A zero or truncated timestamp is rejected instead of reaching localtime().
#
# The defect these cover is issue #35, `OverflowError` from `NTP.datetime`:
# https://github.com/adafruit/Adafruit_CircuitPython_NTP/issues/35
#
# The library uses one bytearray as both the request and the response buffer,
# zeroes it before sending, and discarded `recv_into`'s return value. Any
# datagram that failed to overwrite offsets 40-43 was parsed as the client's
# own zeros, giving a unix time of -2208988800. On a 32-bit board
# `time.localtime()` converts its argument to a machine word, -2208988800 does
# not fit in int32, and the OverflowError in the issue is the result.
# --------------------------------------------------------------------------
def test_zero_timestamp_response_is_rejected():
    """What the issue filer observed: `<class 'int'> 0` for the seconds field,
    immediately followed by the OverflowError. Now an ArithmeticError."""
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(ArithmeticError) as excinfo:
            _ = adafruit_ntp.NTP(pool).datetime
    assert not isinstance(excinfo.value, OverflowError), (
        "bogus timestamp reached time.localtime() instead of being rejected"
    )
    assert not clock.localtime_calls, "localtime() should never have been called"


def test_empty_recv_is_rejected():
    """A recv_into that writes nothing leaves the request buffer zeroed."""
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(ArithmeticError):
            _ = adafruit_ntp.NTP(FakePool([None])).datetime
    assert not clock.localtime_calls


# A datagram shorter than 48 bytes leaves part of the timestamp fields reading
# as the zeros the client wrote itself. Before the fix, 0-32 bytes raised
# OverflowError, 33-40 silently returned a time in 1962, and 41-43 silently
# returned a time wrong by weeks. All of them are now rejected.
@pytest.mark.parametrize("length", [0, 20, 32, 36, 40, 41, 43, 47])
def test_short_datagram_is_rejected(length):
    truncated = make_packet(transmit_s=valid_unix_seconds())[:length]
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(ArithmeticError):
            _ = adafruit_ntp.NTP(FakePool([truncated])).datetime
    assert not clock.localtime_calls, "a short read must never reach localtime()"


def test_short_datagram_never_returns_a_silently_wrong_time():
    """The quiet half of the bug. A 36-byte datagram carries a valid receive
    timestamp and a zeroed transmit timestamp; averaging them produced a time
    around 1962, which is inside int32 and so raised nothing at all. A silently
    wrong clock is worse than a crash, because nothing downstream notices."""
    truncated = make_packet(transmit_s=valid_unix_seconds())[:36]
    with board_time(adafruit_ntp):
        with pytest.raises(ArithmeticError):
            _ = adafruit_ntp.NTP(FakePool([truncated])).datetime


def test_second_request_after_a_good_one_is_rejected():
    """Matches the reported intermittency: first sync fine, next one garbage.
    The bad response must not be able to corrupt an already-good clock."""
    good = make_packet(transmit_s=valid_unix_seconds(), poll=0)
    bad = make_packet(transmit_s=0, recv_s=0, poll=0)
    pool = FakePool([good, bad])
    with board_time(adafruit_ntp, monotonic_s=1) as clock:
        client = adafruit_ntp.NTP(pool)
        assert client.datetime.tm_year == 2024
        clock.monotonic_s = 10_000  # push past next_sync so it re-queries
        with pytest.raises(ArithmeticError):
            _ = client.datetime
    assert pool.request_count == 2


def test_utc_ns_raises_rather_than_returning_a_pre_epoch_time():
    """utc_ns never calls localtime(), so before the fix a bogus response was
    not even loud: it returned -2208988800000000000 with no exception. Anything
    setting an RTC from that got a wildly wrong clock instead of an error it
    could retry."""
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp):
        with pytest.raises(ArithmeticError):
            _ = adafruit_ntp.NTP(pool).utc_ns


def test_documented_arithmeticerror_actually_exists():
    """`_update_time_sync` and `utc_ns` both document "ArithmeticError for
    substantially incorrect NTP results". Before the fix no code path could
    produce it: the guard from PR #38 was never merged, but the rewrite
    documented it anyway."""
    with open(adafruit_ntp.__file__) as handle:
        source = handle.read()
    raises = [line for line in source.splitlines() if "raise" in line and "ArithmeticError" in line]
    assert raises, "no `raise ArithmeticError` anywhere in the library"


def test_rejection_leaves_no_negative_timestamp_behind():
    """A rejected sync must not half-apply. _monotonic_start_ns stays at its
    previous value, so a later successful sync is unaffected."""
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp):
        client = adafruit_ntp.NTP(pool)
        with pytest.raises(ArithmeticError):
            _ = client.datetime
        assert client._monotonic_start_ns == 0
