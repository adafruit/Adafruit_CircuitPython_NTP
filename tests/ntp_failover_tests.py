# SPDX-FileCopyrightText: 2026 Bob Grant for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
ntp_failover_tests.py

Exercises the multi-server failover adafruit_ntp library on hardware. Deploy the failover library
as `adafruit_ntp.py` on the board first. Assumes Wi-Fi is already up (settings.toml) and
CircuitPython 10.x.


Two modes (MODE):
  "regress" — deterministic functional checks: dead-server failover, rotation/stickiness,
              all-dead -> OSError (ETIMEDOUT-compatible), single-server one-retry, periodic
              re-resolve. PASS/FAIL, _Tally, ~~END~~ sentinel.
  "survey"  — one single-server instance per server, round-robined every STEP_DELAY_S; tallies the
              *delivered* failure rate (post one-retry, i.e. what a library user sees) and deliver
              time.  This is the "many instances at once" survey — note it is NOT the raw
              per-packet loss rate (that's ntp_server_survey.py); the library's single-server
              retry masks lone drops.
"""

import gc
import time

import socketpool
import wifi

import adafruit_ntp

try:
    import traceback
except ImportError:
    traceback = None

# ---------------- config ----------------
MODE = "survey"  # "regress" or "survey"

SOCKET_TIMEOUT = 1

# A routable-but-silent sink so a query to it times out. If your network fast-errors these instead
# of timing out, the functional checks still hold (a failure is a failure); only the printed
# timings change.  You can swap in a known-dead host on your LAN.
DEAD_A = "192.0.2.1"  # TEST-NET-1 (RFC 5737)
DEAD_B = "192.0.2.2"
LIVE = "time.cloudflare.com"  # reliable anycast for the deterministic checks

# survey mode: each target is (label, server_arg). A single name measures that server's *delivered*
# reliability (via the 1-retry). A list makes a full failover client — delivered_fail should be ~0
# and you'll see failover events (fover) instead. The dead-seeded list keeps a dead member present
# the whole run to prove the client tolerates it indefinitely.
_POOL = [
    "0.adafruit.pool.ntp.org",
    "1.adafruit.pool.ntp.org",
    "2.adafruit.pool.ntp.org",
    "3.adafruit.pool.ntp.org",
]
SURVEY_TARGETS = [
    ("google", "time.google.com"),
    ("cloudflare", "time.cloudflare.com"),
    ("us.pool", "us.pool.ntp.org"),
    ("adafruit-failover", _POOL),
    ("dead-seeded-failover", ["192.0.2.1"] + _POOL),
]
STEP_DELAY_S = 12
ROUNDS = 0  # 0 = run until Ctrl-C
HEARTBEAT_S = 300
# ----------------------------------------

pool = socketpool.SocketPool(wifi.radio)


def _sync(obj):
    """Force a fresh sync; return (ok, elapsed_ms, exc)."""
    obj.next_sync = 0
    t0 = time.monotonic_ns()
    try:
        _ = obj.utc_ns
        return True, (time.monotonic_ns() - t0) // 1_000_000, None
    except Exception as exc:  # noqa: BLE001 — OSError (timeout) or ArithmeticError (bad packet)
        return False, (time.monotonic_ns() - t0) // 1_000_000, exc


class _Tally:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, label, ok):
        if ok:
            self.passed += 1
            print(f"PASS: {label}")
        else:
            self.failed += 1
            print(f"FAIL: {label}")


def run_regress():
    t = _Tally()

    # 1) dead-first failover: still returns a time; dead server rotates to the back, live to the
    # front.
    obj = adafruit_ntp.NTP(pool, server=(DEAD_A, LIVE), socket_timeout=SOCKET_TIMEOUT)
    ok, el, _ = _sync(obj)
    t.check("failover: dead-first list still returns a time", ok)
    t.check(
        "failover: a live server sits at the front now",
        bool(obj._addresses) and obj._addresses[0][0] != DEAD_A,
    )
    t.check(
        "failover: dead server rotated to the back",
        bool(obj._addresses) and obj._addresses[-1][0] == DEAD_A,
    )
    print(f"  (first sync took {el} ms; ~one dead timeout + RTT)")

    # 2) stickiness: the next sync hits the live front server, so it's fast (no dead-server wait).
    ok2, el2, _ = _sync(obj)
    t.check("stickiness: 2nd sync succeeds", ok2)
    t.check(f"stickiness: 2nd sync fast, skipped the dead server ({el2} ms)", ok2 and el2 < 900)

    # 3) all-dead: raises, and it's an OSError (ETIMEDOUT-compatible), returns no time.
    obj = adafruit_ntp.NTP(pool, server=(DEAD_A, DEAD_B), socket_timeout=SOCKET_TIMEOUT)
    ok, el, exc = _sync(obj)
    t.check("all-dead: raises rather than returning a time", not ok)
    t.check("all-dead: exception is OSError (backward-compatible)", isinstance(exc, OSError))
    print(f"  (all-dead took {el} ms; ~one timeout per server)")

    # 4) single-server one-retry: single dead server raises; single live server succeeds.
    obj = adafruit_ntp.NTP(pool, server=DEAD_A, socket_timeout=SOCKET_TIMEOUT)
    ok, el, exc = _sync(obj)
    t.check("single dead: raises OSError", (not ok) and isinstance(exc, OSError))
    print(f"  (single-server 1-retry took {el} ms; ~2x timeout)")
    obj = adafruit_ntp.NTP(pool, server=LIVE, socket_timeout=SOCKET_TIMEOUT)
    ok, _, _ = _sync(obj)
    t.check("single live: returns a time", ok)

    # 5) periodic re-resolve: with a short interval, the address list rebuilds (timestamp
    # advances).
    obj = adafruit_ntp.NTP(pool, server=LIVE, socket_timeout=SOCKET_TIMEOUT, reresolve_interval=1)
    _sync(obj)
    first = obj._last_resolve_ns
    time.sleep(1.3)
    ok5, _, _ = _sync(obj)
    t.check("re-resolve: list rebuilt after the interval", ok5 and obj._last_resolve_ns > first)

    # 6) defaults / normalization.
    t.check(
        "default server list is the four adafruit pool names",
        len(adafruit_ntp.NTP(pool)._servers) == 4,
    )
    t.check(
        "str server normalizes to a 1-tuple",
        adafruit_ntp.NTP(pool, server="one.x")._servers == ("one.x",),
    )

    # 7) a real datetime is plausible.
    obj = adafruit_ntp.NTP(pool, server=LIVE, socket_timeout=SOCKET_TIMEOUT)
    try:
        obj.next_sync = 0
        dt = obj.datetime
        t.check(f"live datetime is plausible (year {dt.tm_year})", dt.tm_year >= 2024)
    except Exception as exc:  # noqa: BLE001
        t.check("live datetime", False)
        if traceback is not None:
            traceback.print_exception(exc)

    print("ALL TESTS PASSED" if t.failed == 0 else "SOME TESTS FAILED")


def _new_stat():
    return {
        "n": 0,
        "fail": 0,
        "fover": 0,
        "reres": 0,
        "d_n": 0,
        "d_sum": 0,
        "d_min": None,
        "d_max": None,
        "prev": False,
        "consec": 0,
    }


def run_survey():  # noqa: PLR0914
    targets = [
        (label, adafruit_ntp.NTP(pool, server=srv, socket_timeout=SOCKET_TIMEOUT))
        for label, srv in SURVEY_TARGETS
    ]
    stats = {label: _new_stat() for label, _ in targets}
    interval = STEP_DELAY_S * len(targets)
    print(f"library survey: {len(targets)} instances, per-target interval ~{interval}s")
    print(
        "(single-name: delivered per-server rate; multi-name: failover client, delivered_fail ~0)"
    )

    # Warm up: resolve + settle so first-cycle DNS cost stays out of the measured stats. Log the
    # initial failover (documents the dead-seeded case and any dead first pool member) and the
    # resolved member count (a low count means a name failed to resolve or collapsed as a
    # duplicate).
    for label, obj in targets:
        try:
            obj._resolve_servers()
        except OSError:
            print(f"  {label}: no servers resolved")
            continue
        first_ip = obj._addresses[0][0]
        resolved_n = len(obj._addresses)
        ok, _, exc = _sync(obj)
        new_ip = obj._addresses[0][0] if obj._addresses else None
        if ok and new_ip != first_ip:
            print(
                f"  {label}: resolved {resolved_n} member(s); initial failover "
                f"{first_ip} -> {new_ip}"
            )
        elif not ok:
            kind = type(exc).__name__ if exc else "?"
            print(f"  {label}: resolved {resolved_n} member(s); initial sync failed ({kind})")
        else:
            print(f"  {label}: resolved {resolved_n} member(s)")

    start = time.monotonic_ns()
    next_hb = start + HEARTBEAT_S * 1_000_000_000
    r = 0
    try:
        while ROUNDS == 0 or r < ROUNDS:
            for label, obj in targets:
                s = stats[label]
                front_before = obj._addresses[0] if obj._addresses else None
                resolve_before = obj._last_resolve_ns
                ok, ms, exc = _sync(obj)
                reresolved = obj._last_resolve_ns != resolve_before
                front_after = obj._addresses[0] if obj._addresses else None
                s["n"] += 1
                if reresolved:
                    # a DNS refresh can change the front IP on its own; not a failover, and its
                    # cost doesn't belong in deliver_ms
                    s["reres"] += 1
                elif (
                    front_before is not None
                    and front_after is not None
                    and front_before != front_after
                ):
                    s["fover"] += 1
                    print(f"  {label}: failover {front_before[0]} -> {front_after[0]}")
                if ok:
                    if not reresolved:
                        s["d_n"] += 1
                        s["d_sum"] += ms
                        s["d_min"] = ms if s["d_min"] is None else min(s["d_min"], ms)
                        s["d_max"] = ms if s["d_max"] is None else max(s["d_max"], ms)
                    s["prev"] = False
                else:
                    s["fail"] += 1
                    if s["prev"]:
                        s["consec"] += 1
                    s["prev"] = True
                    print(f"  {label}: delivered failure ({type(exc).__name__ if exc else '?'})")
                time.sleep(STEP_DELAY_S)
            if time.monotonic_ns() >= next_hb:
                _report(stats, targets, start)
                next_hb += HEARTBEAT_S * 1_000_000_000
            gc.collect()
            r += 1
    except KeyboardInterrupt:
        print("stopped by user")
    _report(stats, targets, start)


def _report(stats, targets, start):
    elapsed_s = (time.monotonic_ns() - start) // 1_000_000_000
    print(f"=== delivered @ {elapsed_s}s ===")
    for label, _ in targets:
        s = stats[label]
        n, f = s["n"], s["fail"]
        deliver = f"{s['d_min']}/{s['d_sum'] // s['d_n']}/{s['d_max']}" if s["d_n"] else "-/-/-"
        if n == 0:
            rate = "n/a"
        elif f == 0:
            rate = f"0 (<{3.0 / n * 100:.3f}% at 95%)"
        else:
            rate = f"{f / n * 100:.3f}%"
        print(
            f"  {label}: n={n} delivered_fail={f} [{rate}] failovers={s['fover']} "
            f"reresolves={s['reres']} consec={s['consec']} deliver_ms[min/mean/max]={deliver}"
        )


try:
    if MODE == "survey":
        run_survey()
    else:
        run_regress()
except Exception as e:  # noqa: BLE001
    print(f"harness error: {type(e).__name__}: {e}")
    if traceback is not None:
        traceback.print_exception(e)

print("~~END~~")
