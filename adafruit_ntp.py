# SPDX-FileCopyrightText: 2022 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_ntp`
================================================================================

Network Time Protocol (NTP) helper for CircuitPython

 * Author(s): Scott Shawcroft, H Phil Duby

Implementation Notes
--------------------
**Hardware:**
**Software and Dependencies:**

 * Adafruit CircuitPython firmware for the supported boards:
   https://github.com/adafruit/circuitpython/releases

"""
from errno import ETIMEDOUT
import struct
import time

try:
    from time import gmtime as localtime  # use gmtime with CPython
except ImportError:
    from time import localtime  # gmtime not available in CircuitPython
try:
    import socket as SocketPool
except ImportError:
    from socketpool import SocketPool  # type:ignore
try:
    from micropython import const
    import circuitpython_typing
except ImportError:
    pass
try:
    from typing import Callable, Optional, Tuple, Dict
except ImportError:
    pass
try:
    from typing import Protocol
except ImportError:
    try:
        from typing_extensions import Protocol
    except ImportError:
        Protocol = None
if Protocol is not None:

    class SocketProtocol(Protocol):
        """
        Interface for socket needed by NTP class. Allow IDE static type checking and auto
        complete.
        """

        # pylint:disable=redefined-builtin,missing-function-docstring
        def settimeout(self, seconds: int) -> None: ...
        def sendto(
            self, bytes: circuitpython_typing.ReadableBuffer, address: Tuple[str, int]
        ) -> int: ...
        def recv_into(
            self, buffer: circuitpython_typing.WriteableBuffer, bufsize: int
        ) -> int: ...


__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_NTP.git"

NTP_TO_UNIX_EPOCH: int = 2_208_988_800  # 1900-01-01 00:00:00 to 1970-01-01 00:00:00
NS_PER_SEC: int = 1_000_000_000
PACKET_SIZE: int = 48


class EventType:  # pylint:disable=too-few-public-methods
    """NTP callback notification Event Types."""

    NO_EVENT = const(0b000)
    SYNC_COMPLETE = const(0b001)
    SYNC_FAILED = const(0b010)  # get packet failed
    LOOKUP_FAILED = const(0b100)  # getaddrinfo failed (not timedout?)
    ALL_EVENTS = const(0b111)


class NTPIncompleteError(TimeoutError):
    """
    Indicates that NTP synchronization has not yet completed successfully.

    Raised when an NTP operation cannot complete in non-blocking mode or during retries.
    This exception represents transient errors and partial progress. Further NTP calls will
    retry or continue to the next step.
    """


class NTP:  # pylint:disable=too-many-instance-attributes
    """Network Time Protocol (NTP) helper module for CircuitPython.
    This module does not handle daylight savings or local time. It simply requests
    UTC from an NTP server.

    This class uses a simple state machine to manage synchronization:
    - USING_CACHED_REFERENCE (state 3): The default state where the cached time reference is used.

       - Transitions to GETTING_SOCKET when the cache expires.

    - GETTING_SOCKET (state 1): Attempts to perform a DNS lookup for the NTP server.

       - Transitions to GETTING_PACKET on success.
       - Remains in this state if retries are needed.

    - GETTING_PACKET (state 2): Sends an NTP request and waits for the response.

       - Transitions back to USING_CACHED_REFERENCE.

    - On failure, any existing cached value will continue to be used until the next scheduled
      synchronization.

    The state transitions are managed by the ``_update_time_sync`` method, which is called if
    the cached time is expired when ``utc_ns`` is accessed.
    """

    # State machine values
    GETTING_SOCKET: int = const(1)  # To have getting packet
    GETTING_PACKET: int = const(2)  # To cached
    USING_CACHED_REFERENCE: int = const(3)  # To getting socket
    # Exponential retry backoff configuration
    FIRST_WAIT = int(3 * NS_PER_SEC)  # 3 seconds in nanoseconds
    """Time to wait before retry after first (network operation) failure."""
    MAX_WAIT = int(60 * NS_PER_SEC)  # maximum wait time in nanoseconds
    """Maximum time to wait before retry after a failure."""
    WAIT_FACTOR = 1.5  # multiplier for exponential backoff
    """Amount (multiplication factor) to increase the wait before retry after each failure."""

    MINIMUM_RETRY_DELAY: int = const(60)  # 60 seconds
    """A (specified or default) cache_seconds value of 0 is intended to mean using the NTP
    pooling interval returned by the server. However, that also means that no value is known
    until a successful synchronization. If the initial attempts get timeout errors,
    because the server is busy, that 0 value results in the already busy server (or network)
    getting pounded by an unbroken stream of retry requests. Limit that possibility."""

    def __init__(  # pylint:disable=too-many-arguments
        self,
        socketpool: SocketPool,
        *,
        server: str = "0.adafruit.pool.ntp.org",
        port: int = 123,
        tz_offset: float = 0,
        socket_timeout: int = 10,
        cache_seconds: int = 0,
        blocking: bool = True,
    ) -> None:
        """
        :param object socketpool: A socket provider such as CPython's `socket` module.
        :param str server: The domain (url) of the ntp server to query.
        :param int port: The port of the ntp server to query.
        :param float tz_offset: Timezone offset in hours from UTC. This applies to both timezone
                                ignorant CircuitPython and CPython. CPython is aware of timezones,
                                but this code uses methods that do not access that, to be
                                consistent with CircuitPython.
                                For example, Pacific daylight savings time is -7.
        :param int socket_timeout: UDP socket timeout, in seconds.
        :param int cache_seconds: How many seconds to use a cached result from NTP server
                                  (default 0, which respects NTP server's minimum).
        :param bool blocking: Determines whether the NTP operations should be blocking or
                              non-blocking.
        """
        self._pool: SocketPool = socketpool
        self._server: str = server
        self._port: int = port
        self._socket_address: Optional[Tuple[str, int]] = None
        self._packet = bytearray(PACKET_SIZE)
        self._tz_offset_ns = int(tz_offset * 60 * 60) * NS_PER_SEC
        self._socket_timeout: int = socket_timeout
        self._cache_ns: int = NS_PER_SEC * max(self.MINIMUM_RETRY_DELAY, cache_seconds)
        self._blocking: bool = blocking

        # State management

        # This is our estimated start time for the monotonic clock (ns since unix epoch).
        # We adjust it based on the ntp responses.
        self._monotonic_start_ns: int = 0
        self._next_sync: int = 0
        self._state: int = self.USING_CACHED_REFERENCE
        self._last_sync_time: int = 0  # Track the last successful sync time
        self._callbacks: Dict[Callable[[int, int], None], int] = {}
        # The variables _next_rate_limit_end and _next_rate_limit_delay are intentionally
        # not initialized here because they are only used after calling
        # _initialize_backoff_timing(). Accessing them before initialization will raise an
        # AttributeError, indicating a misuse of the class.
        self._next_rate_limit_end: int
        self._next_rate_limit_delay: int

    @property
    def datetime(self) -> time.struct_time:
        """
        Time (structure) based on NTP server time reference. Time synchronization is updated
        if the cache has expired.

        CircuitPython always expects to be working with UTC. CPython though will use its own
        notion of the current time zone when using localtime. To get those to be consistent,
        localtime is overridden (during import) to use gmtime when running in CPython. That
        way this should always return UTC based information.

        :returns time.struct_time: Current UTC time in seconds.
        """
        current_time_s = self.utc_ns // NS_PER_SEC  # seconds since unix epoch
        return localtime(current_time_s)

    @property
    def utc_ns(self) -> int:
        """UTC (unix epoch) time in nanoseconds based on NTP server time reference.
        Time synchronization updated if the cache has expired.

        :returns int: Integer number of nanoseconds since the unix epoch (1970-01-01 00:00:00).
        :raises NTPIncompleteError: if no NTP synchronization has been successful yet.
        """
        if time.monotonic_ns() > self._next_sync:
            self._update_time_sync()
        # if self._last_sync_time <= 0:
        if self._monotonic_start_ns <= 0:
            raise NTPIncompleteError("No NTP synchronization has been successful yet")
        return time.monotonic_ns() + self._monotonic_start_ns

    @property
    def blocking(self) -> bool:
        """Return the current blocking setting."""
        return self._blocking

    @blocking.setter
    def blocking(self, value: bool) -> None:
        """Update the current blocking mode setting"""
        self._blocking = value

    @property
    def since_sync_ns(self) -> int:
        """Return the duration in nanoseconds since the last successful synchronization."""
        if self._next_sync == 0:
            raise NTPIncompleteError("No NTP synchronization has been successful yet")
        return time.monotonic_ns() - self._last_sync_time

    @property
    def cache_ns(self) -> int:
        """Return the current cache value in nanoseconds."""
        return self._cache_ns

    def _update_time_sync(self) -> None:
        """
        Manage NTP synchronization state transition continue and retry logic.

        Handles synchronization by progressing through the following states:
        - USING_CACHED_REFERENCE: Initialized retry backoff timing.
        - GETTING_SOCKET: Perform DNS lookup for the NTP server.
        - GETTING_PACKET: Send NTP request and await response.
        """
        if self._state == self.USING_CACHED_REFERENCE:
            # Cached offset value expired, reinitialize backoff timing and proceed to DNS lookup.
            self._initialize_backoff_timing()
            self._state = self.GETTING_SOCKET
        if self._state == self.GETTING_SOCKET:
            # Attempt DNS lookup; if non-blocking, exit early.
            self._get_socket()
            if not self._blocking:
                return
        if self._state == self.GETTING_PACKET:
            self._get_ntp_packet()

    def _initialize_backoff_timing(self) -> None:
        """Initialize backoff timing values."""
        self._next_rate_limit_delay = self.FIRST_WAIT
        self._next_rate_limit_end = 0  # time.monotonic_ns

    def _get_socket(self) -> None:
        """Get the socket address for the NTP server."""
        now = time.monotonic_ns()
        if now < self._next_rate_limit_end:
            if not self._blocking:
                # Not blocking and a rate limiting delay is in progress, so no
                # operation to do currently.
                return
            # Wait here until the rate limiting delay has expired then continue.
            time.sleep((self._next_rate_limit_end - now) / NS_PER_SEC)
        self._server_dns_lookup()

    def _server_dns_lookup(self) -> None:
        """
        Get the IP address for the configured NTP server.

        In CircuitPython, exceptions raised during DNS lookup do not differentiate between
        connection problems and DNS failures. Therefore, we treat any exception here as a
        LOOKUP_FAILED event and rely on external logic, which may have more context
        information, to handle network connectivity.
        """
        try:
            # List[Tuple[int, int, int, str, Tuple[str, int]]]
            # List[Tuple[AddressFamily, SocketKind, int, str, Tuple[str, int]]]
            new_socket = self._pool.getaddrinfo(self._server, self._port)[0][4]
            self._socket_address = new_socket
            self._state = self.GETTING_PACKET
        except SocketPool.gaierror:
            self._exponential_lookup_retry_backoff()
            if self._blocking and self._last_sync_time <= 0:
                # Legacy blocking mode and do not have any fallback time sync offset. The caller
                # needs to handle the specific failure exception.
                raise
            # otherwise continue normally

    def register_ntp_event_callback(
        self,
        callback: Callable[[int, int], None],
        event_types: int = EventType.SYNC_COMPLETE,
    ) -> None:
        """
        Register a callback to be notified for specific NTP events.

        Callbacks can be used to turn off the radio to save power, initiate a network
        connection, or other progress monitoring processes.
        EG: ``wifi.radio.enabled = False`` or ``connection_manager.connect()``

        .. caution::

           This implementation does not prevent duplicate registration of the same callback.
           All attempts to consistently identify when a callback is already registered have
           failed due to the limitations of the current CircuitPython implementation. Comparing
           the callback value directly, converting to string using ``str()``, or ``repr()``, or to a
           number using ``id()`` all have cases where an identical callback reference will be
           treated as different.

           If the same callback is registered multiple times, with the same event type, it will
           be called multiple times when that event type occurs.

        :param Callable[[IntFlag, int], None] callback: The callback function to register.
        :param IntFlag event_types: The event types that should trigger this callback. This can
                                    be a single event type or a combination of multiple events.
                                    Defaults to ``EventType.SYNC_COMPLETE``.
        :raises TypeError: If the ``event_types`` argument is not a valid event type or combination
                           of event types.

        Usage examples::

            from adafruit_ntp import NTP, EventType
            ntp = NTP(socketpool)

            def on_sync_complete(event_type: IntFlag, next_time: int) -> None:
                print(f"{event_type.name} event: Next operation scheduled at {next_time} ns")

            # Default behavior, only triggers on sync complete
            ntp.register_ntp_event_callback(on_sync_complete)

            def on_ntp_event(event_type: IntFlag, next_time: int) -> None:
                if event_type == EventType.SYNC_COMPLETE:
                    print(f"Synchronization complete. Next sync at {next_time}")
                elif event_type == EventType.SYNC_FAILED:
                    print(f"Sync failed. Will retry at {next_time}")
                elif event_type == EventType.LOOKUP_FAILED:
                    print(f"DNS lookup failed, need to verify active network connection.")

            # Register a single callback for multiple events
            ntp.register_ntp_event_callback(on_ntp_event,
                EventType.SYNC_COMPLETE | EventType.SYNC_FAILED | EventType.LOOKUP_FAILED)
        """
        if not isinstance(event_types, int):
            raise TypeError(f"{type(event_types)} is not compatible with event types")
        if (
            EventType.ALL_EVENTS | event_types != EventType.ALL_EVENTS
            or event_types == 0
        ):
            raise TypeError(
                f"Invalid event type mask 0b{event_types:b}. "
                "Only known events can receive notifications."
            )
        self._callbacks[callback] = event_types

    def _notify_ntp_event_callbacks(
        self, event_type: int, next_operation_time: int
    ) -> None:
        """
        Call all registered callbacks that are interested in the given event type.

        :param IntFlag event_type: The type of event that occurred.
        :param int next_operation_time: The time (in nanoseconds) when the next operation is
            scheduled.
        """
        for callback, registered_events in self._callbacks.items():
            if event_type & registered_events:
                callback(event_type, next_operation_time)

    def _get_ntp_packet(self) -> None:
        """
        Send the NTP packet and process the response to synchronize the local clock.

        Adjusts the local clock based on server-provided timestamps.
        """
        # Prepare the NTP request packet: NTP version 4, Client mode, not leap second
        self._packet[0] = 0b00100011
        for i in range(1, PACKET_SIZE):
            self._packet[i] = 0

        # Open a socket to send the packet and receive the response
        with self._pool.socket(self._pool.AF_INET, self._pool.SOCK_DGRAM) as sock:
            have_packet, local_send_ns, local_recv_ns = self._get_raw_ntp(sock)
        if not have_packet:
            return

        # Extract server receive and send timestamps from the response packet
        srv_recv_ns, srv_send_ns = self._extract_ntp_timestamps()

        # Calculate the clock offset using the formula:
        # offset = (T2 + T3 - T4 - T1) / 2
        # where:
        # - T1: local_send_ns (time request sent)
        # - T2: srv_recv_ns (server received time)
        # - T3: srv_send_ns (server sent time)
        # - T4: local_recv_ns (time response received)
        # That offset aligns the midpoint of the local times with the midpoint of the server times.
        clock_offset = (srv_recv_ns + srv_send_ns - local_recv_ns - local_send_ns) // 2

        # Adjust local monotonic clock to synchronize with the NTP server time
        self._monotonic_start_ns = clock_offset + self._tz_offset_ns
        self._last_sync_time = local_recv_ns
        self._next_sync = local_recv_ns + self._cache_ns

        # Notify registered callbacks that synchronization has completed
        self._notify_ntp_event_callbacks(EventType.SYNC_COMPLETE, self._next_sync)

        # Transition back to using the cached reference
        self._state = self.USING_CACHED_REFERENCE

    def _get_raw_ntp(self, sock: SocketProtocol) -> Tuple[bool, int, int]:
        """Send the NTP packet and receive the response.

        Timing sensitive, so treat as a single operation.

        If a timeout occurs (errno == ETIMEDOUT), we handle it gracefully by scheduling the next
        sync attempt and notifying callbacks. Other exceptions are re-raised for the caller to
        handle.
        """
        packet_sent = False
        sock.settimeout(self._socket_timeout)
        local_send_ns = time.monotonic_ns()
        try:
            sock.sendto(self._packet, self._socket_address)
            packet_sent = True
            sock.recv_into(self._packet)
            # Get the internal clock time reference while still in the context to minimize
            # the difference between it and receiving the packet references.
            local_recv_ns = time.monotonic_ns()
        except OSError as ex:
            if isinstance(ex, BrokenPipeError):
                if packet_sent:
                    raise  # case not currently handled
                # notify as a lookup failure: ie got cached dns lookup when not connected
                self._state = self.GETTING_SOCKET
                self._exponential_lookup_retry_backoff()
                if self._blocking and self._last_sync_time <= 0:
                    # Legacy blocking mode and do not have any fallback time sync offset. The
                    # caller needs to handle the specific failure exception.
                    raise
                # otherwise abort the rest of the NTP attempt, and continue when next called.
                return (False, -1, -1)

            if not packet_sent:
                raise  # other errors not expected for sendto. Not handled here
            self._next_sync = time.monotonic_ns() + self._cache_ns
            self._state = self.USING_CACHED_REFERENCE
            self._notify_ntp_event_callbacks(EventType.SYNC_FAILED, self._next_sync)
            if ex.errno == ETIMEDOUT:
                return (False, -1, -1)
            raise
        return True, local_send_ns, local_recv_ns

    def _extract_ntp_timestamps(self) -> Tuple[int, int]:
        """Extract the receive and send timestamps from the NTP packet."""
        srv_recv_s, srv_recv_f = struct.unpack_from("!II", self._packet, offset=32)
        srv_send_s, srv_send_f = struct.unpack_from("!II", self._packet, offset=40)

        srv_recv_ns = (srv_recv_s - NTP_TO_UNIX_EPOCH) * NS_PER_SEC + (
            srv_recv_f * NS_PER_SEC // 2**32
        )
        srv_send_ns = (srv_send_s - NTP_TO_UNIX_EPOCH) * NS_PER_SEC + (
            srv_send_f * NS_PER_SEC // 2**32
        )
        return srv_recv_ns, srv_send_ns

    def _exponential_lookup_retry_backoff(self) -> None:
        """
        Setup when the next lookup retry should occur due to a DNS lookup failure, or a
        BrokenPipeError failure sending the NTP information request.

        This implementation uses an exponential backoff strategy with a maximum wait time
        """
        # Configure next rate limiting delay period. This 'should' be the same regardless
        # of any processing based on the detected specific exception case.
        self._next_rate_limit_end = time.monotonic_ns() + self._next_rate_limit_delay
        self._next_rate_limit_delay = min(
            self.MAX_WAIT, int(self._next_rate_limit_delay * self.WAIT_FACTOR)
        )
        # It does not seem possible to separate connection problems and DNS lookup failures
        # in circuitpython. Notify as a lookup failure, but any notified external functionality
        # should initially treat it as a connection problem, then ignore it, if it determines
        # that a network connection is already available.
        self._notify_ntp_event_callbacks(
            EventType.LOOKUP_FAILED, self._next_rate_limit_end
        )
