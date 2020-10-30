"""Tests NTP with CPython socket"""

# SPDX-FileCopyrightText: 2022 Scott Shawcroft for Adafruit Industries
# SPDX-License-Identifier: MIT

import adafruit_ntp
import socket
import time

# Don't use tz_offset kwarg with CPython because it will adjust automatically.
ntp = adafruit_ntp.NTP(socket)

while True:
    print(ntp.datetime)
    time.sleep(1)
