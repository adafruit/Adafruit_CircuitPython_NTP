# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Utilities and other support code for adafruit_ntp unittesting.

This module contains code that requires imports from adafruit_ntp, which means that
the mock time module must be setup first. This can NOT be merged into
shared_for_testing, because that contains code using the real time module.

This probably CAN be merged, by explicitly importing the specific time module attributes
before the override is done.
"""
# pylint:disable=too-many-lines

from collections import namedtuple
from errno import ETIMEDOUT
import os
import sys
import unittest

try:
    from typing import Callable, Optional, Tuple, Dict, List, Set
    from tests.shared_for_testing import LogTupleT
except ImportError:
    pass
from tests.shared_for_testing import (
    ListHandler,
    fmt_thousands,
    mock_info,
    get_context_exception,
    DEFAULT_NTP_ADDRESS,
    NS_PER_SEC,
    MOCKED_CALLBACK_MSG,
    MOCKED_TIME_DEFAULT_START_NS,
    MOCKED_TIME_LOCALTIME_MSG,
    MOCKED_TIME_MONOTONIC_NS_MSG,
    MOCKED_TIME_SLEEP_MSG,
    MOCKED_POOL_GETADDR_MSG,
    MOCKED_POOL_SOCKET_MSG,
    MOCKED_SOCK_NEW_MSG,
    MOCKED_SOCK_INIT_MSG,
    MOCKED_SOCK_ENTER_MSG,
    MOCKED_SOCK_SETTIMEOUT_MSG,
    MOCKED_SOCK_EXIT_MSG,
    MOCKED_SOCK_SENDTO_MSG,
    MOCKED_SOCK_RECV_INTO_MSG,
    NTP_PACKET_SIZE,
    NTP_SERVER_IPV4_ADDRESS,
    ADDR_SOCK_KEY,
    NTP_ADDRESS_PORT,
    GETADDR_DNS_EX,
    IP_SOCKET,
)
from tests.simulate_ntp_packet import create_ntp_packet, iso_to_nanoseconds
from tests.mocks.mock_pool import MockPool  # , MockCallback, MockSocket
from tests.mocks import mock_time
from tests.mocks.mock_time import MockTime

# Set/Replace the time module with the mock version. All requests (imports) of time for the
# rest of the session should get the mock.
sys.modules["time"] = mock_time
# Import the adafruit_ntp module components, which should import the mock versions of modules
# defined (imported) above, unless they are injected on instantiation.
from adafruit_ntp import (  # pylint:disable=wrong-import-position
    NTP,
    EventType,
    _IntFlag,
    NTPIncompleteError,
)  # pylint:disable=wrong-import-position

INCOMPLETE_MSG: str = "No NTP synchronization has been successful yet"
INCOMPLETE_EX = NTPIncompleteError(INCOMPLETE_MSG)
SENDTO_BROKENPIPE_EX = BrokenPipeError(32)
try:
    RECV_INTO_TIMEDOUT_EX = OSError(ETIMEDOUT, os.strerror(ETIMEDOUT))
except AttributeError:
    # CircuitPython does not have os.strerror
    RECV_INTO_TIMEDOUT_EX = OSError(ETIMEDOUT, "ETIMEDOUT")

NTPStateMachine = namedtuple(
    "NTPStateMachine", ("GETTING_SOCKET", "GETTING_PACKET", "USING_CACHED")
)
BackoffConfig = namedtuple("BackoffConfig", ("first", "maximum", "factor"))

NTPSTATE_FIELDS = {
    "packet",
    "port",
    "server",
    "socket_address",
    "tz_offset_ns",
    "socket_timeout",
    "cache_ns",
    "monotonic_start_ns",
    "next_sync",
    "last_sync_time",
    "callbacks",
    "state",
    "blocking",
    "monotonic_ns",
    "limit_end",
    "limit_delay",
}


class NTPState:  # pylint:disable=too-many-instance-attributes
    """Storage for internal NTP instance state information"""

    def __init__(
        self,
        *,  # pylint:disable=too-many-arguments,too-many-locals
        server: str = "",
        port: int = 123,
        socket_address: Optional[Tuple[str, int]] = None,
        packet: bytearray = None,
        tz_offset_ns: int = 0,
        socket_timeout: int = 10,
        cache_ns: int = 0,
        monotonic_start_ns: int = 0,
        next_sync: int = 0,
        last_sync_time: int = 0,
        callbacks: Dict[Callable[[_IntFlag, int], None], _IntFlag] = None,
        state: int = 0,
        blocking: bool = True,
        monotonic_ns: int = 0,  # mocked functionality internal state information
        limit_end: int = 0,
        limit_delay: int = 0,
    ):
        # NTP instance internal state information
        self.server: str = server
        self.port: int = port
        self.socket_address: Optional[Tuple[str, int]] = socket_address
        self.packet: bytearray = bytearray(packet) if packet else packet
        self.tz_offset_ns: int = tz_offset_ns
        self.socket_timeout: int = socket_timeout
        self.cache_ns: int = cache_ns
        self.monotonic_start_ns: int = monotonic_start_ns
        self.next_sync: int = next_sync
        self.last_sync_time: int = last_sync_time
        self.callbacks: Dict[Callable[[_IntFlag, int], None], _IntFlag] = (
            {} if callbacks is None else dict(callbacks)
        )
        self.state: int = state
        self.blocking: bool = blocking
        # mocked functionality internal state information : time
        self.monotonic_ns: int = monotonic_ns
        self.limit_end: int = limit_end
        self.limit_delay: int = limit_delay
        # mocked functionality internal state information : socket
        # used and discarded. No state or socket reference kept.
        # mocked functionality internal state information : pool
        # no state information used.

    def copy(self) -> "NTPState":
        """Create a deep copy of the current instance."""
        # Create a new instance of the class
        duplicate_state = NTPState()
        # Copy the (data) attributes from the original instance
        simple_fields = NTPSTATE_FIELDS - {"packet", "callbacks"}
        for field in simple_fields:
            setattr(duplicate_state, field, getattr(self, field))
        # Need to create a copy of the packet and callbacks, not just get a shared reference
        duplicate_state.packet = None if self.packet is None else bytearray(self.packet)
        duplicate_state.callbacks.update(self.callbacks)

        return duplicate_state


DEFAULT_NTP_STATE = NTPState(
    server=DEFAULT_NTP_ADDRESS[0],
    port=DEFAULT_NTP_ADDRESS[1],
    socket_address=None,
    packet=bytearray((0,) * NTP_PACKET_SIZE),
    tz_offset_ns=0,
    socket_timeout=10,
    cache_ns=60 * NS_PER_SEC,
    monotonic_start_ns=0,
    next_sync=0,
    last_sync_time=0,
    callbacks={},
    state=NTP.USING_CACHED_REFERENCE,
    blocking=True,
    monotonic_ns=MOCKED_TIME_DEFAULT_START_NS,
    limit_end=None,
    limit_delay=None,
)


class BaseNTPTest(unittest.TestCase):
    """Base class for NTP unittesting."""

    # attributes to be initialized by child classes
    _log_handler: ListHandler = None
    ntp: NTP = None
    mock_time: MockTime = None
    mock_pool: MockPool = None
    mock_socket: MockPool.socket = None
    # Constants
    DNS_BACKOFF = BackoffConfig(int(3 * NS_PER_SEC), int(60 * NS_PER_SEC), 1.5)
    NTP_STATE_MACHINE = NTPStateMachine(
        NTP.GETTING_SOCKET, NTP.GETTING_PACKET, NTP.USING_CACHED_REFERENCE
    )

    def _set_and_verify_ntp_state(self, target_state: NTPState) -> NTPState:
        """Set the NTP instance to a known state, and verify that it got set."""
        set_ntp_state(target_state, self.ntp)
        actual_state = get_ntp_state(self.ntp)
        unmatched = match_expected_field_values(target_state, actual_state)
        self.assertEqual(
            unmatched, set(), f"NTP state fields {unmatched} do not match intended"
        )
        return actual_state

    def _iterate_dns_failure(
        self, count: int, start: NTPState, notify: Optional[str]
    ) -> None:
        """
        Iterate DNS failure checks with exponential backoff retry checks.

        :param int count: Number of times to iterate the DNS failure.
        :param NTPState start: Base NTP state for the test scenario mode.
        :param Optional[str] notify: Notification context for the test.
        """
        expected_state = self._set_and_verify_ntp_state(start)
        initial_time = self._prime_expected_dns_fail_state(expected_state)
        for _ in range(
            count
        ):  # Do enough iterations to get into the maximum rate limiting delay
            self._dns_failure_cycle(expected_state, notify)
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

    def _configure_send_fail(
        self, start: NTPState, notify: Optional[str]
    ) -> Tuple[NTPState, List[LogTupleT], int]:
        """
        Do the common configuration for an NTP send failure test.

        :param NTPState start: Base NTP state for the test scenario mode.
        :param Optional[str] notify: Notification context for the test.
        """
        # This is an unusual state for legacy mode. The only way that this should be possible
        # (initially) is for the network connection to drop after the successful DNS lookup,
        # but before sending the NTP packet. On following NTP cache timeouts, this can occur
        # because the DNS cache can return a valid looking socket even though the connection
        # is down.
        start.state = self.NTP_STATE_MACHINE.GETTING_PACKET
        start.socket_address = NTP_ADDRESS_PORT
        start.limit_delay = self.DNS_BACKOFF.first
        start.limit_end = 0

        self.mock_socket.set_sendto_responses([SENDTO_BROKENPIPE_EX])
        self.mock_socket.mock_recv_into_attempts.clear()  # Should not get far enough to need.
        send_packet: bytearray = create_ntp_packet(mode=3)  # client
        send_packet[1:] = bytearray(len(send_packet) - 1)  # fill with zeros after mode

        expected_state = self._set_and_verify_ntp_state(start)
        expected_state.state = self.NTP_STATE_MACHINE.GETTING_SOCKET
        expected_state.packet[:] = send_packet
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        next_ns = logged_for_send_fail(should_log, next_ns, expected_state, notify)
        expected_state.monotonic_ns = next_ns - 1
        expected_state.limit_end = (
            expected_state.monotonic_ns + expected_state.limit_delay
        )
        expected_state.limit_delay = min(
            self.DNS_BACKOFF.maximum,
            int(expected_state.limit_delay * self.DNS_BACKOFF.factor),
        )
        return expected_state, should_log, next_ns

    def _configure_send_retry_fail(
        self, expected_state: NTPState, notify: Optional[str]
    ) -> Tuple[List[LogTupleT]]:
        """
        Do the common configuration for an NTP send retry failure test.

        :param NTPState expected_state: NTP state from the previous attempt for the test
                scenario mode.
        :param Optional[str] notify: Notification context for the test.
        """
        self.mock_pool.set_getaddrinfo_responses([IP_SOCKET])
        self.mock_socket.set_sendto_responses([SENDTO_BROKENPIPE_EX])
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        save_ns = next_ns  # DEBUG
        next_ns = logged_for_get_address(
            should_log, next_ns, expected_state, expected_state.limit_end, notify
        )
        print(f"retry fail: {save_ns =}, {next_ns =}")
        next_ns = logged_for_send_fail(should_log, next_ns, expected_state, notify)
        expected_state.monotonic_ns = next_ns - 1
        expected_state.limit_end = (
            expected_state.monotonic_ns + expected_state.limit_delay
        )
        expected_state.limit_delay = min(
            self.DNS_BACKOFF.maximum,
            int(expected_state.limit_delay * self.DNS_BACKOFF.factor),
        )
        return should_log, next_ns

    def _configure_ntp_fail(
        self, start: NTPState, notify: Optional[str]
    ) -> Tuple[NTPState, List[LogTupleT], int]:
        """
        Do the common configuration for an NTP receive failure test.

        :param NTPState start: Base NTP state for the test scenario mode.
        :param Optional[str] notify: Notification context for the test.
        """
        # This is an unusual state for legacy mode. Only way to get here seems to be to start
        # in non-blocking mode, then change to blocking after the DNS lookup is finished.
        start.state = self.NTP_STATE_MACHINE.GETTING_PACKET
        start.socket_address = NTP_ADDRESS_PORT
        start.limit_delay = self.DNS_BACKOFF.first  # Shouldn't really matter
        start.limit_end = 0  # Shouldn't really matter

        self.mock_socket.set_sendto_responses([NTP_PACKET_SIZE])
        self.mock_socket.set_recv_into_responses([RECV_INTO_TIMEDOUT_EX])
        send_packet: bytearray = create_ntp_packet(mode=3)  # client
        send_packet[1:] = bytearray(len(send_packet) - 1)  # fill with zeros after mode

        expected_state = self._set_and_verify_ntp_state(start)
        expected_state.state = self.NTP_STATE_MACHINE.USING_CACHED
        expected_state.packet[:] = send_packet
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        expected_state.monotonic_ns = next_ns + 1
        expected_state.next_sync = expected_state.cache_ns + expected_state.monotonic_ns
        next_ns = logged_for_ntp_packet(should_log, next_ns, expected_state, notify)
        return expected_state, should_log, next_ns

    def _configure_good_ntp(
        self, start: NTPState, notify: Optional[str]
    ) -> Tuple[NTPState, List[LogTupleT]]:
        """
        Do the common configuration for a successful NTP test.

        - Adjust the starting state to match what is needed to have the NTP instance attempt
          to get an NTP packet from the server. That means being in the correct state, and
          having a good socket.
        - Set the mock so the request will get a good (test) ntp packet.
        - Populate what the instance state and log should contain after the request.

        :param NTPState start: Base NTP state for the test scenario mode.
        :param Optional[str] notify: Notification context for the test.
        """
        # This is an unusual state for blocking mode. The only way to get here seems to be to
        # start in non-blocking mode, then change to blocking after the DNS lookup is finished.
        start.state = self.NTP_STATE_MACHINE.GETTING_PACKET
        start.socket_address = NTP_ADDRESS_PORT
        start.limit_delay = self.DNS_BACKOFF.first  # Shouldn't really matter
        start.limit_end = 0  # Shouldn't really matter

        ntp_base_iso = "2024-01-01T10:11:12.987654321"
        ntp_receive_delta, ntp_transmit_delta, good_receive_packet = (
            create_ntp_packet_for_iso(ntp_base_iso)
        )
        # Queue a good NTP packet for the mock to supply when requested.
        self.mock_socket.set_sendto_responses([NTP_PACKET_SIZE])
        self.mock_socket.set_recv_into_responses([good_receive_packet])
        # Push the adjusted starting state information to the test instance: base expected state
        expected_state = self._set_and_verify_ntp_state(start)
        expected_state.state = self.NTP_STATE_MACHINE.USING_CACHED
        expected_state.packet[:] = good_receive_packet
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        expected_state.monotonic_ns = next_ns + 2
        expected_state.last_sync_time = expected_state.monotonic_ns - 1
        expected_state.next_sync = (
            expected_state.cache_ns + expected_state.last_sync_time
        )
        expected_state.monotonic_start_ns = (
            iso_to_nanoseconds(ntp_base_iso)
            + ntp_receive_delta
            + ntp_transmit_delta // 2
            - expected_state.last_sync_time
            - 1
        )
        next_ns = logged_for_ntp_packet(should_log, next_ns, expected_state, notify)
        logged_for_time_reference(should_log, next_ns, False)
        return expected_state, should_log

    def _configure_cached_ntp(self, iso_time: str) -> NTPState:
        """
        Create an NTP state configuration for an already synchronized scenario.

        :param str iso_time: The time to use for the cached synchronization offset.
        :return: NTPState: The configured NTP state.
        """
        start = DEFAULT_NTP_STATE.copy()
        start.monotonic_start_ns = iso_to_nanoseconds(iso_time)
        start.state = self.NTP_STATE_MACHINE.USING_CACHED

        start.last_sync_time = NS_PER_SEC + 1000
        ntp_receive_delta, ntp_transmit_delta, good_receive_packet = (
            create_ntp_packet_for_iso(iso_time)
        )
        start.packet[:] = good_receive_packet
        start.next_sync = start.cache_ns + start.last_sync_time
        start.monotonic_start_ns = (
            iso_to_nanoseconds(iso_time)
            + ntp_receive_delta
            + ntp_transmit_delta // 2
            - start.last_sync_time
            - 1
        )
        return start

    def _cached_ntp_operation_and_check_results(self, start: NTPState) -> None:
        """
        Check the result when should be using cached NTP synchronization offset.

        :param NTPState start: The initial NTP state.
        :return: None
        """
        expected_state = self._set_and_verify_ntp_state(start)
        self.mock_time.set_mock_ns(expected_state.last_sync_time)
        # self.mock_time.set_mock_ns(expected_state.next_sync - 2)  # upto .next_sync - 2
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)

    def _good_ntp_operation_and_check_result(
        self, expected_state: NTPState, expected_log: Tuple[LogTupleT]
    ) -> None:
        """
        Perform an NTP time request (successful) operation for the configured state and check the
        result.

        :param NTPState expected: Expected NTP state after the operation attempt.
        :param Tuple[LogTupleT] expected_log: Expected log records from the operation.
        :return: None
        """
        time_ns = self.ntp.utc_ns
        expected_ns = expected_state.monotonic_start_ns + expected_state.monotonic_ns
        self.assertEqual(
            time_ns,
            expected_ns,
            "Expected nanoseconds value of "
            f"{expected_ns:,}, but got {time_ns:,}, delta = {expected_ns - time_ns}",
        )
        self._verify_expected_operation_state_and_log(expected_state, expected_log)

    def _verify_expected_operation_state_and_log(
        self, expected_state: NTPState, expected_log: Tuple[LogTupleT]
    ) -> None:
        """
        Common state and log verification for NTP operation results.

        :param NTPState expected_state: The expected NTP state after the operation attempt.
        :param Tuple[LogTupleT] expected_log: Expected log records from the operation.
        :return: None
        """
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            expected_log,
            "NTP state fields %s do not match expected for NTP operation",
            "Configured NTP operation log records should be:\n%s; actually got:\n%s",
        )

    def _fail_ntp_operation_and_check_result(
        self,
        exception: Exception,
        expected_state: NTPState,
        expected_log: Tuple[LogTupleT],
    ) -> None:
        """
        Perform an NTP time request (failing) operation for the configured state and check the
        result.

        :param Exception exception: Specific exception that is expected.
        :param NTPState expected: Expected NTP state after the operation attempt.
        :param Tuple[LogTupleT] expected_log: Expected log records from the operation.
        :return: None
        """
        with self.assertRaises(type(exception)) as context:
            time_ns = self.ntp.utc_ns
            raise AssertionError(
                f"Should have raised {type(exception)}, got {fmt_thousands(time_ns)}"
            )
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(exception))
        self._verify_expected_operation_state_and_log(expected_state, expected_log)

    def _bound_check_result_verification(
        self, expected_state: NTPState, should_log: List[LogTupleT]
    ) -> None:
        """
        Common result verification for rate limiting delay interval boundary checks.

        :param NTPState expected: The expected NTP state after the test.
        :param List[LogTupleT] should_log: The expected generated log records.
        """
        expected_log = tuple(should_log)
        self._fail_ntp_operation_and_check_result(
            INCOMPLETE_EX, expected_state, expected_log
        )
        self._log_handler.log_records.clear()

    def _before_boundary_check(self, start: NTPState, start_time_point: int) -> None:
        """
        Check the result when should be before the end of the rate limiting delay interval.

        :param NTPState start: The initial NTP state.
        :param int start_time_point: The time point at the start of the test.
        """
        expected_state = self._set_and_verify_ntp_state(start)
        self.mock_time.set_mock_ns(start_time_point)
        should_log: List[LogTupleT] = []
        expected_state.monotonic_ns = start_time_point + 2
        next_ns = logged_for_time_request(should_log)
        logged_for_rate_limit_skip(should_log, next_ns)
        self._bound_check_result_verification(expected_state, should_log)

    def _past_boundary_check(self, start: NTPState, start_time_point: int) -> None:
        """
        Check the result when should be past the rate limiting delay interval.

        :param NTPState start: The initial NTP state.
        :param int start_time_point: The time point at the start of the test.
        """
        expected_state = self._set_and_verify_ntp_state(start)
        self.mock_time.set_mock_ns(start_time_point)
        should_log: List[LogTupleT] = []
        expected_state.monotonic_ns = start_time_point + 3
        expected_state.limit_end = (
            expected_state.monotonic_ns + expected_state.limit_delay
        )
        expected_state.limit_delay = int(
            expected_state.limit_delay * self.DNS_BACKOFF.factor
        )
        next_ns = logged_for_time_request(should_log)
        logged_for_get_address(
            should_log, next_ns, expected_state, start.limit_end, None
        )
        self._bound_check_result_verification(expected_state, should_log)

    def _prime_expected_dns_fail_state(self, expected_state: NTPState) -> int:
        """
        Initialize the expected NTP state to match a dummy previous DNS fail cycle.

        This sets the expected state to values that the initial _dns_failure_state 'step' update
        will advance to the correct starting expected state for the first cycle of the DNS
        failure case tests.

        :param NTPState expected: Base expected NTP state for the test scenario.
        """
        expected_state.monotonic_ns = self.mock_time.get_mock_ns()
        expected_state.state = self.NTP_STATE_MACHINE.GETTING_SOCKET
        expected_state.limit_delay = self.DNS_BACKOFF.first
        expected_state.limit_end = expected_state.monotonic_ns + 2
        return expected_state.monotonic_ns

    def _dns_failure_state(self, expected_state: NTPState) -> None:
        """
        Update expected ntp instance state for next dns lookup and failure.

        :param NTPState expected: The ntp instance state before attempt the dns lookup.
        """
        # additional (non-state) test case scenario setup
        self._log_handler.log_records.clear()
        # expected ntp instance state changes
        sleep_ns = 0
        if expected_state.blocking:
            sleep_s = (
                expected_state.limit_end - expected_state.monotonic_ns - 2
            ) / NS_PER_SEC
            sleep_ns = int(sleep_s * NS_PER_SEC)
        if (
            expected_state.blocking
            or expected_state.monotonic_ns + 3 > expected_state.limit_end
        ):
            # actual dns lookup attempt will be made
            expected_state.monotonic_ns = expected_state.monotonic_ns + 3 + sleep_ns
            expected_state.limit_end = (
                expected_state.monotonic_ns + expected_state.limit_delay
            )
            expected_state.limit_delay = min(
                self.DNS_BACKOFF.maximum,
                int(expected_state.limit_delay * self.DNS_BACKOFF.factor),
            )
        else:  # early incomplete exit during rate limiting wait
            # limit values do not change in the middle of a rate limiting delay
            expected_state.monotonic_ns = expected_state.monotonic_ns + 2

    def _dns_failure_cycle(
        self, expected_state: NTPState, notify: Optional[str]
    ) -> None:
        """
        Set up and execute next dns lookup and failure.

        Input expected_state is from the previous cycle, so is the starting state for the
        next cycle. Updated in place instead of duplicated.

        :param NTPState expected_state: The ntp instance state before the dns lookup attempt.
        :param Optional[str] notify: The name of the notification context being used.
        """
        previous_end = (
            0
            if expected_state.limit_delay == self.DNS_BACKOFF.first
            else expected_state.limit_end
        )
        self._dns_failure_state(expected_state)
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        logged_for_get_address(
            should_log, next_ns, expected_state, previous_end, notify
        )
        expected_log = tuple(should_log)
        exception = GETADDR_DNS_EX if expected_state.blocking else INCOMPLETE_EX
        self._fail_ntp_operation_and_check_result(
            exception, expected_state, expected_log
        )

    def _post_dns_failures_check(self, cycle_start: int) -> None:
        """
        Verification done after a sequence of dns lookup attempts that all fail.

        Test conditions are dependent on the number of cycles (attempts), and on the rate limiting
        backoff configuration (self.DNS_BACKOFF)

        :param int cycle_start: The mock monotonic nanoseconds time point that the sequence is
            started.
        """
        # pylint:disable=protected-access
        self.assertEqual(
            self.ntp._next_rate_limit_delay,
            self.DNS_BACKOFF.maximum,
            "Should have reached the maximum retry delay of "
            f"{self.DNS_BACKOFF.maximum}: currently at {self.ntp._next_rate_limit_delay}",
        )
        minimum_elapsed = 200  # seconds
        min_ns = NS_PER_SEC * minimum_elapsed + cycle_start
        now = self.mock_time.get_mock_ns()
        self.assertTrue(
            now > min_ns,
            "Should have used at least "
            f"{minimum_elapsed} seconds: elapsed {now - cycle_start:,} nanoseconds",
        )

    def _expected_for_any_get_dns(
        self, start: NTPState, notify: Optional[str]
    ) -> Tuple[NTPState, Tuple[LogTupleT]]:
        """
        Common expected state and log configuration for successful DNS lookup.

        When in blocking more, a successful DNS lookup continues to do a NTP packet request. That
        means the expected result and logging have additional changes.

        :param NTPState start: The initial NTP state.
        :param Optional[str] notify: The notification context or None
        :returns Tuple[NTPState, int, List[LogTupleT]]: The calculated state, ending nanosecond,
            and the expected log records.
        """
        self.mock_pool.set_getaddrinfo_responses(
            [
                IP_SOCKET,
            ]
        )
        expected_state = self._set_and_verify_ntp_state(start)
        expected_state.socket_address = NTP_ADDRESS_PORT
        expected_state.limit_delay = self.DNS_BACKOFF.first
        expected_state.limit_end = 0
        if start.blocking:
            # Attempts to get NTP packet right after getting DNS
            self.mock_socket.set_sendto_responses([NTP_PACKET_SIZE])
            self.mock_socket.set_recv_into_responses([RECV_INTO_TIMEDOUT_EX])
            send_packet: bytearray = create_ntp_packet(mode=3)  # client
            send_packet[1:] = bytearray(
                len(send_packet) - 1
            )  # fill with zeros after mode
            expected_state.packet[:] = send_packet

        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        start_end = 0 if start.limit_end is None else start.limit_end
        next_ns = logged_for_get_address(
            should_log, next_ns, expected_state, start_end, notify
        )
        if start.blocking:
            expected_state.next_sync = expected_state.cache_ns + next_ns + 1
            expected_state.state = self.NTP_STATE_MACHINE.USING_CACHED  # no change
            next_ns = logged_for_ntp_packet(should_log, next_ns, expected_state, notify)
        else:
            expected_state.state = self.NTP_STATE_MACHINE.GETTING_PACKET

        if start.monotonic_start_ns > 0:
            # When have previous cached offset, use it
            next_ns = logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns - 1
        expected_log = tuple(should_log)
        return expected_state, expected_log

    def _fallback_dns_fail(self, start: NTPState, notify: Optional[str]) -> None:
        """
        Common testing for failing DNS lookup attempts when a cached offset already exists.

        :param NTPState start: The initial NTP state.
        :param Optional[str] notify: The notification context or None
        :return: None
        """
        start.monotonic_ns = start.next_sync  # Earliest time that cache will be expired
        expected_state = self._set_and_verify_ntp_state(start)
        expected_state.state = self.NTP_STATE_MACHINE.GETTING_SOCKET
        previous_delay = (
            self.DNS_BACKOFF.first if start.limit_delay is None else start.limit_delay
        )
        expected_state.limit_delay = int(previous_delay * self.DNS_BACKOFF.factor)
        should_log: List[LogTupleT] = []
        next_ns = logged_for_time_request(should_log)
        expected_state.limit_end = self.DNS_BACKOFF.first + next_ns + 1
        start_end = 0 if start.limit_end is None else start.limit_end
        next_ns = logged_for_get_address(
            should_log, next_ns, expected_state, start_end, notify
        )

        logged_for_time_reference(should_log, next_ns, False)
        expected_state.monotonic_ns = next_ns
        expected_log = tuple(should_log)
        self._good_ntp_operation_and_check_result(expected_state, expected_log)


def get_ntp_state(ntp: NTP) -> NTPState:
    """
    Extract the current state of the given NTP instance into an NTPState dataclass.

    The NTP instance state includes state from the (mocked) instance it uses.

    :param ntp: NTP: The NTP instance whose state is to be extracted.
    :return: NTPState: A dataclass instance representing the current state of the NTP instance.
    """
    # pylint:disable=protected-access
    limit_delay = getattr(ntp, "_next_rate_limit_delay", None)
    limit_end = getattr(ntp, "_next_rate_limit_end", None)
    return NTPState(
        server=ntp._server,
        port=ntp._port,
        socket_address=ntp._socket_address,
        packet=bytearray(ntp._packet),
        tz_offset_ns=ntp._tz_offset_ns,
        socket_timeout=ntp._socket_timeout,
        cache_ns=ntp._cache_ns,
        monotonic_start_ns=ntp._monotonic_start_ns,
        next_sync=ntp._next_sync,
        last_sync_time=ntp._last_sync_time,
        callbacks=dict(ntp._callbacks),
        state=ntp._state,
        blocking=ntp._blocking,
        limit_delay=limit_delay,
        limit_end=limit_end,
        monotonic_ns=MockTime.get_mock_instance().get_mock_ns(),
    )


def set_ntp_state(state: NTPState, ntp: NTP) -> None:
    """
    Set the state of the given NTP instance from an NTPState dataclass.

    The NTP instance state includes state from the (mocked) instance it uses.

    :param state: NTPState: A dataclass instance representing the state to be restored to the NTP
        instance.
    :param ntp: NTP: The NTP instance whose state is to be set.
    :return: None
    """
    # pylint:disable=protected-access
    ntp._server = state.server
    ntp._port = state.port
    ntp._socket_address = state.socket_address
    ntp._packet[:] = state.packet
    ntp._tz_offset_ns = state.tz_offset_ns
    ntp._socket_timeout = state.socket_timeout
    ntp._cache_ns = state.cache_ns
    ntp._monotonic_start_ns = state.monotonic_start_ns
    ntp._next_sync = state.next_sync
    ntp._last_sync_time = state.last_sync_time
    ntp._callbacks.clear()
    ntp._callbacks.update(state.callbacks)
    ntp._state = state.state
    ntp._blocking = state.blocking
    ntp._next_rate_limit_delay = state.limit_delay
    ntp._next_rate_limit_end = state.limit_end
    MockTime.get_mock_instance().set_mock_ns(state.monotonic_ns)


def create_ntp_packet_for_iso(iso_time: str) -> Tuple[int, int, bytearray]:
    """
    Create an NTP packet as received from an NTP server.

    :param str iso_time: The UTC time to use as a reference point on the server.
    :returns Tuple[int, int, bytearray]:
        Offset from iso_time in nanoseconds used for the received (from client) timestamp.
        Offset from iso_time in nanoseconds used for the transmitted (from server) timestamp.
        NTP packet
    """
    ntp_receive_delta = (
        10_012_345_678  # 10 seconds + adjust to get all 9's ns from 987654321
    )
    ntp_transmit_delta = 500_000_002  # just over half a second
    good_receive_packet = create_ntp_packet(
        iso=iso_time,
        leap=0,
        mode=4,  # Server
        stratum=3,
        poll=7,
        precision=-9,
        root_delay=1_543_210_987,
        root_dispersion=567_432,
        ipv4=NTP_SERVER_IPV4_ADDRESS,
        ref_delta=0,  # keep at zero, to calculations using delta values work
        receive_delta=ntp_receive_delta,
        transmit_delay=ntp_transmit_delta,
    )
    return ntp_receive_delta, ntp_transmit_delta, good_receive_packet


def _changed_state_fields(
    state1: NTPState, state2: NTPState, fields: Optional[Set[str]] = None
) -> Set[str]:
    """
    Compare two NTPState instances and return the names of the attributes that are different.

    :param state1: NTPState: The first NTPState instance.
    :param state2: NTPState: The second NTPState instance.
    :param fields: Optional[Set[str]]: A set of attribute names to check for changes. If None,
                    compare all attributes.
    :return: Set[str]: A set of attribute names that have different values between the two states.
    :raises AttributeError: If a specified field name does not exist in NTPState.
    """
    if fields is not None:
        # Ensure that all provided field names are valid attributes of NTPState
        invalid_fields = fields - NTPSTATE_FIELDS
        if invalid_fields:
            raise AttributeError(
                f"Invalid NTPState field names: {', '.join(invalid_fields)}"
            )

    fields = NTPSTATE_FIELDS if fields is None else fields
    callbacks_field = {"callbacks"}
    changed_fields = set()

    for field in fields - callbacks_field:
        if getattr(state1, field) != getattr(state2, field):
            changed_fields.add(field)

    for field in fields & callbacks_field:
        # Need to handle the callbacks dict separately. The way that python generates id values
        # for (at least) callable objects means that a direct compare of dictionaries fails. The
        # 'duplicate' Callable references are not equal, even though they refer to the same object
        # in memory.
        # All attempts to find a data structure and comparison code to match expected and actual
        # state dictionary callable instance have failed. An expected entry created from exactly
        # the same method as was registered still compares as not equal. The best can apparently
        # be done, is to make sure that the registered event masks are the same.
        callback1 = getattr(state1, field)
        callback2 = getattr(state2, field)
        # Forcing all values to IntFlag instances seems easier than extracting the .value when the
        # dict value is an IntFlag. Need to get them to be consistent for the sorting (on
        # circuitpython) to work. Otherwise can get.
        #     TypeError: unsupported types for __lt__: 'int', 'IntFlag'
        # Either cpython automatically reverse the comparison, or it happens to only compare IntFlag
        # to int, and not int to IntFlag.
        if sorted([_IntFlag(v) for v in callback1.values()]) != sorted(
            [_IntFlag(v) for v in callback2.values()]
        ):
            changed_fields.add(field)

    return changed_fields


def match_expected_field_values(
    expected_state: NTPState, actual_state: NTPState, fields: Optional[Set[str]] = None
) -> Set[str]:
    """
    Compare all or selected fields of state information

    :param expected_state: NTPState: The expected NTP instance state.
    :param actual_state: NTPState: The actual NTP instance state.
    :param fields: Optional[Set[str]]: A set of attribute names to check for changes. If None,
                    compare all attributes.
    :return: Set[str]: A set of attribute names that have different values between the two states.
    :raises AttributeError: If a specified field name does not exist in NTPState.
    """
    dict_fields = {"callbacks"}
    unmatched = _changed_state_fields(expected_state, actual_state, fields)
    for field in unmatched:
        if field in dict_fields:
            expected_dict = getattr(expected_state, field)
            state_dict = getattr(actual_state, field)
            # keys could be different, but values should be the same, though order could change
            print(f"NTP state.{field} expected:")
            for key, value in expected_dict.items():
                print(f' "{str(key)}": {value})')
            print(f"NTP state.{field} actual:")
            for key, value in state_dict.items():
                print(f' "{str(key)}": {value})')
            continue
        print(
            f'NTP state.{field} expected "{getattr(expected_state, field)}", '
            + f'found "{getattr(actual_state, field)}"'
        )
    return unmatched


def verify_generic_expected_state_and_log(  # pylint:disable=invalid-name
    case: BaseNTPTest,
    expected_state: NTPState,  # pylint:disable=invalid-name
    expected_log: Tuple[LogTupleT],
    unmatched_message: str,
    log_message: str,
) -> None:
    """
    Common state and log verification for NTP tests.

    :param NTPState expected_state: The expected NTP state after the operation attempt.
    :param Tuple[LogTupleT] expected_log: Expected log records from the operation.
    :param str unmatched_message: Message format for unmatched state fields.
    :param str log_message: Message format for expected and actual log records.
    :return: None
    """
    unmatched = match_expected_field_values(expected_state, get_ntp_state(case.ntp))
    case.assertEqual(unmatched, set(), unmatched_message % unmatched)

    actual_log = case._log_handler.to_tuple()  # pylint:disable=protected-access
    log_args = (expected_log, actual_log) if expected_log else (actual_log,)
    case.assertEqual(actual_log, expected_log, log_message % log_args)


# Some helper methods to build a tuple of expected log records generated by (NTP instance)
# calls to the various mocked methods. This will be compared with what is collected by
# the logger (mogger). The helpers append expected log records to a supplied list, so the
# final step will be to convert the list to a tuple to compare with _log_handler.to_tuple().
# Populate any needed mock configuration response buffers before generating the expected
# log records. Some of the helper methods access the buffers to decide which log records
# should be expected.


def logged_for_time_request(log_records: List[LogTupleT]) -> int:
    """
    Create the log records expected when requesting a time reference.

    Requesting the current time with the utc_ns or datetime property always starts with a
    single request to «mock» monotonic_ns(). From there, multiple conditional branches
    can occur. After that, if an offset exists, another monotonic_ns call is done to get
    the actual time reference to use. Adding the log records for that is handled separately.

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param int time_reference: The time reference value to log.
    :return: The incremented time reference, which is the next mock time reference
    """
    start_ns = MockTime.get_mock_instance().get_mock_ns() + 1
    log_records.append(mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(start_ns)))
    return start_ns + 1


def logged_for_time_reference(
    log_records: List[LogTupleT], time_reference: int, localtime: bool
) -> int:
    """
    Create the log records expected when getting a time reference.

    This is the log records expected when an offset exists after whatever branching logic
    is used. This path is followed when the offset is known, whether the cached offset
    has expired or not.

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param int time_reference: The time reference value to log.
    :param bool localtime: True when the local time is being requested.
    :return: The incremented time reference, which is the next mock time reference
    """
    log_records.append(
        mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference))
    )
    if localtime:
        log_records.append(
            mock_info(MOCKED_TIME_LOCALTIME_MSG, time_reference // NS_PER_SEC)
        )
    return time_reference + 1


def logged_for_get_address(
    log_records: List[LogTupleT],
    time_reference: int,
    expected_state: NTPState,
    wait_end: int,
    notify: Optional[str],
) -> int:
    """
    Create the log records expected on an execution path that includes a get socket operation.

    This does not include a get socket request that is skipped during a non-blocking rate
    limiting delay.

    REMINDER: Load any needed mock_getaddrinfo_attempts before generating the expected log
        records, and execute the test code afterwards

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param NTPState expected: The ntp instance state expected after the get socket operation.
    :param int time_reference: The time reference at the start of the get socket request.
    :param int wait_end: The time when the rate limiting delay ends.
    :param Optional[str] notify: The context used when a notification is being generated.
    :return: The incremented time reference, which is the next mock time reference
    """
    log_records.append(
        mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference))
    )
    sleep_ns = 0
    if expected_state.blocking and wait_end > time_reference:
        # blocking mode sleeps until the end of the configured delay period.
        sleep_seconds = (wait_end - time_reference) / NS_PER_SEC
        sleep_ns = int(sleep_seconds * NS_PER_SEC)
        log_records.append(mock_info(MOCKED_TIME_SLEEP_MSG, sleep_seconds))
    log_records.append(
        mock_info(
            MOCKED_POOL_GETADDR_MSG, (expected_state.server, expected_state.port)
        ),
    )
    if not isinstance(
        MockPool.get_mock_instance().mock_getaddrinfo_attempts[0], Exception
    ):
        return time_reference + sleep_ns + 1
    # If the attempt will fail, a new monotonic_ns call is made to adjust the rate limiting.
    log_records.append(
        mock_info(
            MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference + sleep_ns + 1)
        )
    )
    if notify:
        log_records.append(
            mock_info(
                MOCKED_CALLBACK_MSG
                % (notify, EventType.LOOKUP_FAILED, expected_state.limit_end)
            )
        )
    return time_reference + sleep_ns + 2


def logged_for_rate_limit_skip(
    log_records: List[LogTupleT], time_reference: int
) -> int:
    """
    Create the log records expected when when processing skipped due to rate limiting.

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param int time_reference: The time reference value to log.
    :return: The incremented time reference, which is the next mock time reference
    """
    log_records.append(
        mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference))
    )
    return time_reference + 1


def logged_for_send_fail(
    log_records: List[LogTupleT],
    time_reference: int,
    expected_state: NTPState,
    notify: Optional[str],
) -> int:
    """
    Create the log records expected when failing to send an NTP packet.

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param NTPState expected_state: The ntp instance state expected after the get socket operation.
        Make sure referenced fields are populated before calling:
            - socket_timeout
            - next_sync
    :param int time_reference: The time reference at the start of the get socket request.
    :param Optional[str] notify: The context used when a notification is being generated.
    :return: The incremented time reference, which is the next mock time reference
    """
    # The following set of log records are always expected when attempting to send an NTP packet.
    log_records.extend(
        [
            mock_info(MOCKED_POOL_SOCKET_MSG % ADDR_SOCK_KEY),
            mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
            mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
            mock_info(MOCKED_SOCK_ENTER_MSG % (ADDR_SOCK_KEY,)),
            mock_info(
                MOCKED_SOCK_SETTIMEOUT_MSG,
                (expected_state.socket_timeout, ADDR_SOCK_KEY),
            ),
            mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference)),
            mock_info(MOCKED_SOCK_SENDTO_MSG, (NTP_ADDRESS_PORT, ADDR_SOCK_KEY)),
            mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference + 1)),
        ]
    )
    if notify:
        log_records.append(
            mock_info(
                MOCKED_CALLBACK_MSG
                % (
                    notify,
                    EventType.LOOKUP_FAILED,
                    time_reference + 1 + expected_state.limit_delay,
                )
            )
        )
    log_records.append(
        mock_info(MOCKED_SOCK_EXIT_MSG % (ADDR_SOCK_KEY,))
    )  # Always, when context ends
    return time_reference + 2


def logged_for_ntp_packet(
    log_records: List[LogTupleT],
    time_reference: int,
    expected_state: NTPState,
    notify: Optional[str],
) -> int:
    """
    Create the log records expected successfully sending and attempting to get an NTP packet.

    :param List[LogTupleT] log_records: The list to append the log records to.
    :param NTPState expected_state: The ntp instance state expected after the get socket operation.
        Make sure referenced fields are populated before calling:
            - socket_timeout
            - next_sync
    :param int time_reference: The time reference at the start of the get socket request.
    :param Optional[str] notify: The context used when a notification is being generated.
    :return: The incremented time reference, which is the next mock time reference
    """
    # The following set of log records are always expected when attempting to get an NTP packet.
    log_records.extend(
        [
            mock_info(MOCKED_POOL_SOCKET_MSG % ADDR_SOCK_KEY),
            mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
            mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
            mock_info(MOCKED_SOCK_ENTER_MSG % (ADDR_SOCK_KEY,)),
            mock_info(
                MOCKED_SOCK_SETTIMEOUT_MSG,
                (expected_state.socket_timeout, ADDR_SOCK_KEY),
            ),
            mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference)),
            mock_info(MOCKED_SOCK_SENDTO_MSG, (NTP_ADDRESS_PORT, ADDR_SOCK_KEY)),
            mock_info(MOCKED_SOCK_RECV_INTO_MSG % (ADDR_SOCK_KEY,)),
            mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, fmt_thousands(time_reference + 1)),
        ]
    )
    if notify and notify[0:5] == "fail ":
        # If notification is on, and receiving the return packet fails, then a log for the
        # notification is generated.
        log_records.append(
            mock_info(
                MOCKED_CALLBACK_MSG
                % (notify, EventType.SYNC_FAILED, expected_state.next_sync)
            )
        )
    log_records.append(
        mock_info(MOCKED_SOCK_EXIT_MSG % (ADDR_SOCK_KEY,))
    )  # Always, when context ends
    if notify and notify[0:5] == "good ":
        # If notification is on, and receiving the return packet succeeded, then a log
        # for the notification is generated.
        log_records.append(
            mock_info(
                MOCKED_CALLBACK_MSG
                % (notify, EventType.SYNC_COMPLETE, expected_state.next_sync)
            )
        )
    return time_reference + 2
