# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Unittests for instantiation of NTP instances from adafruit_ntp
"""

import unittest
from tests.shared_for_testing import (
    # set_utc_timezone,
    DEFAULT_NTP_ADDRESS,
    NS_PER_SEC,
)
from tests.mocks.mock_pool import MockPool
from tests.shared_for_testing import set_utc_timezone, mock_cleanup

# ntp_testing_support overrides sys.modules['time']. Make sure anything that needs
# the real time module is imported first.
from tests.ntp_testing_support import (
    NTP,
    MockTime,
    mock_time,
    get_ntp_state,
    match_expected_field_values,
    DEFAULT_NTP_STATE,
)


class TestNTPInstantiation(unittest.TestCase):
    """Test cases for constructing an NTP instance with various arguments.

    Other testing initializes the NTP instance using direct write to private properties. This
    checks that those private properties are being set to the expected state by the constructor.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        set_utc_timezone()
        cls.mock_pool = MockPool()
        cls.mock_time = MockTime()
        cls.mock_time.set_mock_ns(NS_PER_SEC)

    @classmethod
    def tearDownClass(cls):
        """Clear the singleton instances."""
        MockPool.clear_mock_singleton()
        mock_time.clear_mock_singleton()

    def setUp(self):
        """Common initialization for each test method."""
        # self.ntp: NTP = None

    def test_default_constructor(self):
        """Test the default constructor."""
        ntp = NTP(self.mock_pool)
        expected_state = DEFAULT_NTP_STATE.copy()
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_alternate_server(self):
        """Test constructing with an alternate server url."""
        alt_server = "ntp.example.com"
        ntp = NTP(self.mock_pool, server=alt_server)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.server = alt_server
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_alternate_port(self):
        """Test constructing with an alternate port number."""
        alt_port = 9876
        ntp = NTP(self.mock_pool, port=alt_port)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.port = alt_port
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_alternate_tz_offset(self):
        """Test constructing with an alternate time zone offset."""

        alt_tz_offset = -1.5
        ntp = NTP(self.mock_pool, tz_offset=alt_tz_offset)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.tz_offset_ns = int(alt_tz_offset * 60 * 60) * NS_PER_SEC
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_alternate_timeout(self):
        """Test constructing with an alternate timeout value."""
        alt_timeout = 15
        ntp = NTP(self.mock_pool, socket_timeout=alt_timeout)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.socket_timeout = alt_timeout
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_cache_minimum(self):
        """Test constructing specify less than minimum cache duration."""
        min_cache = 60 * NS_PER_SEC
        ntp = NTP(self.mock_pool, cache_seconds=55)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.cache_ns = min_cache
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_alternate_cache(self):
        """Test constructing with an alternate cache duration."""
        alt_cache = 355 * NS_PER_SEC
        ntp = NTP(self.mock_pool, cache_seconds=alt_cache // NS_PER_SEC)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.cache_ns = alt_cache
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_non_blocking(self):
        """Test constructing in non-blocking mode."""
        ntp = NTP(self.mock_pool, blocking=False)
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.blocking = False
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_specified_defaults(self):
        """Test constructing with specified default values."""
        ntp = NTP(
            self.mock_pool,
            server=DEFAULT_NTP_ADDRESS[0],
            port=DEFAULT_NTP_ADDRESS[1],
            tz_offset=0,
            socket_timeout=10,
            cache_seconds=60,
            blocking=True,
        )
        expected_state = DEFAULT_NTP_STATE.copy()
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )

    def test_specify_all_alternates(self):
        """Test constructing with all alternate values."""
        alt_server = "ntp.example.com"
        alt_port = 9876
        alt_tz_offset = -1.5
        alt_timeout = 15
        alt_cache = 355 * NS_PER_SEC
        ntp = NTP(
            self.mock_pool,
            server=alt_server,
            port=alt_port,
            tz_offset=alt_tz_offset,
            socket_timeout=alt_timeout,
            cache_seconds=alt_cache // NS_PER_SEC,
            blocking=False,
        )
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.server = alt_server
        expected_state.port = alt_port
        expected_state.tz_offset_ns = int(alt_tz_offset * 60 * 60) * NS_PER_SEC
        expected_state.socket_timeout = alt_timeout
        expected_state.cache_ns = alt_cache
        expected_state.blocking = False
        unmatched = match_expected_field_values(expected_state, get_ntp_state(ntp))
        self.assertEqual(
            unmatched, set(), f"NTP instance fields {unmatched} do not match expected"
        )


if __name__ == "__main__":
    unittest.main()

mock_cleanup()
