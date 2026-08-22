# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""Reproduction for issue #35, `OverflowError` from `NTP.datetime`.

    https://github.com/adafruit/Adafruit_CircuitPython_NTP/issues/35

Run from the repo root:

    python3 -m venv .venv && .venv/bin/pip install pytest
    .venv/bin/python -m pytest tests/ -v

These tests document what `adafruit_ntp.py` in this working tree currently does
with a malformed response. They are expected to fail once the library starts
validating the server timestamp -- that is the point of them, and the two
xfails below are what should start passing at the same time.

The failure only exists on a 32-bit board, where `time.localtime()` converts
its argument to a machine word. CPython's does not, so the crash is invisible
under plain CPython. `harness.board_time()` substitutes a `time` whose
`localtime()` enforces the int32 limit and whose monotonic clock is
controllable, which makes a board-only failure deterministic on a laptop with
no hardware.
"""

import pytest
from harness import (
    NTP_TO_UNIX_EPOCH,
    FakePool,
    board_time,
    make_packet,
    valid_unix_seconds,
)

import adafruit_ntp


# --------------------------------------------------------------------------
# Sanity
# --------------------------------------------------------------------------
def test_valid_response_returns_correct_time():
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds())])
    with board_time(adafruit_ntp) as clock:
        stamp = adafruit_ntp.NTP(pool).datetime
    assert stamp.tm_year == 2024
    assert clock.localtime_calls[-1] == pytest.approx(1_720_915_505, abs=2)


# --------------------------------------------------------------------------
# The bug. A response whose timestamp seconds are 0 yields a unix time of about
# -2208988800, which does not fit in a 32-bit machine word.
# --------------------------------------------------------------------------
def test_zero_timestamp_response_overflows():
    """Exactly what the issue filer observed: `<class 'int'> 0` for the
    seconds field, immediately followed by the OverflowError."""
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(OverflowError, match="machine word"):
            _ = adafruit_ntp.NTP(pool).datetime
    assert clock.localtime_calls[-1] == pytest.approx(-NTP_TO_UNIX_EPOCH, abs=10)


def test_empty_recv_leaves_zeroed_packet_and_overflows():
    """A recv_into that writes nothing leaves the request buffer zeroed."""
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(OverflowError, match="machine word"):
            _ = adafruit_ntp.NTP(FakePool([None])).datetime
    assert clock.localtime_calls[-1] == pytest.approx(-NTP_TO_UNIX_EPOCH, abs=10)


# The library reuses ONE bytearray for the request and the response, zeroes it
# before sending, and discards recv_into's return value. So a datagram shorter
# than 48 bytes leaves part of the timestamp fields reading as the zeros the
# client wrote itself. What that produces depends on where it truncates.


@pytest.mark.parametrize("length", [0, 20, 32])
def test_short_datagram_below_32_bytes_overflows(length):
    """Nothing reaches either timestamp field -- the reported OverflowError."""
    truncated = make_packet(transmit_s=valid_unix_seconds())[:length]
    with board_time(adafruit_ntp) as clock:
        with pytest.raises(OverflowError, match="machine word"):
            _ = adafruit_ntp.NTP(FakePool([truncated])).datetime
    assert clock.localtime_calls[-1] == pytest.approx(-NTP_TO_UNIX_EPOCH, abs=10)


@pytest.mark.parametrize("length", [36, 40])
def test_short_datagram_33_to_40_returns_a_silently_wrong_time(length):
    """`datetime` averages the server's receive and transmit timestamps, so a
    datagram of 33-40 bytes -- a VALID receive timestamp and a zeroed transmit
    timestamp -- averages to about halfway between 1900 and now. That is inside
    int32, so localtime() does not complain and nothing is raised at all. This
    is the quieter half of the bug: a silently wrong clock rather than a crash.

    Asserted as "nowhere near the real time" rather than as an exact year. The
    observed value today is 1962, but that number is a consequence of the
    averaging; the contract being broken is that a malformed response yields a
    plausible-looking time instead of an error."""
    truncated = make_packet(transmit_s=valid_unix_seconds())[:length]
    with board_time(adafruit_ntp) as clock:
        stamp = adafruit_ntp.NTP(FakePool([truncated])).datetime  # no exception
    assert stamp.tm_year < 2000, "expected a wildly wrong year (observed: 1962)"
    off_by = abs(clock.localtime_calls[-1] - 1_720_915_505)
    assert off_by > 10 * 365 * 24 * 3600, "expected to be wrong by decades"


@pytest.mark.parametrize("length", [41, 43])
def test_partial_timestamp_bytes_give_a_plausible_but_wrong_time(length):
    """Truncating mid-field zeroes only the low bytes of the transmit
    timestamp. The year still looks right, so nothing downstream flags it, but
    the clock is off by days. A range check on the year would not catch this;
    checking the recv_into length would."""
    correct = 1_720_915_505
    truncated = make_packet(transmit_s=valid_unix_seconds())[:length]
    with board_time(adafruit_ntp) as clock:
        stamp = adafruit_ntp.NTP(FakePool([truncated])).datetime
    assert stamp.tm_year == 2024
    assert abs(clock.localtime_calls[-1] - correct) > 60, "silently wrong time"


def test_second_request_after_a_good_one_still_overflows():
    """Matches the reported intermittency: first sync fine, next one garbage."""
    good = make_packet(transmit_s=valid_unix_seconds(), poll=0)
    bad = make_packet(transmit_s=0, recv_s=0, poll=0)
    pool = FakePool([good, bad])
    with board_time(adafruit_ntp, monotonic_s=1) as clock:
        client = adafruit_ntp.NTP(pool)
        assert client.datetime.tm_year == 2024
        clock.monotonic_s = 10_000  # push past next_sync so it re-queries
        with pytest.raises(OverflowError, match="machine word"):
            _ = client.datetime
    assert pool.request_count == 2


def test_utc_ns_fails_silently_instead_of_raising():
    """utc_ns never calls localtime(), so a bogus response is not even loud --
    it returns a pre-1970 timestamp with no exception at all. Anything setting
    an RTC from this gets a wildly wrong clock instead of a retryable error."""
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp):
        value = adafruit_ntp.NTP(pool).utc_ns
    assert value == pytest.approx(-NTP_TO_UNIX_EPOCH * 1_000_000_000, rel=1e-4)
    assert value < 0, "silently reports a time before the unix epoch"


# --------------------------------------------------------------------------
# What a fix should do. These xfail today and pass once the library rejects a
# bogus server timestamp instead of doing arithmetic on it.
# --------------------------------------------------------------------------
@pytest.mark.xfail(reason="library does not validate the server timestamp")
def test_invalid_response_rejected_rather_than_overflowing():
    pool = FakePool([make_packet(transmit_s=0, recv_s=0)])
    with board_time(adafruit_ntp):
        with pytest.raises(ArithmeticError) as excinfo:
            _ = adafruit_ntp.NTP(pool).datetime
    # OverflowError is itself a subclass of ArithmeticError, so be explicit:
    # we want a deliberate validation error, not the machine-word blowup.
    assert not isinstance(excinfo.value, OverflowError), (
        "bogus server timestamp reached time.localtime() instead of being rejected"
    )


@pytest.mark.xfail(reason="docstrings promise an ArithmeticError the code cannot raise")
def test_documented_arithmeticerror_actually_exists():
    """`_update_time_sync` and `utc_ns` both document "ArithmeticError for
    substantially incorrect NTP results". No code path can produce it: the
    guard from PR #38 was never merged, but the rewrite documented it anyway."""
    with open(adafruit_ntp.__file__) as handle:
        source = handle.read()
    assert "ArithmeticError" in source, "docstring promise is gone; update this test"
    raises = [line for line in source.splitlines() if "raise" in line and "ArithmeticError" in line]
    assert raises, "no `raise ArithmeticError` anywhere in the library"
