# tests

Reproduction for [issue #35](https://github.com/adafruit/Adafruit_CircuitPython_NTP/issues/35)
(`OverflowError: overflow converting long int to machine word`). Upstream ships
no test suite, so this directory is self-contained.

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -v
```

## What's here

| File | What |
|---|---|
| `test_issue35.py` | The bug, driven through a fake socketpool |
| `test_real_sockets.py` | The same mechanisms shown with CPython's real UDP sockets |
| `harness.py` | Fake socketpool + a `time` shim enforcing the 32-bit machine-word limit on `localtime()`, as a real board does |
| `conftest.py` | `micropython.const` shim, and puts the repo root on `sys.path` so `import adafruit_ntp` works |

Everything runs against `../adafruit_ntp.py` in the working tree. No hardware
and no network are needed.

## Why the `time` shim matters

The failure only exists on a 32-bit board. `time.localtime()` there converts its
argument to a **machine word**, and CPython's does not — so the bug that crashes
a QT Py ESP32-S2 passes silently under plain CPython. `harness.board_time()`
substitutes a `time` whose `localtime()` enforces the int32 limit and whose
monotonic clock is controllable. That makes a board-only crash deterministic on
a laptop.

## Expected result

```
25 passed
```

## What the tests establish

The library reuses one `bytearray` as both request and response buffer, zeroes
it before sending, and discards `recv_into`'s return value — so it reads back
its own zeros whenever a datagram fails to overwrite offsets 40-43. What that
produces depends on where the datagram truncates:

| bytes received | before the fix | now |
|---|---|---|
| 0-32 | `OverflowError` | `ArithmeticError` |
| 33-40 | silently returned a time decades off (1962) | `ArithmeticError` |
| 41-43 | silently wrong by weeks | `ArithmeticError` |
| 44-48 | correct | correct |

The 1962 row was the quieter half: `datetime` averages the server's receive and
transmit timestamps, so a valid receive plus a zeroed transmit landed halfway
between 1900 and now — inside int32, so nothing raised at all. A guard that only
checked for a zero timestamp would not have caught the 41-43 row either; that
one needs the length check.

`test_real_sockets.py` confirms the mechanism outside the fake: buffer reuse and
truncation over loopback UDP, an over-48-byte response being harmless, and —
because the socket is never `connect()`ed — acceptance of a datagram from a
source that is not the server.
