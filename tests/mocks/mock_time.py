# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Mock code to simulate attributes of the time module for testing adafruit_ntp

Usage:
    import tests.mock_time as mock_time
    from tests.mock_time import MockTime
    sys.modules['time'] = mock_time
    from adafruit_ntp import NTP …

The adafruit_ntp module will import the time module and get the module functions provided here.
The unittest code will access and manipulate the mock time state through an instance (singleton)
of the MockTime class.

During unittesting, the mock time can be advanced by calling the mock_time instance's set_mock_ns()
method, and accessed with get_mock_ns().
"""

import time

try:
    from typing import Optional
except ImportError:
    pass
from tests.shared_for_testing import (
    setup_logger,
    fmt_thousands,
    MOCK_LOGGER,
    NS_PER_SEC,
    MOCKED_TIME_DEFAULT_START_NS,
    MOCKED_TIME_NEW_MSG,
    MOCKED_TIME_FIRST_NEW_MSG,
    MOCKED_TIME_MONOTONIC_NS_MSG,
    MOCKED_TIME_SLEEP_MSG,
    MOCKED_TIME_LOCALTIME_MSG,
    MOCKED_TIME_NOT_LOCALTIME_EX,
)

# Expose struct_time for compatibility
struct_time = time.struct_time  # pylint:disable=invalid-name

# A Logging instance that the UnitTest code can use to monitor calls to the mocked functionality.
_logger = setup_logger(MOCK_LOGGER)


class MockTime:
    """Singleton class to hold the state of the mock time module."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        _logger.info(MOCKED_TIME_NEW_MSG)
        if cls._instance is None:
            _logger.info(MOCKED_TIME_FIRST_NEW_MSG)
            cls._instance = super(MockTime, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        """Additional (duplicate) instances should not change the internal singleton state."""
        if not hasattr(self, "_initialized"):
            # Do not start at zero. It confuses the app. Use a 'fake' boot time delay instead.
            self._monotonic_ns = MOCKED_TIME_DEFAULT_START_NS
            self._initialized = True

    def monotonic_ns(self) -> int:
        """Simulate time.monotonic_ns, incrementing mock nanoseconds with each call."""
        self._monotonic_ns += 1
        _logger.info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(self._monotonic_ns))
        return self._monotonic_ns

    def sleep(self, seconds: float) -> None:
        """Simulate time.sleep by advancing mock nanoseconds by the specified duration."""
        _logger.info(MOCKED_TIME_SLEEP_MSG, seconds)
        self._monotonic_ns += int(seconds * NS_PER_SEC)

    @staticmethod
    def localtime(seconds: Optional[float] = None) -> time.struct_time:
        """simulate time.localtime, but only when a seconds value is provided.

        This could be merged into the module level function. Keeping it in the instance to
        to keep the functionality in the class, which allows future enhancements that might
        want to manipulate the result via the controlling instance. IE return a specific
        value instead of using the built in function.
        """
        _logger.info(MOCKED_TIME_LOCALTIME_MSG, seconds)
        if seconds is None:
            # not reasonable to get 'now' time in environment without a real time clock.
            raise MOCKED_TIME_NOT_LOCALTIME_EX
        return time.localtime(seconds)

    def get_mock_ns(self) -> int:
        """
        Get the current mock time in nanoseconds without advancing the clock.

        This bypasses the actual mocked methods to avoid the logging and increment,
        allowing direct access for testing purposes.
        """
        return self._monotonic_ns

    def set_mock_ns(self, time_ns: int) -> None:
        """
        Set the mock time in nanoseconds.

        This is useful in testing scenarios where manual control of the time flow is required.
        """
        self._monotonic_ns = time_ns

    @classmethod
    def get_mock_instance(cls) -> "MockTime":
        """Get the singleton instance of MockTime without going through instantiation."""
        if MockTime._instance is None:
            raise AttributeError(
                "No MockTime instance currently exists. Call MockTime() first."
            )
        return MockTime._instance

    @classmethod
    def clear_mock_singleton(cls) -> None:
        """Explicitly reset the singleton to 'undefined' for testing control.

        Do **NOT** call this directly from testing code. Use the module level function instead.
        """
        cls._instance = None


# Mocked module-level functions
_mock_time_instance = MockTime()


def monotonic_ns() -> int:
    """Module-level function to simulate time.monotonic_ns, using the singleton instance."""
    return _mock_time_instance.monotonic_ns()


def sleep(seconds: float) -> None:
    """Module-level function to simulate time.sleep, using the singleton instance."""
    _mock_time_instance.sleep(seconds)


def localtime(seconds: Optional[float] = None) -> time.struct_time:
    """Module-level function to simulate time.localtime, using the singleton instance."""
    return _mock_time_instance.localtime(seconds)


def get_mock_instance() -> MockTime:
    """Get the (global) singleton instance for MockTime."""
    return _mock_time_instance


def clear_mock_singleton() -> None:
    """Clear the singleton instance of MockTime for testing purposes, and create a new instance."""
    global _mock_time_instance  # pylint:disable=global-statement
    MockTime.clear_mock_singleton()
    _mock_time_instance = MockTime()
