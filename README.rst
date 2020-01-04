Introduction
============

.. image:: https://readthedocs.org/projects/adafruit-circuitpython-ntp/badge/?version=latest
    :target: https://circuitpython.readthedocs.io/projects/ntp/en/latest/
    :alt: Documentation Status

.. image:: https://img.shields.io/discord/327254708534116352.svg
    :target: https://discord.gg/nBQh6qu
    :alt: Discord

.. image:: https://github.com/adafruit/Adafruit_CircuitPython_NTP/workflows/Build%20CI/badge.svg
    :target: https://github.com/adafruit/Adafruit_CircuitPython_NTP/actions/
    :alt: Build Status

Network Time Protocol (NTP) helper for CircuitPython.


Dependencies
=============
This driver depends on:

* `Adafruit CircuitPython <https://github.com/adafruit/circuitpython>`_

Please ensure all dependencies are available on the CircuitPython filesystem.
This is easily achieved by downloading
`the Adafruit library and driver bundle <https://github.com/adafruit/Adafruit_CircuitPython_Bundle>`_.

Installing from PyPI
=====================
On supported GNU/Linux systems like the Raspberry Pi, you can install the driver locally `from
PyPI <https://pypi.org/project/adafruit-circuitpython-ntp/>`_. To install for current user:

.. code-block:: shell

    pip3 install adafruit-circuitpython-ntp

To install system-wide (this may be required in some cases):

.. code-block:: shell

    sudo pip3 install adafruit-circuitpython-ntp

To install in a virtual environment in your current project:

.. code-block:: shell

    mkdir project-name && cd project-name
    python3 -m venv .env
    source .env/bin/activate
    pip3 install adafruit-circuitpython-ntp

Usage Example
=============

.. code-block:: python

    import time
    import board
    import busio
    from digitalio import DigitalInOut
    from adafruit_esp32spi import adafruit_esp32spi
    from adafruit_ntp import NTP

    # If you are using a board with pre-defined ESP32 Pins:
    esp32_cs = DigitalInOut(board.ESP_CS)
    esp32_ready = DigitalInOut(board.ESP_BUSY)
    esp32_reset = DigitalInOut(board.ESP_RESET)

    # If you have an externally connected ESP32:
    # esp32_cs = DigitalInOut(board.D9)
    # esp32_ready = DigitalInOut(board.D10)
    # esp32_reset = DigitalInOut(board.D5)

    spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
    esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

    print("Connecting to AP...")
    while not esp.is_connected:
        try:
            esp.connect_AP(b"WIFI_SSID", b"WIFI_PASS")
        except RuntimeError as e:
            print("could not connect to AP, retrying: ", e)
            continue

    # Initialize the NTP object
    ntp = NTP(esp)

    # Fetch and set the microcontroller's current UTC time
    ntp.set_time()

    # Get the current time in seconds since Jan 1, 1970
    current_time = time.time()
    print("Seconds since Jan 1, 1970: {} seconds".format(current_time))


Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/adafruit/Adafruit_CircuitPython_NTP/blob/master/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.

Documentation
=============

For information on building library documentation, please check out `this guide <https://learn.adafruit.com/creating-and-sharing-a-circuitpython-library/sharing-our-docs-on-readthedocs#sphinx-5-1>`_.
