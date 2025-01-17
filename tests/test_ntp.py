# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Unittests for adafruit_ntp
"""

import unittest
import adafruit_logging as logging
from tests.mocks.mock_pool import MockPool, MockCallback, MockSocket
from tests.mocks.mock_time import MockTime
from tests.shared_for_testing import (
    ListHandler,
    setup_logger,
    set_utc_timezone,
    mock_cleanup,
    MOCK_LOGGER,
    NS_PER_SEC,
    MOCKED_TIME_DEFAULT_START_NS,
    GETADDR_DNS_EX,
)

# ntp_testing_support overrides sys.modules['time']. Make sure anything that needs
# the builtin time module is imported first.
from tests.ntp_testing_support import (
    BaseNTPTest,
    mock_time,
    logged_for_time_reference,
    set_ntp_state,
    DEFAULT_NTP_STATE,
    INCOMPLETE_EX,
    SENDTO_BROKENPIPE_EX,
)

# Import the adafruit_ntp module components, which should import the mock versions of modules
# defined above, unless they are injected on instantiation.
from adafruit_ntp import NTP, EventType  # pylint:disable=wrong-import-position


class TestNTPFunction(BaseNTPTest):  # pylint:disable=too-many-public-methods
    """Test cases for adafruit_ntp module functionality.

    Most tests needs to be done for 4 different scenario combinations:
    - blocking or non-blocking
    - with and without notification callbacks
    With 'white box' testing, the notifications could just always be included. With or
    without notification does not alter the flow of the code. Best to test both ways anyway,
    to not rely on that.

    Once tests are done to verify that the requested notifications are working, all other
    tests that include notifications can use a single 'all events' notification. The log
    messages from that will show (log) all triggered events.
    """

    # Constants
    # Testing scenarios                               blocking | notifications
    LEGACY: str = "legacy"  # yes          no
    MONITORING: str = "monitoring"  # yes         yes
    NON_BLOCKING: str = "non-blocking"  #  no          no
    MON_NON_BLOCKING: str = "monitored non-blocking"  #  no         yes

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        set_utc_timezone()
        cls.mock_time = MockTime()
        cls.mock_pool = MockPool()
        cls.mock_socket = cls.mock_pool.socket(
            cls.mock_pool.AF_INET, cls.mock_pool.SOCK_DGRAM
        )
        cls.mogger: logging.Logger = setup_logger(MOCK_LOGGER)
        # py lint:disable=protected-access
        cls._log_handler = ListHandler()
        cls._log_handler.log_only_to_me(cls.mogger)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        cls.mogger.removeHandler(cls._log_handler)
        mock_time.clear_mock_singleton()
        MockPool.clear_mock_singleton()
        MockSocket.clear_mock_singleton()

    def setUp(self):
        """Common initialization for each test method."""
        self.mock_pool.mock_getaddrinfo_attempts.clear()
        self.mock_socket.mock_recv_into_attempts.clear()
        start = DEFAULT_NTP_STATE.copy()
        start.monotonic_ns = MOCKED_TIME_DEFAULT_START_NS
        self.ntp = NTP(self.mock_pool)
        set_ntp_state(start, self.ntp)
        self.mogger.setLevel(logging.INFO)  # pylint:disable=no-member
        self._log_handler.log_records.clear()

    def tearDown(self):
        """Clean up after each test."""

    # @ unittest.skip('trace changed pattern')
    def test_legacy_no_cache_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP DNS address lookup without previous cached offset.
        (blocking, no notification).
        """
        notification_context = None
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX] * 10)

        expected_state = self._set_and_verify_ntp_state(DEFAULT_NTP_STATE)
        initial_time = self._prime_expected_dns_fail_state(expected_state)

        for _ in range(
            10
        ):  # Do enough iterations to get into the maximum rate limiting delay
            self._dns_failure_cycle(expected_state, notification_context)
            if not expected_state.blocking:
                # need to advance time to get past each rate limiting delay
                saved_ns = self.mock_time.get_mock_ns()
                self.mock_time.set_mock_ns(expected_state.limit_end)
                expected_state.monotonic_ns = expected_state.limit_end
        if not expected_state.blocking:
            # Undo the final time advance
            self.mock_time.set_mock_ns(saved_ns)
            expected_state.monotonic_ns = saved_ns
        self._post_dns_failures_check(initial_time)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_no_cache_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP DNS address lookup without previous cached offset.
        (blocking, with notification).
        """
        configuration_scenario = self.MONITORING
        notification_context = "all " + configuration_scenario
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX] * 10)
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS

        expected_state = self._set_and_verify_ntp_state(start)
        initial_time = self._prime_expected_dns_fail_state(expected_state)

        for _ in range(
            10
        ):  # Do enough iterations to get into the maximum rate limiting delay
            self._dns_failure_cycle(expected_state, notification_context)
            if not expected_state.blocking:
                # need to advance time to get past each rate limiting delay
                saved_ns = self.mock_time.get_mock_ns()
                self.mock_time.set_mock_ns(expected_state.limit_end)
                expected_state.monotonic_ns = expected_state.limit_end
        if not expected_state.blocking:
            # Undo the final time advance
            self.mock_time.set_mock_ns(saved_ns)
            expected_state.monotonic_ns = saved_ns
        self._post_dns_failures_check(initial_time)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_no_cache_dns_fail(  # pylint:disable=invalid-name
        self,
    ) -> None:
        """
        Test failing non-blocking NTP DNS address lookup without previous cached offset.
        (non-blocking, no notification).
        """
        notification_context = None
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX] * 10)
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        self._iterate_dns_failure(10, start, notification_context)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_no_cache_dns_fail(  # pylint:disable=invalid-name
        self,
    ) -> None:
        """
        Test failing mon-non-blocking NTP DNS address lookup without previous cached offset.
        (non-blocking, with notification).
        """
        configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "all " + configuration_scenario
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX] * 10)
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.blocking = False
        self._iterate_dns_failure(10, start, notification_context)

    # @ unittest.skip('trace changed pattern')
    def test_rate_limiting_boundaries(self):  # pylint:disable=invalid-name
        """Test rate limiting delay interval boundary conditions."""
        # For context in this test. The actual values are constants used in the called methods
        # that were created to DRY the code.
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        # exception = INCOMPLETE_EX

        # 2 operations should attempt to get address information, because they are past the
        # end of the rate limiting delay interval.
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX] * 2)

        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        start.monotonic_ns = NS_PER_SEC + 3
        start.limit_delay = int(self.DNS_BACKOFF.first * self.DNS_BACKOFF.factor)
        start.limit_end = self.DNS_BACKOFF.first + start.monotonic_ns
        start.state = self.NTP_STATE_MACHINE.GETTING_SOCKET

        self._before_boundary_check(start, start.monotonic_ns)

        # Still in the rate limiting delay period.
        self._before_boundary_check(start, start.limit_end - 3)

        # Should be just past the end of the rate limiting delay.
        self._past_boundary_check(start, start.limit_end - 2)

        # Well past the end of the rate limiting delay.
        self._past_boundary_check(start, start.limit_end + 2000)

        self.assertEqual(
            len(self.mock_pool.mock_getaddrinfo_attempts),
            0,
            "rate limiting boundary checks should have used all of the queued getaddr responses: "
            f"found {len(self.mock_pool.mock_getaddrinfo_attempts)} left.",
        )

    # @ unittest.skip('trace changed pattern')
    def test_legacy_no_cache_get_dns(self):  # pylint:disable=invalid-name
        """
        Test successful legacy DNS address lookup without previous cached offset.
        (blocking, no notification).
        Fail on the immediately attempted NTP packet request.
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        expected_state, expected_log = self._expected_for_any_get_dns(
            DEFAULT_NTP_STATE, None
        )
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_no_cache_get_dns(self):  # pylint:disable=invalid-name
        """
        Test successful monitoring DNS address lookup without previous cached offset.
        (blocking, with notification).
        Fail on the immediately attempted NTP packet request.
        """
        # configuration_scenario = self.MONITORING
        # DNS lookup succeeds, but does not generate any notifications. The Following NTP
        # packet request is set to fail, and that generates a notification.
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, expected_log = self._expected_for_any_get_dns(
            start, notification_context
        )
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_no_cache_get_dns(self):  # pylint:disable=invalid-name
        """
        Test successful non-blocking DNS address lookup without previous cached offset.
        (not blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        expected_state, expected_log = self._expected_for_any_get_dns(start, None)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_no_cache_get_dns(self):  # pylint:disable=invalid-name
        """
        Test successful monitored non-blocking DNS address lookup without previous cached offset.
        (not blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        # No actual notifications are generated for this operation and scenario.
        notification_context = "good " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, expected_log = self._expected_for_any_get_dns(
            start, notification_context
        )
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_legacy_no_cache_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP packet send without previous cached offset.
        (blocking, no notification).

        This should only occur if the network connection drops between getting the DNS
        lookup and sending the NTP packet.
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        expected_state, should_log, _ = self._configure_send_fail(start, None)
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            SENDTO_BROKENPIPE_EX, expected_state, expected_log
        )

        # Should honour retry backoff rate limiting for next attempt (using sleep)
        self._log_handler.log_records.clear()
        should_log, _ = self._configure_send_retry_fail(expected_state, None)
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            SENDTO_BROKENPIPE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_no_cache_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP packet send without previous cached offset.
        (blocking, with notification).

        This should only occur if the network connection drops between getting the DNS
        lookup and sending the NTP packet.
        """
        # configuration_scenario = self.MONITORING
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log, _ = self._configure_send_fail(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            SENDTO_BROKENPIPE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_no_cache_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing non-blocking NTP packet send without previous cached offset.
        (non-blocking, no notification).

        This should only occur if the network connection drops between getting the DNS
        lookup and sending the NTP packet.
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        expected_state, should_log, _ = self._configure_send_fail(start, None)
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_no_cache_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring non-blocking NTP packet send without previous cached offset.
        (non-blocking, with notification).

        This should only occur if the network connection drops between getting the DNS
        lookup and sending the NTP packet.
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "fail " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log, _ = self._configure_send_fail(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_legacy_no_cache_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP packet request without previous cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        expected_state, should_log, _ = self._configure_ntp_fail(start, None)
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_no_cache_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP packet request without previous cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log, _ = self._configure_ntp_fail(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_no_cache_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing non-blocking NTP packet request without previous cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        expected_state, should_log, _ = self._configure_ntp_fail(start, None)
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_no_cache_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring non-blocking NTP packet request without previous cached offset.
        (non-blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "fail " + self.MON_NON_BLOCKING
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log, _ = self._configure_ntp_fail(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )

    # @ unittest.skip('trace changed pattern')
    def test_legacy_no_cache_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful legacy NTP packet request without previous cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        expected_state, should_log = self._configure_good_ntp(start, None)
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_no_cache_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful monitoring NTP packet request without previous cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MONITORING
        start = DEFAULT_NTP_STATE.copy()
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log = self._configure_good_ntp(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_no_cache_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful non-blocking NTP packet request without previous cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        expected_state, should_log = self._configure_good_ntp(start, None)
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_no_cache_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful monitored non-blocking NTP packet request without previous cached offset.
        (non-blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "good " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        start = DEFAULT_NTP_STATE.copy()
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        expected_state, should_log = self._configure_good_ntp(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_utc(self):  # pylint:disable=invalid-name
        """
        Test legacy get utc time with existing cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        self._cached_ntp_operation_and_check_results(start)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_cached_utc(self):  # pylint:disable=invalid-name
        """
        Test monitoring get utc time with existing cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MONITORING
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        self._cached_ntp_operation_and_check_results(start)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_utc(self):  # pylint:disable=invalid-name
        """
        Test non-blocking get utc time with existing cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        self._cached_ntp_operation_and_check_results(start)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_block_cached_utc(self):  # pylint:disable=invalid-name
        """
        Test monitoring get utc time with existing cached offset.
        (non-blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MONITORING
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        self._cached_ntp_operation_and_check_results(start)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP DNS address lookup with existing cached offset.
        (blocking, no notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX])
        self._fallback_dns_fail(start, None)

    # @ unittest.skip('trace changed pattern')
    def test_monitor_cached_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP DNS address lookup with existing cached offset.
        (blocking, with notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MONITORING
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX])
        self._fallback_dns_fail(start, notification_context)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing non-blocking NTP DNS address lookup with existing cached offset.
        (not blocking, no notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX])
        self._fallback_dns_fail(start, None)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_cached_dns_fail(self):  # pylint:disable=invalid-name
        """
        Test failing mon_non-blocking NTP DNS address lookup with existing cached offset.
        (not blocking, with notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MON_NON_BLOCKING
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        test_cb = MockCallback(notification_context)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        self.mock_pool.set_getaddrinfo_responses([GETADDR_DNS_EX])
        self._fallback_dns_fail(start, notification_context)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_get_dns(self):  # pylint:disable=invalid-name
        """
        Test legacy get DNS address lookup with existing cached offset.
        (blocking, no notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.

        Since this is blocking mode, the successful dns lookup immediately continues to
        attempt to get the NTP packet. That is set to fail for this test.
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.monotonic_ns = start.next_sync  # Earliest time that cache will be expired
        expected_state, expected_log = self._expected_for_any_get_dns(start, None)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_cached_get_dns(self):  # pylint:disable=invalid-name
        """
        Test monitoring get DNS address lookup with existing cached offset.
        (blocking, with notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.

        Since this is blocking mode, the successful dns lookup immediately continues to
        attempt to get the NTP packet. That is set to fail for this test.
        """
        # configuration_scenario = self.MONITORING
        # DNS lookup succeeds, but does not generate any notifications. The Following NTP
        # packet request is set to fail, and that generates a notification.
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync  # Earliest time that cache will be expired
        expected_state, expected_log = self._expected_for_any_get_dns(
            start, notification_context
        )
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_get_dns(self):  # pylint:disable=invalid-name
        """
        Test non-blocking get DNS address lookup with existing cached offset.
        (not blocking, no notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.NON_BLOCKING
        # No actual notifications are generated for this operation and scenario.
        notification_context = "good " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync  # Earliest time that cache will be expired
        expected_state, expected_log = self._expected_for_any_get_dns(start, None)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_cached_get_dns(self):  # pylint:disable=invalid-name
        """
        Test monitored non-blocking get DNS address lookup with existing cached offset.
        (not blocking, with notification).

        Base configuration is the same as the cached utc tests, adjusted so that the cached
        offset has expired.
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.monotonic_ns = start.next_sync  # Earliest time that cache will be expired
        expected_state, expected_log = self._expected_for_any_get_dns(start, None)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP packet send with existing cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_send_fail(start, None)
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

        # Should honour retry backoff rate limiting for next attempt (using sleep)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_cached_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP packet send with existing cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_send_fail(
            start, notification_context
        )
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing non-blocking NTP packet send with existing cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_send_fail(start, None)
        # expected_state.monotonic_ns = next_ns
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_cached_send_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring non-blocking NTP packet send with existing cached offset.
        (non-blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "fail " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_send_fail(
            start, notification_context
        )
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing legacy NTP packet request with existing cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_ntp_fail(start, None)
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_cached_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring NTP packet request with existing cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "fail " + self.MONITORING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_ntp_fail(
            start, notification_context
        )
        # if start.monotonic_start_ns > 0:
        #     # When have previous cached offset, use it
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing non-blocking NTP packet request with existing cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_ntp_fail(start, None)
        # if start.monotonic_start_ns > 0:
        #     # When have previous cached offset, use it
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_cached_ntp_fail(self):  # pylint:disable=invalid-name
        """
        Test failing monitoring non-blocking NTP packet request with existing cached offset.
        (non-blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "fail " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.blocking = False
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log, next_ns = self._configure_ntp_fail(
            start, notification_context
        )
        # if start.monotonic_start_ns > 0:
        #     # When have previous cached offset, use it
        next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_legacy_cached_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful legacy NTP packet request with existing cached offset.
        (blocking, no notification).
        """
        # configuration_scenario = self.LEGACY
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log = self._configure_good_ntp(start, None)
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_monitoring_cached_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful monitoring NTP packet request with existing cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MONITORING
        notification_context = "good " + self.MONITORING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log = self._configure_good_ntp(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_non_blocking_cached_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful non-blocking NTP packet request with existing cached offset.
        (non-blocking, no notification).
        """
        # configuration_scenario = self.NON_BLOCKING
        # notification_context = None
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log = self._configure_good_ntp(start, None)
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    # @ unittest.skip('trace changed pattern')
    def test_mon_non_blocking_cached_get_ntp(self):  # pylint:disable=invalid-name
        """
        Test successful monitored non-blocking NTP packet request with existing cached offset.
        (blocking, with notification).
        """
        # configuration_scenario = self.MON_NON_BLOCKING
        notification_context = "good " + self.MON_NON_BLOCKING
        test_cb = MockCallback(notification_context)
        ntp_base_iso = "2024-01-01T09:11:22.456789123"
        start = self._configure_cached_ntp(ntp_base_iso)
        start.blocking = False
        start.callbacks[test_cb.mock_callback] = EventType.ALL_EVENTS
        start.monotonic_ns = start.next_sync + 100  # some time after got dns
        expected_state, should_log = self._configure_good_ntp(
            start, notification_context
        )
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)


# end class TestNTPFunction():


if __name__ == "__main__":
    unittest.main()

mock_cleanup()
