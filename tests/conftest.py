# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""Make the CircuitPython library importable under CPython.

Two things are needed: a stand-in for the `micropython` module, which CPython
does not have, and the repo root on sys.path so `import adafruit_ntp` finds the
library next to this directory.
"""

import os
import sys
import types

# adafruit_ntp does `from micropython import const`.
if "micropython" not in sys.modules:
    _mp = types.ModuleType("micropython")
    _mp.const = lambda x: x
    sys.modules["micropython"] = _mp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
