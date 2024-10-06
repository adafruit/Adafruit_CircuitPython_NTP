# SPDX-FileCopyrightText: 2024 H PHil Duby
# SPDX-License-Identifier: MIT

"""Print out time based on NTP using power saving options between updates."""

import os
import time

import socketpool
import wifi

from adafruit_ntp import NTP, EventType, NTPIncompleteError

print("Start PowerSave example")
check_connection = False  # pylint:disable=invalid-name
# Get wifi AP credentials from a settings.toml file
wifi_ssid = os.getenv("CIRCUITPY_WIFI_SSID")
wifi_password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
# print(f'have credentials: {time.monotonic_ns() =}')  # DEBUG


def on_ntp_event(event_type: EventType, next_time: int):
    """Handle notifications from NTP about not using the radio for awhile."""
    global check_connection  # pylint:disable=global-statement
    if event_type == EventType.NO_EVENT:
        print(
            "No Event: "
            f"{time.monotonic_ns() =}, {wifi.radio.enabled =}, {wifi.radio.connected =}"
        )
        return
    print(f"event {event_type}: Next operation scheduled at {next_time} ns")
    if event_type == EventType.LOOKUP_FAILED:
        check_connection = True
        return
    wifi.radio.enabled = False
    if event_type == EventType.SYNC_FAILED:
        raise RuntimeError("NTP sync failed")


def check_wifi_connection():
    """Check if the WiFi connection is still (currently) active."""
    global check_connection  # pylint:disable=global-statement
    # Always reset the flag to False. Another notification will set it true again as needed.
    check_connection = False
    # print(f'checking connection: {time.monotonic_ns() =}, {wifi.radio.enabled =}')  # DEBUG
    if not wifi.radio.enabled:
        wifi.radio.enabled = True
    if wifi.radio.connected:
        return
    print("Connecting to WiFi...")
    if wifi_ssid is None:
        print("WiFi credentials are kept in settings.toml, please add them there!")
        raise ValueError("SSID not found in environment variables")

    try:
        wifi.radio.connect(wifi_ssid, wifi_password)
    except ConnectionError as ex:
        print(f"Failed to connect to WiFi with provided credentials: {ex}")
    # print(f'done connect attempt: {time.monotonic_ns() =}')  # DEBUG


def fmt_iso(datetime: time.struct_time) -> str:
    """Format the datetime as ISO 8601."""
    return (
        f"{datetime.tm_year}-{datetime.tm_mon:02d}-{datetime.tm_mday:02d}"
        + f"T{datetime.tm_hour:02d}:{datetime.tm_min:02d}:{datetime.tm_sec:02d}"
    )


pool = socketpool.SocketPool(wifi.radio)
ntp = NTP(pool, blocking=False)
# ntp.register_ntp_event_callback(on_ntp_event, EventType.SYNC_COMPLETE |
#                       EventType.SYNC_FAILED | EventType.LOOKUP_FAILED)
ntp.register_ntp_event_callback(on_ntp_event, EventType.ALL_EVENTS)
# ntp.register_ntp_event_callback(on_ntp_event, 0b111)  # == 7 == 0x7

while True:
    if check_connection:
        check_wifi_connection()
    else:
        try:
            print(fmt_iso(ntp.datetime))
        except NTPIncompleteError:
            print("Waiting for NTP information")
        except Exception as ex:
            print(f"{type(ex)}")
            print(f"Exception: {ex}")
            raise
    # other regular processing …
    time.sleep(1)
