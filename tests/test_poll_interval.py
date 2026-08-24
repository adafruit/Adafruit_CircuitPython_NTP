# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""How far ahead the next sync is scheduled, given the server's poll byte.

The poll field is a single byte taken straight off the wire and used as
`2**poll` seconds until the next sync. RFC 5905 constrains it to
NTP_MINPOLL..NTP_MAXPOLL, but the library did not, so one corrupt or hostile
byte set the resync interval to anything from one second to 10**69 years --
while the returned time still looked perfectly valid, so nothing downstream
noticed. These tests pin both ends of the clamp, the pass-through in between,
and the interaction with an explicit `cache_seconds`.

`harness.board_time()` supplies a controllable monotonic clock, which is what
makes `next_sync` inspectable without waiting for real time to pass.

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

NTP_MINPOLL = 4  # 16 seconds
NTP_MAXPOLL = 17  # 131072 seconds, about 36 hours


def _next_sync_horizon_s(client, clock):
    return (client.next_sync - clock.monotonic_ns()) // 1_000_000_000


def test_absurd_poll_does_not_disable_resync():
    """A poll byte of 255 means 2**255 seconds -- roughly 10**69 years. One
    corrupt or hostile byte would stop the client ever re-syncing again, while
    still returning a valid-looking time so nothing downstream notices."""
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds(), poll=255)])
    with board_time(adafruit_ntp) as clock:
        client = adafruit_ntp.NTP(pool)
        assert client.datetime.tm_year == 2024
        horizon = _next_sync_horizon_s(client, clock)
    assert horizon <= 2**NTP_MAXPOLL, (
        f"next sync is {horizon}s away; the client would never re-sync"
    )


def test_tiny_poll_does_not_cause_aggressive_resync():
    """A poll byte of 0 means re-query every second. That is abusive by NTP
    standards, gets the client rate-limited, and is what made issue #35 fire as
    often as it did before cache_seconds landed in #37."""
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds(), poll=0)])
    with board_time(adafruit_ntp) as clock:
        client = adafruit_ntp.NTP(pool)
        _ = client.datetime
        horizon = _next_sync_horizon_s(client, clock)
    assert horizon >= 2**NTP_MINPOLL, f"next sync is only {horizon}s away"


def test_ordinary_poll_is_respected():
    """A poll inside the RFC range must pass through untouched."""
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds(), poll=6)])
    with board_time(adafruit_ntp) as clock:
        client = adafruit_ntp.NTP(pool)
        _ = client.datetime
        horizon = _next_sync_horizon_s(client, clock)
    assert horizon == pytest.approx(2**6, abs=1)


def test_absurd_poll_is_clamped_to_the_rfc_maximum():
    """With no explicit cache_seconds, a nonsense poll falls back to the RFC
    ceiling rather than to something arbitrary."""
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds(), poll=255)])
    with board_time(adafruit_ntp) as clock:
        client = adafruit_ntp.NTP(pool)
        _ = client.datetime
        horizon = _next_sync_horizon_s(client, clock)
    assert horizon == pytest.approx(2**NTP_MAXPOLL, abs=1)


def test_larger_cache_seconds_still_wins_over_a_clamped_poll():
    """cache_seconds is a floor, not a cap: `max(2**poll, cache_seconds)`. A
    caller asking for longer than the clamped poll interval still gets it."""
    longer = 2 ** (NTP_MAXPOLL + 1)
    pool = FakePool([make_packet(transmit_s=valid_unix_seconds(), poll=255)])
    with board_time(adafruit_ntp) as clock:
        client = adafruit_ntp.NTP(pool, cache_seconds=longer)
        _ = client.datetime
        horizon = _next_sync_horizon_s(client, clock)
    assert horizon == pytest.approx(longer, abs=1)
