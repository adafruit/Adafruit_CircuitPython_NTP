# SPDX-FileCopyrightText: 2024 Justin Myers for Adafruit Industries
# SPDX-FileCopyrightText: 2024 anecdata for Adafruit Industries
#
# SPDX-License-Identifier: Unlicense

"""Print out time based on NTP, using connection manager"""

import time
import adafruit_connection_manager
import adafruit_ntp

try:
    import wifi
    import os

    # adjust method to get credentials as necessary...
    wifi_ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    wifi_password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    radio = wifi.radio
    while not radio.connected:
        radio.connect(wifi_ssid, wifi_password)
except ImportError:
    import board
    from digitalio import DigitalInOut

    spi = board.SPI()
    try:
        from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K

        # adjust pin for the specific board...
        eth_cs = DigitalInOut(board.D10)
        radio = WIZNET5K(spi, eth_cs)
    except ImportError:
        from adafruit_esp32spi.adafruit_esp32spi import ESP_SPIcontrol

        # adjust pins for the specific board...
        esp32_cs = DigitalInOut(board.ESP_CS)
        esp32_ready = DigitalInOut(board.ESP_BUSY)
        esp32_reset = DigitalInOut(board.ESP_RESET)
        radio = ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

# get the socket pool from connection manager
socket = adafruit_connection_manager.get_radio_socketpool(radio)

# adjust tz_offset for locale...
ntp = adafruit_ntp.NTP(socket, tz_offset=-5)

while True:
    print(ntp.datetime)
    time.sleep(5)
