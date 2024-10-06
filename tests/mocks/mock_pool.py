# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Mock code to simulate Socket and SocketPool classes with the functionality needed for
testing adafruit_ntp.

Usage:
    from tests.mock_pool import MockPool, MockCallback, MockSocket
    mock_pool = MockPool()
    mock_pool.mock_getaddrinfo_attempts.clear()
    mock_pool.set_getaddrinfo_responses([«exceptions and values»])
    mock_socket = mock_pool.socket(mock_pool.AF_INET, mock_pool.SOCK_DGRAM)
    mock_socket.mock_recv_into_attempts.clear()
    mock_socket.mock_sendto_attempts.clear()
    mock_socket.set_recv_into_responses([«exceptions and values»])
    mock_socket.set_sendto_responses([«exceptions and values»])

    ntp = NTP(mock_pool)

    Values in the response lists will be used (popped) one at a time for each call to
    getaddrinfo and recv_into. The value will be raised if it is an Exception, or returned
    if it is not. This allows multiple responses to be queued for cases where the application
    being tested could make multiple calls before exiting back to the testing code.
"""

try:
    from typing import Tuple, Union, Dict, List

    GetAddressInfoT = Tuple[int, int, int, str, Tuple[str, int]]
except ImportError:
    pass
from micropython import const  # type:ignore
from tests.shared_for_testing import (
    ResourcesDepletedError,
    setup_logger,
    MOCK_LOGGER,
    MOCKED_SOCK_NEW_MSG,
    MOCKED_SOCK_INITIALIZED_MSG,
    MOCKED_SOCK_INIT_MSG,
    MOCKED_SOCK_ENTER_MSG,
    MOCKED_SOCK_EXIT_MSG,
    MOCKED_SOCK_SETTIMEOUT_MSG,
    MOCKED_SOCK_SENDTO_MSG,
    MOCKED_SOCK_RECV_INTO_MSG,
    MOCKED_SOCK_CLOSE_MSG,
    MOCKED_SOCK_SUPER_MSG,
    MOCKED_POOL_NEW_MSG,
    MOCKED_POOL_INITIALIZED_MSG,
    MOCKED_POOL_INIT_MSG,
    MOCKED_POOL_INIT_CLEARED_MSG,
    MOCKED_POOL_GETADDR_MSG,
    MOCKED_POOL_SOCKET_MSG,
    MOCKED_NO_RESOURCE_MSG,
    MOCKED_CALLBACK_MSG,
)

_logger = setup_logger(MOCK_LOGGER)


class MockSocket:
    """Mock Socket for testing NTP

    Use set_recv_into_responses in unittests to configure recv_into behaviour for an
    individual instance. Only a single instance will be created (enforced by the singleton
    pattern in __new__) for each unique combination of the family, type, and proto arguments.
    That allows the controlling unittest code to configure an instance for the arguments that
    the application will use, and then the application will get that same instance.
    """

    _instances: Dict[Tuple[int, int, int], "MockSocket"] = {}

    def __new__(
        cls, family: int, type: int, proto: int, *args, **kwargs
    ):  # pylint:disable=redefined-builtin
        """Control the creation of instances to enforce singleton pattern."""
        key = (family, type, proto)
        _logger.info(MOCKED_SOCK_NEW_MSG % (key,))
        if key not in cls._instances:
            _logger.info(MOCKED_SOCK_SUPER_MSG % (key,))
            cls._instances[key] = super(MockSocket, cls).__new__(cls, *args, **kwargs)
        return cls._instances[key]

    def __init__(
        self, family: int, type: int, proto: int
    ):  # pylint:disable=redefined-builtin
        """simulate Socket"""
        if not hasattr(self, "_mock_initialized"):
            self.family = family
            self.type = type
            self.proto = proto
            self.timeout = None
            self.mock_recv_into_attempts: List[Union[Exception, bytearray]] = []
            self.mock_sendto_attempts: List[Union[Exception, int]] = []
            self.mock_send_packet: List[bytearray] = []
            _logger.info(MOCKED_SOCK_INITIALIZED_MSG % (self.mock_key,))
            self._mock_initialized = (
                True  # Prevent re-initialization after setup by test case
            )
        _logger.info(MOCKED_SOCK_INIT_MSG % (self.mock_key,))

    def __enter__(self):
        """simulate Socket.__enter__. For use as a context manager"""
        _logger.info(MOCKED_SOCK_ENTER_MSG % (self.mock_key,))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """simulate Socket.__exit__. For use as a context manager"""
        _logger.info(MOCKED_SOCK_EXIT_MSG % (self.mock_key,))

    def settimeout(self, timeout: int) -> None:
        """simulate Socket.settimeout"""
        _logger.info(MOCKED_SOCK_SETTIMEOUT_MSG, timeout, self.mock_key)
        self.timeout = timeout

    def set_recv_into_responses(
        self, responses: List[Union[Exception, bytearray]]
    ) -> None:
        """Set a sequence of responses for the recv_into method."""
        self.mock_recv_into_attempts = responses

    def set_sendto_responses(self, responses: List[Union[Exception, int]]) -> None:
        """Set a sequence of responses for the sendto method."""
        self.mock_sendto_attempts = responses

    def sendto(self, packet: bytearray, address: Tuple[str, int]) -> int:
        """simulate Socket.sendto. Sending packet to NTP server address.

        Only expected to be single call to sendto from the application. More will continue
        to append to the mock_send_packet bytearray, so make sure that is cleaned up before
        the application tries to reuse it with recv_into.
        """
        _logger.info(MOCKED_SOCK_SENDTO_MSG, address, self.mock_key)
        if not self.mock_sendto_attempts:
            raise ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "sendto")
        result: Union[Exception, int] = self.mock_sendto_attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        self.mock_send_packet.append(packet[:])  # better alternative?
        return result

    def recv_into(self, packet: bytearray) -> int:
        """simulate Socket.recv_into. Receiving packet from NTP server"""
        _logger.info(MOCKED_SOCK_RECV_INTO_MSG % (self.mock_key,))
        if not self.mock_recv_into_attempts:
            raise ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "recv_into")
        result: Union[Exception, bytearray] = self.mock_recv_into_attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        packet[:] = result
        return len(packet)

    def close(self) -> None:
        """simulate Socket.close. Receiving packet from NTP server"""
        _logger.info(MOCKED_SOCK_CLOSE_MSG % (self.mock_key,))

    @property
    def mock_key(self) -> Tuple[int, int, int]:
        """Return a key for the instance based on the family, type, and proto attributes"""
        return (self.family, self.type, self.proto)

    @classmethod
    def get_mock_instance(cls) -> Dict[Tuple[int, int, int], "MockSocket"]:
        """Get the singleton instance dict for MockSocket."""
        return MockSocket._instances

    @classmethod
    def clear_mock_singleton(cls) -> None:
        """Testing interface to reset the singleton to 'empty'"""
        cls._instances.clear()


class MockPool:
    """Singleton class to hold the state of the mock socketPool.

    Use set_getaddrinfo_responses in unittests to configure getaddrinfo behaviour.
    """

    AF_INET: int = const(2)
    SOCK_DGRAM: int = const(2)
    SOCK_STREAM: int = const(1)
    IPPROTO_IP: int = const(0)

    _instance: "MockPool" = None

    def __new__(cls, *args, **kwargs):
        _logger.debug(MOCKED_POOL_NEW_MSG)
        if cls._instance is None:
            _logger.debug(MOCKED_POOL_INITIALIZED_MSG)
            cls._instance = super(MockPool, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        # not really needed for the singleton setup, but define the attributes here (as well),
        # so pylint doesn't complain about attributes defined outside of init
        _logger.debug(MOCKED_POOL_INIT_MSG)
        if not hasattr(self, "_mock_initialized"):
            _logger.debug(MOCKED_POOL_INIT_CLEARED_MSG)
            self.mock_getaddrinfo_attempts: List[Union[Exception, GetAddressInfoT]] = []
            self._mock_initialized = (
                True  # Prevent re-initialization after setup by test case
            )

    def getaddrinfo(
        self, server: str, port: int
    ) -> Tuple[int, int, int, str, Tuple[str, int]]:
        """simulate SocketPool.getaddrinfo"""
        _logger.info(MOCKED_POOL_GETADDR_MSG, server, port)
        if not self.mock_getaddrinfo_attempts:
            raise ResourcesDepletedError(MOCKED_NO_RESOURCE_MSG % "getaddrinfo")
        result: Union[Exception, GetAddressInfoT] = self.mock_getaddrinfo_attempts.pop(
            0
        )
        if isinstance(result, Exception):
            raise result
            # SocketPool.gaierror((-2, 'Name or service not known'))
        return result

    @staticmethod
    def socket(
        family: int = AF_INET,
        type: int = SOCK_STREAM,  # pylint:disable=redefined-builtin
        proto: int = IPPROTO_IP,
    ) -> MockSocket:
        """simulate SocketPool.socket"""
        _logger.info(MOCKED_POOL_SOCKET_MSG % (family, type, proto))
        return MockSocket(family, type, proto)

    def set_getaddrinfo_responses(
        self, responses: List[Union[Exception, GetAddressInfoT]]
    ) -> None:  # type:ignore
        """Set a sequence of responses for the getaddrinfo method."""
        self.mock_getaddrinfo_attempts = responses

    @classmethod
    def get_mock_instance(cls) -> "MockPool":
        """Get the singleton instance of MockPool without going through instantiation."""
        if MockPool._instance is None:
            raise AttributeError(
                "No MockPool instance currently exists. Call MockPool() first."
            )
        return MockPool._instance

    @classmethod
    def clear_mock_singleton(cls) -> None:
        """Testing interface to reset the singleton to 'undefined'"""
        cls._instance = None


class MockCallback:
    """Mock notification callback for testing NTP."""

    def __init__(self, context: str):
        self.context = context

    def mock_callback(self, event: int, delay: int) -> None:
        """Log which callback was called, and the triggering event details"""
        event_num = event if isinstance(event, int) else event.value
        if event_num == 0:
            _logger.debug(MOCKED_CALLBACK_MSG % (self.context, event, delay))
            return
        _logger.info(MOCKED_CALLBACK_MSG % (self.context, event, delay))
