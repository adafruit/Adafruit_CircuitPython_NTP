Introduction
============

.. image:: https://readthedocs.org/projects/adafruit-circuitpython-ntp/badge/?version=latest
    :target: https://docs.circuitpython.org/projects/ntp/en/latest/
    :alt: Documentation Status

.. image:: https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_Bundle/main/badges/adafruit_discord.svg
    :target: https://adafru.it/discord
    :alt: Discord

.. image:: https://github.com/adafruit/Adafruit_CircuitPython_NTP/workflows/Build%20CI/badge.svg
    :target: https://github.com/adafruit/Adafruit_CircuitPython_NTP/actions/
    :alt: Build Status

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black
    :alt: Code Style: Black

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
    python3 -m venv .venv
    source .venv/bin/activate
    pip3 install adafruit-circuitpython-ntp

Usage Example
=============

.. code-block:: python

    import adafruit_connection_manager
    import adafruit_ntp
    import os
    import time
    import wifi

    wifi_ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    wifi_password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    wifi.radio.connect(wifi_ssid, wifi_password)

    pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
    ntp = adafruit_ntp.NTP(pool, tz_offset=0, cache_seconds=3600)

    while True:
        print(ntp.datetime)
        time.sleep(1)


Documentation
=============

API documentation for this library can be found on `Read the Docs <https://docs.circuitpython.org/projects/ntp/en/latest/>`_.

For information on building library documentation, please check out `this guide <https://learn.adafruit.com/creating-and-sharing-a-circuitpython-library/sharing-our-docs-on-readthedocs#sphinx-5-1>`_.

Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/adafruit/Adafruit_CircuitPython_NTP/blob/main/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.
