# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Unittests for the mock classes that support adafruit_ntp testing.
"""
# pylint: disable=too-many-lines

import struct
import sys
import time

try:
    from typing import Tuple
except ImportError:
    pass
import unittest

try:
    import socket as SocketPool
except ImportError:
    from socketpool import SocketPool  # type:ignore
import adafruit_logging as logging
from tests.mocks.mock_pool import MockPool, MockSocket
from tests.mocks import mock_time
from tests.mocks.mock_time import MockTime
from tests.mocks.mock_time import (
    monotonic_ns as mock_monotonic_ns,
    sleep as mock_sleep,
    localtime as mock_localtime,
)
from tests.shared_for_testing import (
    ListHandler,
    ResourcesDepletedError,
    RaisesContext,
    get_context_exception,
    make_mock_rec,
    mock_info,
    set_utc_timezone,
    setup_logger,
    fmt_thousands,
    mock_cleanup,
    MOCK_LOGGER,
    NS_PER_SEC,
    DEFAULT_NTP_ADDRESS,
    MOCKED_NO_RESOURCE_MSG,
    MOCKED_POOL_NEW_MSG,
    MOCKED_POOL_INITIALIZED_MSG,
    MOCKED_POOL_INIT_MSG,
    MOCKED_POOL_INIT_CLEARED_MSG,
    MOCKED_POOL_GETADDR_MSG,
    MOCKED_POOL_SOCKET_MSG,
    MOCKED_SOCK_NEW_MSG,
    MOCKED_SOCK_SUPER_MSG,
    MOCKED_SOCK_INITIALIZED_MSG,
    MOCKED_SOCK_INIT_MSG,
    MOCKED_SOCK_ENTER_MSG,
    MOCKED_SOCK_EXIT_MSG,
    MOCKED_SOCK_SETTIMEOUT_MSG,
    MOCKED_SOCK_SENDTO_MSG,
    MOCKED_SOCK_RECV_INTO_MSG,
    MOCKED_TIME_DEFAULT_START_NS,
    MOCKED_TIME_NEW_MSG,
    MOCKED_TIME_MONOTONIC_NS_MSG,
    MOCKED_TIME_SLEEP_MSG,
    MOCKED_TIME_LOCALTIME_MSG,
    MOCKED_TIME_NOT_LOCALTIME_EX,
    NTP_PACKET_SIZE,
    NTP_SERVER_IPV4_ADDRESS,
    ADDR_SOCK_KEY,
    IP_SOCKET,
)
from tests.simulate_ntp_packet import (
    NTPPacket,
    create_ntp_packet,
    format_ns_as_iso_timestamp,
    ipv4_to_int,
    iso_to_nanoseconds,
    ns_to_fixedpoint,
    ns_to_ntp_timestamp,
    ntp_timestamp_to_unix_ns,
    NTP_PACKET_STRUCTURE,
    NTP_TO_UNIX_EPOCH_SEC,
    NTP_TO_UNIX_EPOCH_NS,
)


class MockException(ValueError):
    """Exception to pass to mock code, to verify raised when requested"""


MOCKED_EXCEPTION_MSG: str = "mock raised requested exception"
MOCKED_EXCEPTION = MockException(MOCKED_EXCEPTION_MSG)


class TestMockPoolSingleton(unittest.TestCase):
    """Unittest for MockPool singleton."""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        _setup_mock_log_capture(cls)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)
        MockPool.clear_mock_singleton()

    def setUp(self):
        """Set up test environment"""
        _reset_mock_log_capture(self)
        MockPool.clear_mock_singleton()

    def tearDown(self):
        """Clean up after each test"""

    def test_singleton(self):
        """Test mock Pool class instantiation"""
        # Cannot use MockPool.get_mock_instance() for the initial test, because that will raise
        # an exception when the singleton is not initialized.
        # pylint:disable=protected-access
        self.assertIsNone(
            MockPool._instance,
            f"MockPool._instance should start at None, found: {type(MockPool._instance)}",
        )
        self.assertFalse(
            hasattr(MockPool, "_mock_initialized"),
            "MockPool class should not start "
            f'with _mock_initialized attribute: {getattr(MockPool, "_mock_initialized", None)}',
        )
        pool1 = MockPool()
        self.assertIsInstance(
            pool1, MockPool, f"instance should be MockPool: {type(pool1)}"
        )
        self.assertIs(
            pool1,
            MockPool.get_mock_instance(),
            'instance should "be" same as _instance',
        )
        self.assertFalse(
            hasattr(MockPool, "_mock_initialized"),
            "MockPool class should not "
            f'get _mock_initialized attribute: {getattr(MockPool, "_mock_initialized", None)}',
        )
        self.assertTrue(
            hasattr(pool1, "_mock_initialized"),
            "MockPool instance should have _mock_initialized attribute",
        )
        # pylint:disable=no-member
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                make_mock_rec(MOCKED_POOL_NEW_MSG, logging.DEBUG),
                make_mock_rec(MOCKED_POOL_INITIALIZED_MSG, logging.DEBUG),
                make_mock_rec(MOCKED_POOL_INIT_MSG, logging.DEBUG),
                make_mock_rec(MOCKED_POOL_INIT_CLEARED_MSG, logging.DEBUG),
            ),
            f"first instance log records should match expected: {self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        pool2 = MockPool()
        self.assertIsInstance(
            pool2, MockPool, f"instance2 should be MockPool: {type(pool2)}"
        )
        self.assertIs(pool1, pool2, "second instance should be same as first")
        self.assertTrue(
            pool2._mock_initialized,
            "instance2._mock_initialized should be True: "
            f"{type(pool2._mock_initialized)} {pool2._mock_initialized}",
        )
        # pylint:disable=no-member
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                make_mock_rec(MOCKED_POOL_NEW_MSG, logging.DEBUG),
                make_mock_rec(MOCKED_POOL_INIT_MSG, logging.DEBUG),
            ),
            f"second instance log records should match expected: {self._log_handler.to_tuple()}",
        )


# end class TestMockPoolSingleton()


class TestMockPoolFunction(unittest.TestCase):
    """Unittest for MockPool functionality."""

    GOOD_SERVER: str = "google.ca"
    GOOD_PORT: int = 80
    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        cls.mock_pool = MockPool()
        _setup_mock_log_capture(cls)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)
        MockPool.clear_mock_singleton()
        MockSocket.clear_mock_singleton()

    def setUp(self):
        """Set up test environment"""
        self.mock_pool.mock_getaddrinfo_attempts.clear()
        MockSocket.clear_mock_singleton()
        _reset_mock_log_capture(self)

    def tearDown(self):
        """Clean up after each test"""

    def test_class_constants(self):
        """See if the mocked class constants match the real class."""
        self.assertEqual(
            MockPool.AF_INET,
            SocketPool.AF_INET,
            f"AF_INET {MockPool.AF_INET} should match {SocketPool.AF_INET}",
        )
        self.assertEqual(
            MockPool.SOCK_DGRAM,
            SocketPool.SOCK_DGRAM,
            f"SOCK_DGRAM {MockPool.SOCK_DGRAM} should match {SocketPool.SOCK_DGRAM}",
        )
        self.assertEqual(
            MockPool.SOCK_STREAM,
            SocketPool.SOCK_STREAM,
            f"SOCK_STREAM {MockPool.SOCK_STREAM} should match {SocketPool.SOCK_STREAM}",
        )
        self.assertEqual(
            MockPool.IPPROTO_IP,
            SocketPool.IPPROTO_IP,
            f"IPPROTO_IP {MockPool.IPPROTO_IP} should match {SocketPool.IPPROTO_IP}",
        )

    def test_empty_responses(self):
        """Test empty mock getaddrinfo responses."""
        with self.assertRaises(ResourcesDepletedError) as context:
            result = self.mock_pool.getaddrinfo(self.GOOD_SERVER, self.GOOD_PORT)
            raise AssertionError(
                f"should have raised ResourcesDepletedError, got {result}"
            )
        exc_data = get_context_exception(context)
        self.assertEqual(
            repr(exc_data),
            repr(ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "getaddrinfo")),
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_POOL_GETADDR_MSG, (self.GOOD_SERVER, self.GOOD_PORT)),),
        )

    def test_lookup_failures(self):
        """Test address lookup failures before success."""
        self.mock_pool.set_getaddrinfo_responses(
            [
                MOCKED_EXCEPTION,
                MOCKED_EXCEPTION,
                IP_SOCKET,
            ]
        )

        with self.assertRaises(MockException) as context:
            result = self.mock_pool.getaddrinfo(None, self.GOOD_PORT)
            raise AssertionError(f"should have raised MockException, got {result}")
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(MOCKED_EXCEPTION))

        with self.assertRaises(MockException) as context:
            result = self.mock_pool.getaddrinfo(self.GOOD_SERVER, self.GOOD_PORT)
            raise AssertionError(f"should have raised MockException, got {result}")
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(MOCKED_EXCEPTION))
        result = self.mock_pool.getaddrinfo(self.GOOD_SERVER, self.GOOD_PORT)
        self.assertEqual(result, IP_SOCKET)
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_POOL_GETADDR_MSG, (None, self.GOOD_PORT)),
                mock_info(MOCKED_POOL_GETADDR_MSG, (self.GOOD_SERVER, self.GOOD_PORT)),
                mock_info(MOCKED_POOL_GETADDR_MSG, (self.GOOD_SERVER, self.GOOD_PORT)),
            ),
        )

    def test_socket_default(self):
        """Test default socket creation."""
        sock = self.mock_pool.socket()
        self.assertIsInstance(
            sock, MockSocket, f"sock instance should be MockSocket: {type(sock)}"
        )
        expected = (
            self.mock_pool.AF_INET,
            self.mock_pool.SOCK_STREAM,
            self.mock_pool.IPPROTO_IP,
        )
        self.assertEqual(
            sock.mock_key,
            expected,
            f"default sock mock_key should match {expected}, got: {sock.mock_key}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_POOL_SOCKET_MSG % expected),
                mock_info(MOCKED_SOCK_NEW_MSG % (expected,)),
                mock_info(MOCKED_SOCK_SUPER_MSG % (expected,)),
                mock_info(MOCKED_SOCK_INITIALIZED_MSG % (expected,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (expected,)),
            ),
            "default socket creation log records should match expected, got:\n"
            f"{self._log_handler.to_tuple()}",
        )

    def test_socket_dgram(self):
        """Test datagram socket creation."""
        sock = self.mock_pool.socket(self.mock_pool.AF_INET, self.mock_pool.SOCK_DGRAM)
        self.assertIsInstance(
            sock, MockSocket, f"sock instance should be MockSocket: {type(sock)}"
        )
        expected = (
            self.mock_pool.AF_INET,
            self.mock_pool.SOCK_DGRAM,
            self.mock_pool.IPPROTO_IP,
        )
        self.assertEqual(
            sock.mock_key,
            expected,
            f"dgram sock mock_key should match {expected}, got: {sock.mock_key}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_POOL_SOCKET_MSG % expected),
                mock_info(MOCKED_SOCK_NEW_MSG % (expected,)),
                mock_info(MOCKED_SOCK_SUPER_MSG % (expected,)),
                mock_info(MOCKED_SOCK_INITIALIZED_MSG % (expected,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (expected,)),
            ),
            "dgram socket creation log records should match expected, got:\n"
            f"{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        sock2 = self.mock_pool.socket(self.mock_pool.AF_INET, self.mock_pool.SOCK_DGRAM)
        self.assertIsInstance(
            sock2, MockSocket, f"sock2 instance should be MockSocket: {type(sock)}"
        )
        expected = (
            self.mock_pool.AF_INET,
            self.mock_pool.SOCK_DGRAM,
            self.mock_pool.IPPROTO_IP,
        )
        self.assertEqual(
            sock2.mock_key,
            expected,
            f"dgram sock mock_key should match {expected}, got: {sock.mock_key}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_POOL_SOCKET_MSG % expected),
                mock_info(MOCKED_SOCK_NEW_MSG % (expected,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (expected,)),
            ),
            "duplicate dgram socket creation log records should match expected, got:\n"
            f"{self._log_handler.to_tuple()}",
        )


# end class TestMockPool()


class TestMockSocketSingleton(unittest.TestCase):
    """Unittest for MockSocket singleton"""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        _setup_mock_log_capture(cls)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)
        MockSocket.clear_mock_singleton()

    def setUp(self):
        """Set up test environment"""
        _reset_mock_log_capture(self)
        MockSocket.clear_mock_singleton()

    def tearDown(self):
        """Clean up after each test"""

    def test_singleton(self):
        """Test mock Socket class instantiation"""
        # pylint:disable=protected-access
        sock_instances = MockSocket.get_mock_instance()
        self.assertIsInstance(
            sock_instances, dict, "MockSocket._instances should be a dict"
        )
        self.assertEqual(
            len(sock_instances), 0, "MockSocket._instances should start empty"
        )
        mock_sock = MockSocket(*ADDR_SOCK_KEY)
        self.assertIsNotNone(mock_sock, "Should have returned an instance")
        self.assertIs(
            sock_instances,
            mock_sock.get_mock_instance(),
            'MockSocket._instances should "be" the instance._instances',
        )
        self.assertEqual(
            len(sock_instances),
            1,
            "MockSocket._instances should contain a single entry",
        )
        self.assertIn(
            ADDR_SOCK_KEY,
            sock_instances,
            "MockSocket._instances should have expected key",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_SUPER_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INITIALIZED_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
            ),
            "first instance log records should match expected, got: "
            + f"{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        # duplicate instance
        mock_sock1 = MockSocket(*ADDR_SOCK_KEY)
        self.assertIs(mock_sock, mock_sock1, "should be the same MockSocket instance")
        self.assertEqual(
            len(sock_instances),
            1,
            "MockSocket._instances should contain a single entry",
        )
        self.assertEqual(
            tuple(sock_instances.keys())[0],
            ADDR_SOCK_KEY,
            "MockSocket._instances should have expected entry",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
            ),
            "duplicate instance log records should match expected, got: "
            f"{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        # different instance
        alt_sock_key = (1, 2, 3)
        mock_sock2 = MockSocket(*alt_sock_key)
        self.assertIsNotNone(mock_sock)
        self.assertIsNot(
            mock_sock, mock_sock2, "should not be the same MockSocket instance"
        )
        self.assertEqual(
            len(sock_instances), 2, "MockSocket._instances should contain two entries"
        )
        self.assertIn(
            alt_sock_key,
            sock_instances,
            "MockSocket._instances should have expected alternate entry",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (alt_sock_key,)),
                mock_info(MOCKED_SOCK_SUPER_MSG % (alt_sock_key,)),
                mock_info(MOCKED_SOCK_INITIALIZED_MSG % (alt_sock_key,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (alt_sock_key,)),
            ),
            "alternate instance log records should match expected, got: "
            f"{self._log_handler.to_tuple()}",
        )


# end class TestMockSocketSingleton()


class TestMockSocketFunction(unittest.TestCase):
    """Unittest for MockSocket functionality"""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        _setup_mock_log_capture(cls)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)

    def setUp(self):
        """Set up test environment"""
        MockSocket.clear_mock_singleton()
        # The method being tested will be used by the instance of the app being tested, which
        # is created after the 'controlling' instance in the unit tests. Create the controlling
        # instance, clear the log records, and then create the app instance for the test.
        self.mock_control = MockSocket(*ADDR_SOCK_KEY)
        self.mock_socket = MockSocket(*ADDR_SOCK_KEY)
        _reset_mock_log_capture(self)

    def tearDown(self):
        """Clean up after each test"""

    def test_settimeout_direct(self):
        """test direct call to MockSocket.settimeout"""
        timeout = 15
        self.mock_socket.settimeout(timeout)
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_SOCK_SETTIMEOUT_MSG, (timeout, ADDR_SOCK_KEY)),),
        )

    def test_settimeout_with(self):
        """test MockSocket.settimeout inside with"""
        with MockSocket(*ADDR_SOCK_KEY) as sock:
            timeout = 15
            sock.settimeout(timeout)
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_ENTER_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_SETTIMEOUT_MSG, (timeout, ADDR_SOCK_KEY)),
                mock_info(MOCKED_SOCK_EXIT_MSG % (ADDR_SOCK_KEY,)),
            ),
        )

    def test_sendto_direct(self):
        """test direct call to MockSocket.sendto"""
        # The method being tested will be used by the instance of the app being tested, which
        # is created after the 'controlling' instance in the unit tests. Create the controlling
        # instance, clear the log records, and then create the app instance for the test.
        size, send_packet, ref_send_packet = self._setup_test_sendto()
        self.assertEqual(
            len(ref_send_packet), size, f"NTP Packet should be {size} bytes"
        )
        self.assertIsNot(
            send_packet, ref_send_packet, "packet to send should be a copy"
        )
        self.assertEqual(
            send_packet, ref_send_packet, "packet to send should match ref"
        )

        result = self.mock_socket.sendto(send_packet, DEFAULT_NTP_ADDRESS)
        self.assertEqual(result, size, f"sendto should return {size}, got {result}")
        self._match_send_packet(self.mock_control, send_packet, ref_send_packet)
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_SOCK_SENDTO_MSG, (DEFAULT_NTP_ADDRESS, ADDR_SOCK_KEY)),),
        )

    def test_sendto_with(self):
        """test MockSocket.sendto using with"""
        size, send_packet, ref_send_packet = self._setup_test_sendto()
        with MockSocket(*ADDR_SOCK_KEY) as sock:
            result = sock.sendto(send_packet, DEFAULT_NTP_ADDRESS)
        self.assertEqual(result, size, f"sendto should return {size}, got {result}")
        self._match_send_packet(self.mock_control, send_packet, ref_send_packet)
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_ENTER_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_SENDTO_MSG, (DEFAULT_NTP_ADDRESS, ADDR_SOCK_KEY)),
                mock_info(MOCKED_SOCK_EXIT_MSG % (ADDR_SOCK_KEY,)),
            ),
        )

    def _setup_test_sendto(self) -> Tuple[int, bytearray, bytearray]:
        """setup data to use for testing sendto method."""
        base_packet = create_ntp_packet(mode=3)
        ref_send_packet = bytearray((0,) * len(base_packet))
        ref_send_packet[0] = base_packet[0]  # Leap:2, Version:3, Mode:3
        self.mock_control.mock_sendto_attempts = [NTP_PACKET_SIZE]
        send_packet = ref_send_packet[:]
        return NTP_PACKET_SIZE, send_packet, ref_send_packet

    def test_empty_recv_into_responses(self):
        """Test empty recv_into responses."""
        source_packet = create_ntp_packet(mode=3)
        test_sock = MockSocket(*ADDR_SOCK_KEY)
        self._log_handler.log_records.clear()
        with self.assertRaises(ResourcesDepletedError) as context:
            result = test_sock.recv_into(source_packet)
            raise AssertionError(
                f"should have raised ResourcesDepletedError, got {result}"
            )
        exc_data = get_context_exception(context)
        self.assertEqual(
            repr(exc_data),
            repr(ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "recv_into")),
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_SOCK_RECV_INTO_MSG % (ADDR_SOCK_KEY,)),),
        )
        self._log_handler.log_records.clear()

    def test_empty_sendto_responses(self):
        """Test empty sendto responses."""
        source_packet = create_ntp_packet(mode=3)
        test_sock = MockSocket(*ADDR_SOCK_KEY)
        self._log_handler.log_records.clear()
        with self.assertRaises(ResourcesDepletedError) as context:
            result = test_sock.sendto(source_packet, NTP_SERVER_IPV4_ADDRESS)
            raise AssertionError(
                f"should have raised ResourcesDepletedError, got {result}"
            )
        exc_data = get_context_exception(context)
        self.assertEqual(
            repr(exc_data),
            repr(ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "sendto")),
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(
                    MOCKED_SOCK_SENDTO_MSG, (NTP_SERVER_IPV4_ADDRESS, ADDR_SOCK_KEY)
                ),
            ),
        )
        self._log_handler.log_records.clear()

    def test_recv_into_direct(self):
        """test MockSocket.recv_into with good data"""
        recv_packet = create_ntp_packet(mode=4, ref_delta=500_000_000)
        self.mock_control.mock_recv_into_attempts = [recv_packet]
        source_packet = bytearray((0,) * len(recv_packet))
        test_sock = MockSocket(*ADDR_SOCK_KEY)
        result = test_sock.recv_into(source_packet)
        self.assertEqual(
            result,
            len(recv_packet),
            f"recv_into should return {len(recv_packet)}, got {result}",
        )
        self.assertEqual(
            source_packet, recv_packet, "source packet should match received"
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(MOCKED_SOCK_NEW_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_INIT_MSG % (ADDR_SOCK_KEY,)),
                mock_info(MOCKED_SOCK_RECV_INTO_MSG % (ADDR_SOCK_KEY,)),
            ),
        )

    def test_recv_into_raise_exception(self):
        """test MockSocket.recv_into raising injected exception"""
        self.mock_control.mock_recv_into_attempts = [MOCKED_EXCEPTION]
        source_packet = bytearray((0,) * NTP_PACKET_SIZE)
        with self.assertRaises(MockException) as context:
            result = self.mock_socket.recv_into(source_packet)
            raise AssertionError(f"should have raised MockException, got {result}")
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(MOCKED_EXCEPTION))
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_SOCK_RECV_INTO_MSG % (ADDR_SOCK_KEY,)),),
        )

    def test_sendto_raise_exception(self):
        """test MockSocket.sendto raising injected exception"""
        self.mock_control.mock_sendto_attempts = [MOCKED_EXCEPTION]
        source_packet = bytearray((0,) * NTP_PACKET_SIZE)
        with self.assertRaises(MockException) as context:
            result = self.mock_socket.sendto(source_packet, NTP_SERVER_IPV4_ADDRESS)
            raise AssertionError(f"should have raised MockException, got {result}")
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(MOCKED_EXCEPTION))
        self.assertEqual(
            self._log_handler.to_tuple(),
            (
                mock_info(
                    MOCKED_SOCK_SENDTO_MSG, (NTP_SERVER_IPV4_ADDRESS, ADDR_SOCK_KEY)
                ),
            ),
        )

    def _match_send_packet(
        self, control: MockSocket, send_packet: bytearray, ref_send_packet: bytearray
    ) -> None:
        """
        Match the send packet to the reference packet

        :param control: MockSocket: mock control instance for socket
        :param send_packet: bytearray: packet sent
        :param ref_send_packet: bytearray: reference packet
        """
        self.assertIsNot(
            send_packet, ref_send_packet, "packet to send should be a copy"
        )
        self.assertEqual(
            len(control.mock_send_packet),
            1,
            "Should be 1 packet in the send "
            f"capture buffer, found {len(control.mock_send_packet)}",
        )
        captured_packet = control.mock_send_packet.pop(0)
        self.assertEqual(captured_packet, ref_send_packet)
        self.assertIsNot(
            captured_packet, send_packet, "Captured packet should be a copy"
        )
        raw_fields = struct.unpack(NTP_PACKET_STRUCTURE, captured_packet)
        lvm = raw_fields[0]  # Leap:2, Version:3, Mode:3
        captured_fields = NTPPacket(
            (lvm & 0b11000000) >> 6,
            (lvm & 0b00111000) >> 3,
            lvm & 0b00000111,
            *raw_fields[1:],
        )
        self.assertEqual(
            captured_fields, NTPPacket(0, 4, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )


# end class TestMockSocketFunction()


class TestPacketUtilities(unittest.TestCase):
    """Unittest for ntp packet and field manipulation utility functions"""

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        set_utc_timezone()

    @classmethod
    def tearDownClass(cls):
        """Get rid of resources used for the TestCase."""

    def test_ipv4_to_int(self):
        """test ipv4_to_int"""
        ipv4 = "192.168.1.1"
        expected = (
            0xC0A80101  # hex(192) hex(168) hex(1) hex(1), 8 bits each = 0xc0a80101
        )
        result = ipv4_to_int(ipv4)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ipv4}, got {result}"
        )
        ipv4 = "255.255.255.255"
        expected = 0xFFFFFFFF
        result = ipv4_to_int(ipv4)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ipv4}, got {result}"
        )
        ipv4 = "0.0.0.0"
        expected = 0
        result = ipv4_to_int(ipv4)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ipv4}, got {result}"
        )

    def test_iso_to_nanoseconds(self):
        """test iso_to_seconds"""
        iso = "2024-1-1T10:11:12.123456789"
        result = iso_to_nanoseconds(iso)
        expected = 1704103872123456789
        self.assertEqual(
            result, expected, f"Expected {expected} for {iso}, got {result}"
        )
        iso = "2024-1-1T10:11:12.12345678"
        result = iso_to_nanoseconds(iso)
        expected = 1704103872123456780
        self.assertEqual(
            result, expected, f"Expected {expected} for {iso}, got {result}"
        )
        iso = "2024-1-1T10:11:12.5"
        result = iso_to_nanoseconds(iso)
        expected = 1704103872500000000
        self.assertEqual(
            result, expected, f"Expected {expected} for {iso}, got {result}"
        )
        iso = "2021-08-11T16:12:34"
        result = iso_to_nanoseconds(iso)
        expected = 1628698354000000000
        self.assertEqual(
            result, expected, f"Expected {expected} for {iso}, got {result}"
        )
        iso = "2023-12-31T23:59:59.987654321"
        result = iso_to_nanoseconds(iso)
        expected = 1704067199987654321
        self.assertEqual(
            result, expected, f"Expected {expected} for {iso}, got {result}"
        )

    def test_ns_to_fixedpoint(self):
        """test ns_to_fixedpoint"""
        nanoseconds = 1
        result = ns_to_fixedpoint(nanoseconds)
        expected = 0
        nanoseconds = 900
        result = ns_to_fixedpoint(nanoseconds)
        expected = 0
        self.assertEqual(
            result, expected, f"Expected {expected} for {nanoseconds}, got {result}"
        )
        nanoseconds = 500_000_000
        result = ns_to_fixedpoint(nanoseconds)
        expected = 0x8000
        self.assertEqual(
            result, expected, f"Expected {expected} for {nanoseconds}, got {result}"
        )
        nanoseconds = 2_500_000_000
        result = ns_to_fixedpoint(nanoseconds)
        expected = 0x28000
        self.assertEqual(
            result, expected, f"Expected {expected} for {nanoseconds}, got {result}"
        )
        nanoseconds = -500_000_000
        result = ns_to_fixedpoint(nanoseconds)
        expected = -1 * (0x8000)
        self.assertEqual(
            result, expected, f"Expected {expected} for {nanoseconds}, got {result}"
        )
        nanoseconds = -2_500_000_000
        result = ns_to_fixedpoint(nanoseconds)
        expected = -1 * (0x28000)
        self.assertEqual(
            result, expected, f"Expected {expected} for {nanoseconds}, got {result}"
        )

    def test_ns_to_ntp_timestamp(self):
        """test ns_to_ntp_timestamp"""
        # iso = '2024-1-1T10:11:12.5'
        # utc ns = 1_704_103_872_500_000_000
        # seconds = 1_704_103_872, 0x65928fc0
        tst_seconds = 1_704_103_872 + NTP_TO_UNIX_EPOCH_SEC  # 0xe93d0e40
        tst_ns = 500_000_000
        ntp_ns = (tst_seconds * NS_PER_SEC) + tst_ns
        expected = 0xE93D0E4080000000
        result = ns_to_ntp_timestamp(ntp_ns)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ntp_ns}, got {result}"
        )

        tst_ns = 3906250
        ntp_ns = (tst_seconds * NS_PER_SEC) + tst_ns
        expected = 0xE93D0E4001000000
        result = ns_to_ntp_timestamp(ntp_ns)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ntp_ns}, got {result}"
        )

        tst_ns = 1
        ntp_ns = (tst_seconds * NS_PER_SEC) + tst_ns
        expected = 0xE93D0E4000000004
        result = ns_to_ntp_timestamp(ntp_ns)
        self.assertEqual(
            result, expected, f"Expected {expected} for {ntp_ns}, got {result}"
        )

    def test_ntp_timestamp_to_unix_ns(self):
        """test ntp_timestamp_to_unix_ns"""
        # iso = '2024-1-1T10:11:12.5'
        # utc ns = 1_704_103_872_500_000_000
        ntp = 0xE93D0E4080000000
        expected = 1_704_103_872_500_000_000
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected0 {expected} for {ntp:x}, got {result}"
        )
        ntp = 0xE93D0E4000000001
        expected = 1_704_103_872_000_000_001
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected1 {expected} for {ntp:x}, got {result}"
        )
        ntp = 0xE93D0E4000000002
        expected = 1_704_103_872_000_000_001
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected1 {expected} for {ntp:x}, got {result}"
        )
        ntp = 0xE93D0E4000000003
        expected = 1_704_103_872_000_000_001
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected1 {expected} for {ntp:x}, got {result}"
        )
        ntp = 0xE93D0E4000000004
        expected = 1_704_103_872_000_000_001
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected2 {expected} for {ntp:x}, got {result}"
        )
        ntp = 0xE93D0E4000000005
        expected = 1_704_103_872_000_000_002
        result = ntp_timestamp_to_unix_ns(ntp)
        self.assertEqual(
            result, expected, f"Expected3 {expected} for {ntp:x}, got {result}"
        )

    def test_ns_ntp_ns_round_trip(self):
        """test ns_to_ntp_timestamp and back"""
        base_utc_ns = 1_704_103_872 * NS_PER_SEC
        # Test across different nanosecond ranges
        for slide in range(32):
            slide_offset = 2**slide
            for ns_offset in range(12):
                utc_ns = base_utc_ns + slide_offset + ns_offset
                result = ntp_timestamp_to_unix_ns(
                    ns_to_ntp_timestamp(utc_ns + NTP_TO_UNIX_EPOCH_NS)
                )
                self.assertEqual(
                    result,
                    utc_ns,
                    f"Expected {fmt_thousands(utc_ns)} for round trip, got {fmt_thousands(result)}",
                )

    def test_create_ntp_packet(self):  # pylint:disable=too-many-locals
        """test create_ntp_packet"""
        test_iso = "2024-01-01T10:11:12.987654321"
        test_leap = 0
        fixed_version = 4
        test_mode = 5
        test_stratum = 3
        test_poll = 9
        test_precision = -9
        test_root_delay = 1_543_210_987
        test_root_dispersion = 567_432
        test_ipv4 = "10.23.45.67"
        test_ref_delta = 0  # iso is the reference
        test_receive_delta = 10_012_345_678  # 10 seconds plus adjust to get all 9's ns
        test_transmit_delay = 500_000_002  # just over half a second
        result = create_ntp_packet(
            test_iso,
            leap=test_leap,
            mode=test_mode,
            stratum=test_stratum,
            poll=test_poll,
            precision=test_precision,
            root_delay=test_root_delay,
            root_dispersion=test_root_dispersion,
            ipv4=test_ipv4,
            ref_delta=test_ref_delta,
            receive_delta=test_receive_delta,
            transmit_delay=test_transmit_delay,
        )
        raw_fields = struct.unpack(NTP_PACKET_STRUCTURE, result)
        lvm = raw_fields[0]  # Leap:2, Version:3, Mode:3
        created_fields = NTPPacket(
            (lvm & 0b11000000) >> 6,
            (lvm & 0b00111000) >> 3,
            lvm & 0b00000111,
            *raw_fields[1:],
        )
        self.assertEqual(
            created_fields.leap,
            test_leap,
            f"leap is {created_fields.leap}, expected {test_leap}",
        )
        self.assertEqual(
            created_fields.version,
            fixed_version,
            f"version is {created_fields.version}, expected {fixed_version}",
        )
        self.assertEqual(
            created_fields.mode,
            test_mode,
            f"mode is {created_fields.mode}, expected {test_mode}",
        )
        self.assertEqual(
            created_fields.stratum,
            test_stratum,
            f"stratum is {created_fields.stratum}, expected {test_stratum}",
        )
        self.assertEqual(
            created_fields.poll,
            test_poll,
            f"poll is {created_fields.poll}, expected {test_poll}",
        )
        self.assertEqual(
            created_fields.precision,
            test_precision,
            f"precision is {created_fields.precision}, expected {test_precision}",
        )
        formatted = ns_to_fixedpoint(test_root_delay)
        self.assertEqual(
            created_fields.root_delay,
            formatted,
            f"root_delay is {fmt_thousands(created_fields.root_delay)} "
            + f"{created_fields.root_delay:x}, "
            + f"expected {fmt_thousands(test_root_delay)} {formatted:x}",
        )
        formatted = ns_to_fixedpoint(test_root_dispersion)
        self.assertEqual(
            created_fields.root_dispersion,
            formatted,
            "root_dispersion is "
            f"{fmt_thousands(created_fields.root_dispersion)} "
            + f"{created_fields.root_dispersion:x}, "
            + f"expected {fmt_thousands(test_root_dispersion)} {formatted:x}",
        )
        formatted = "{}.{}.{}.{}".format(  # pylint:disable=consider-using-f-string
            *tuple(
                (created_fields.ref_id >> shift) & 0xFF for shift in range(24, -1, -8)
            )
        )
        self.assertEqual(
            formatted, test_ipv4, f"ref_id (IPv4) is {formatted}, expected {test_ipv4}"
        )
        formatted = format_ns_as_iso_timestamp(
            ntp_timestamp_to_unix_ns(created_fields.ref_ts)
        )
        expected = "2024-01-01T10:11:12.987654321"
        self.assertEqual(
            formatted, expected, f"ref_ts is {formatted}, expected {expected}"
        )
        formatted = format_ns_as_iso_timestamp(
            ntp_timestamp_to_unix_ns(created_fields.recv_ts)
        )
        expected = "2024-01-01T10:11:22.999999999"
        self.assertEqual(
            formatted, expected, f"recv_ts is {formatted}, expected {expected}"
        )
        formatted = format_ns_as_iso_timestamp(
            ntp_timestamp_to_unix_ns(created_fields.tx_ts)
        )
        expected = "2024-01-01T10:11:23.500000001"
        self.assertEqual(
            formatted, expected, f"tx_ts is {formatted}, expected {expected}"
        )
        self.assertEqual(
            created_fields.orig_ts,
            0,
            f"orig_ts is {created_fields.orig_ts}, expected {0}",
        )


# end class TestPacketUtilities()


class TestMockTimeSingleton(unittest.TestCase):
    """Unittest for MockTime singleton"""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        _setup_mock_log_capture(cls)

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)
        mock_time.clear_mock_singleton()

    def setUp(self):
        """Set up test environment"""
        mock_time.clear_mock_singleton()
        _reset_mock_log_capture(self)

    def test_singleton(self):
        """Test mock class instantiation"""
        base_instance = mock_time.get_mock_instance()
        self.assertIs(
            base_instance,
            MockTime.get_mock_instance(),
            "MockTime._instance should match the module level instance",
        )
        time_instance = MockTime()
        self.assertIsNotNone(
            time_instance,
            f"MockTime Should have returned an instance: {type(time_instance)}",
        )
        self.assertIs(
            base_instance,
            time_instance,
            "MockTime instantiation should match the module level instance",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_NEW_MSG),),
            "First instance log records should match expected; "
            f"got:\n{self._log_handler.to_tuple()}",
        )
        # Really time_instance is not the first instance. base_instance was created first
        # when the module was imported, and mock_time.clear_mock_singleton() makes sure
        # that stays current. That is why the above log check does NOT include a record for
        # MOCKED_TIME_FIRST_NEW_MSG
        self._log_handler.log_records.clear()

        # duplicate instance
        time_instance1 = MockTime()
        self.assertIs(
            time_instance, time_instance1, "should be the same MockTime instance"
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_NEW_MSG),),
            "Other instance log records should match expected; "
            f"got:\n{self._log_handler.to_tuple()}",
        )


# end class TestMockSocketSingleton()


class TestMockTimeFunction(unittest.TestCase):
    """Unittest for MockTime functionality"""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        _setup_mock_log_capture(cls)
        set_utc_timezone()
        # cls.mock_control = mock_time.get_mock_instance()

    @classmethod
    def tearDownClass(cls):
        """Get rid of the list test specific handler."""
        _teardown_mock_log_capture(cls)
        mock_time.clear_mock_singleton()

    def setUp(self):
        """Set up test environment"""
        mock_time.clear_mock_singleton()
        self.mock_control = mock_time.get_mock_instance()
        # self.mock_control.set_mock_ns(MOCKED_TIME_DEFAULT_START_NS)
        _reset_mock_log_capture(self)

    def tearDown(self):
        """Clean up after each test"""

    def test_get_mock_ns(self):
        """test MockTime.get_mock_ns"""
        expected = MOCKED_TIME_DEFAULT_START_NS
        actual = self.mock_control.get_mock_ns()
        self.assertEqual(
            actual, expected, f"Initial mock time should be {expected}, got {actual}"
        )
        expected = 1_234_567
        self.mock_control.set_mock_ns(expected)
        actual = self.mock_control.get_mock_ns()
        self.assertEqual(
            actual, expected, f"Updated mock time should be {expected}, got {actual}"
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (),
            f"Using get_mock_ns should not create any log records: {self._log_handler.to_tuple()}",
        )

    def test_set_mock_ns(self):
        """test MockTime.set_mock_ns"""
        expected = 7_654_321
        self.mock_control.set_mock_ns(expected)
        actual = self.mock_control.get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"mock instance monotonic_ns should be {expected}, got {actual}",
        )
        actual = MockTime.get_mock_instance().get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"mock Class monotonic_ns should be be {expected}, got {actual}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (),
            f"Using set_mock_ns should not create any log records: {self._log_handler.to_tuple()}",
        )

    def test_new(self):
        """test MockTime.__new__"""
        expected = MOCKED_TIME_DEFAULT_START_NS
        tm_instance = MockTime()
        actual = tm_instance.get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"default mock time should start at {expected}, got {actual}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_NEW_MSG),),
            "Instance1 reset log records should match expected; "
            f"got:\n{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        expected = 1_345_987_246
        tm_instance = MockTime()
        tm_instance.set_mock_ns(expected)
        actual = tm_instance.get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"specified mock time should start at {expected}, got {actual}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_NEW_MSG),),
            "Instance2 reset log records should match expected; "
            f"got:\n{self._log_handler.to_tuple()}",
        )

    def test_monotonic_ns(self):
        """test MockTime.monotonic_ns, mock_time.monotonic_ns, and mock_monotonic_ns"""
        expected = MOCKED_TIME_DEFAULT_START_NS
        actual = self.mock_control.get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"starting mock time should start at {expected}, got {actual}",
        )
        expected += 1
        actual = self.mock_control.monotonic_ns()
        self._verify_monotonic_ns_increment(expected, actual, "instance monotonic_ns")
        self._log_handler.log_records.clear()
        expected += 1
        actual = mock_time.monotonic_ns()
        self._verify_monotonic_ns_increment(expected, actual, "mock_time.monotonic_ns")
        self._log_handler.log_records.clear()
        expected += 1
        actual = mock_monotonic_ns()
        self._verify_monotonic_ns_increment(expected, actual, "mock_monotonic_ns")

    def _verify_monotonic_ns_increment(
        self, expected: int, actual: int, label: str
    ) -> None:
        """Consistent check of monotonic_ns result."""
        self.assertEqual(
            actual,
            expected,
            f"{label} should have incremented to {expected}, got {actual}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_MONOTONIC_NS_MSG, (fmt_thousands(expected),)),),
            f"{label} log records should match expected; got:\n{self._log_handler.to_tuple()}",
        )

    def test_sleep(self):
        """test MockTime.sleep, mock_time.sleep and mock_sleep"""
        sleep_time = 1.5  # float seconds
        # Do not use simple 1_500_000_000 offset. CircuitPython precision does not get there.
        sleep_ns = int(sleep_time * 1_000_000_000)
        expected = MOCKED_TIME_DEFAULT_START_NS + sleep_ns
        self.mock_control.sleep(sleep_time)
        self._verify_sleep_time(sleep_time, expected, "instance sleep")
        self._log_handler.log_records.clear()
        expected += sleep_ns
        mock_time.sleep(sleep_time)
        self._verify_sleep_time(sleep_time, expected, "mock_time.sleep")
        self._log_handler.log_records.clear()
        expected += sleep_ns
        mock_sleep(sleep_time)
        self._verify_sleep_time(sleep_time, expected, "mock_sleep")

    def _verify_sleep_time(self, sleep_time: float, expected: int, label: str) -> None:
        """Consistent check of sleep result."""
        actual = self.mock_control.get_mock_ns()
        self.assertEqual(
            actual,
            expected,
            f"{label} mock time should end at {expected}, got {actual}",
        )
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_SLEEP_MSG, (sleep_time,)),),
            f"{label} log records should match expected; got:\n{self._log_handler.to_tuple()}",
        )

    def test_localtime_default(self):
        """test MockTime.localtime, mock_time.localtime and mock_localtime without an argument"""
        with self.assertRaises(NotImplementedError) as context:
            self.mock_control.localtime()
        self._verify_localtime_default(context, "instance localtime")
        self._log_handler.log_records.clear()
        with self.assertRaises(NotImplementedError) as context:
            mock_time.localtime()
        self._verify_localtime_default(context, "mock_time.localtime")
        self._log_handler.log_records.clear()
        with self.assertRaises(NotImplementedError) as context:
            mock_localtime()
        self._verify_localtime_default(context, "mock_localtime")

    def _verify_localtime_default(self, context: RaisesContext, label: str) -> None:
        """Consistent check of localtime result."""
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(MOCKED_TIME_NOT_LOCALTIME_EX))
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_LOCALTIME_MSG, (None,)),),
            f"{label} log records should match expected; got:\n{self._log_handler.to_tuple()}",
        )

    def test_localtime_with_arg(self):
        """test MockTime.localtime, mock_time.localtime and mock_localtime with an argument"""
        # datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc) = 946684800.0
        # time.localtime(946684800) = time.struct_time(tm_year=1999, tm_mon=12, tm_mday=31,
        #   tm_hour=17, tm_min=0, tm_sec=0, tm_wday=4, tm_yday=365, tm_isdst=0)
        case = 946684800  # 2000-01-01 00:00:00 UTC
        actual = self.mock_control.localtime(case)
        self._verify_time_struct_fields("instance localtime", case, actual)
        self._log_handler.log_records.clear()
        actual = mock_time.localtime(case)
        self._verify_time_struct_fields("mock_time.localtime", case, actual)
        self._log_handler.log_records.clear()
        actual = mock_localtime(case)
        self._verify_time_struct_fields("mock_localtime", case, actual)

    def _verify_time_struct_fields(
        self, context: str, case: int, actual: time.struct_time
    ) -> None:
        """Common field value verifications that are repeated a couple of times."""
        self.assertIsInstance(
            actual,
            time.struct_time,
            f"localtime should return a time.struct_time, got {type(actual)}",
        )
        self.assertEqual(
            actual.tm_year, 2000, f"localtime year should be 2000, got {actual.tm_year}"
        )
        self.assertEqual(
            actual.tm_mon, 1, f"localtime month should be 1, got {actual.tm_mon}"
        )
        self.assertEqual(
            actual.tm_mday, 1, f"localtime day should be 1, got {actual.tm_mday}"
        )
        self.assertEqual(
            actual.tm_hour, 0, f"localtime hour should be 0, got {actual.tm_hour}"
        )
        self.assertEqual(
            actual.tm_min, 0, f"localtime minute should be 0, got {actual.tm_min}"
        )
        self.assertEqual(
            actual.tm_sec, 0, f"localtime second should be 0, got {actual.tm_sec}"
        )
        self.assertEqual(
            actual.tm_yday,
            1,
            f"localtime day of year should be 1, got {actual.tm_yday}",
        )
        self.assertEqual(
            actual.tm_wday, 5, f"localtime weekday should be 5, got {actual.tm_wday}"
        )
        expected = 0 if sys.implementation.name == "cpython" else -1
        self.assertEqual(
            actual.tm_isdst,
            expected,
            f"localtime is dst should be {expected}, got {actual.tm_isdst}",
        )
        iso = format_ns_as_iso_timestamp(case * 1_000_000_000)
        expected = "2000-01-01T00:00:00"
        self.assertEqual(iso, expected, f"utc iso should be {expected}, got {iso}")
        self.assertEqual(
            self._log_handler.to_tuple(),
            (mock_info(MOCKED_TIME_LOCALTIME_MSG, (case,)),),
            f"{context} log records should match expected; got:\n{self._log_handler.to_tuple()}",
        )


# end class TestMockTimeFunction()


def _setup_mock_log_capture(context: unittest.TestCase) -> None:
    """
    Set up log capture for the test context.

    :param context: unittest.TestCase: test context
    """
    # pylint:disable=protected-access
    context._log_handler = ListHandler()
    context.mogger: logging.Logger = setup_logger(
        MOCK_LOGGER
    )  # type:ignore # mocking logger
    context._log_handler.log_only_to_me(context.mogger)


def _teardown_mock_log_capture(context: unittest.TestCase) -> None:
    """
    Clean up log capture for the test context.

    :param context: unittest.TestCase: test context
    """
    # pylint:disable=protected-access
    assert isinstance(context._log_handler, ListHandler)
    context.mogger.removeHandler(context._log_handler)


def _reset_mock_log_capture(context: unittest.TestCase) -> None:
    """
    Reset log capture for the test context.

    :param context: unittest.TestCase: test context
    """
    # pylint:disable=protected-access
    context.mogger.setLevel(logging.DEBUG)  # pylint:disable=no-member
    context._log_handler.log_records.clear()


if __name__ == "__main__":
    unittest.main()

mock_cleanup()
