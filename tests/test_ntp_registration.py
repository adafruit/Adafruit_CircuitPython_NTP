# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Unittests for registration functionality of NTP instances from adafruit_ntp
"""

import unittest

import adafruit_logging as logging
from tests.shared_for_testing import (
    ListHandler,
    get_context_exception,
    mock_info,
    setup_logger,
    mock_cleanup,
    MOCK_LOGGER,
    BAD_EVENT_MASK_MSG,
    MOCKED_CALLBACK_MSG,
)
from tests.mocks.mock_pool import MockPool, MockCallback  # , MockSocket

# ntp_testing_support overrides sys.modules['time']. Make sure anything that needs
# the real time module is imported first.
from tests.ntp_testing_support import (
    NTP,
    verify_generic_expected_state_and_log,
    DEFAULT_NTP_STATE,
)
from adafruit_ntp import EventType


class TestNTPRegistrations(unittest.TestCase):
    """Test registration functionality of NTP instances."""

    _log_handler: ListHandler = None
    mogger: logging.Logger = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources."""
        cls.mock_pool = MockPool()
        cls.mogger: logging.Logger = setup_logger(MOCK_LOGGER)  # mocking logger
        cls._log_handler = ListHandler()
        cls._log_handler.log_only_to_me(cls.mogger)

    @classmethod
    def tearDownClass(cls):
        """Clean up class-level resources."""
        cls.mogger.removeHandler(cls._log_handler)
        MockPool.clear_mock_singleton()

    def setUp(self):
        """Common initialization for each test method."""
        self.ntp = NTP(self.mock_pool)
        self.mogger.setLevel(logging.INFO)  # pylint:disable=no-member
        self._log_handler.log_records.clear()

    def tearDown(self):
        """Clean up after each test."""

    def test_initialization(self):  # pylint:disable=invalid-name
        """Test NTP initialization."""
        self.assertIsNotNone(self.ntp)
        expected_state = DEFAULT_NTP_STATE.copy()
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP state fields %s do not match the expected default",
            "There should not be any log records generated during initialization; got: %s",
        )

    def test_no_notifications(self):  # pylint:disable=invalid-name
        """Test _notify_callbacks private method without any registered callbacks.

        The _notify_callbacks does not, and does not need to, verify that only expected events
        are being notified. The calling code is responsible for making sure that only 'real'
        events are being triggered.
        """
        # Calling the private _notify_callbacks method directly. NTP instance state should
        # not matter, and should not be changed. The Event(s) registered should not make a
        # difference to that either.
        expected_state = DEFAULT_NTP_STATE.copy()
        # pylint:disable=protected-access
        self.ntp._notify_ntp_event_callbacks(EventType.SYNC_COMPLETE, 1000)
        self.ntp._notify_ntp_event_callbacks(EventType.SYNC_FAILED, 1001)
        self.ntp._notify_ntp_event_callbacks(EventType.LOOKUP_FAILED, 1002)
        self.ntp._notify_ntp_event_callbacks(EventType.NO_EVENT, 1003)
        self.ntp._notify_ntp_event_callbacks(EventType.ALL_EVENTS, 1004)
        self.ntp._notify_ntp_event_callbacks(127, 1005)
        self.ntp._notify_ntp_event_callbacks(128, 1006)
        # pylint:enable=protected-access
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP state fields %s do not match the expected default",
            "No notification log records should be generated; got: %s",
        )

    def test_register_good_notification(self):  # pylint:disable=invalid-name
        """Test registering a callback for valid events."""
        context1 = "c1"
        callback1 = MockCallback(context1)
        self.ntp.register_ntp_event_callback(
            callback1.mock_callback, EventType.SYNC_COMPLETE
        )
        expected_state = DEFAULT_NTP_STATE.copy()
        expected_state.callbacks[callback1.mock_callback] = EventType.SYNC_COMPLETE
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP(1) state fields %s do not match expected",
            "Registering a callback should not add any log records; got: \n%s",
        )

        context2 = "c2"
        callback2 = MockCallback(context2)
        self.ntp.register_ntp_event_callback(
            callback2.mock_callback, EventType.SYNC_FAILED
        )
        expected_state.callbacks[callback2.mock_callback] = EventType.SYNC_FAILED
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP(2) state fields %s do not match expected",
            "Registering callback2 should not add any log records; got: \n%s",
        )

        context3 = "c3"
        callback3 = MockCallback(context3)
        self.ntp.register_ntp_event_callback(callback3.mock_callback, 0b111)
        expected_state.callbacks[callback3.mock_callback] = EventType.ALL_EVENTS
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP(3) state fields %s do not match expected",
            "Registering callback3 should not add any log records; got: \n%s",
        )

        test_delay = 13579
        """Any legitimate unique delay amount, just to verify that the value is passed
        to the notification."""

        expected_log = (
            mock_info(
                MOCKED_CALLBACK_MSG % (context1, EventType.SYNC_COMPLETE, test_delay)
            ),
            mock_info(
                MOCKED_CALLBACK_MSG % (context3, EventType.SYNC_COMPLETE, test_delay)
            ),
        )
        # print(f'\n{len(self._log_handler.log_records) =}, {len(self._log_handler.to_tuple()) =}')
        self.ntp._notify_ntp_event_callbacks(  # pylint:disable=protected-access
            EventType.SYNC_COMPLETE, test_delay
        )
        # Triggering notifications should generate log records, but the order for a single event is
        # not deterministic.  When a single event results in multiple notifications, they could be
        # in any order. Sort the log records for comparison purposes.
        self.assertEqual(
            tuple(sorted(self._log_handler.to_tuple(), key=lambda x: x[3])),
            expected_log,
            "Sync complete notification should generate these log records:\n"
            f"{expected_log}; got: \n{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        test_delay = 15793
        """Any legitimate unique delay amount, just to verify that the value is passed
        to the notification."""
        expected_log = (
            mock_info(
                MOCKED_CALLBACK_MSG % (context3, EventType.LOOKUP_FAILED, test_delay)
            ),
        )
        self.ntp._notify_ntp_event_callbacks(  # pylint:disable=protected-access
            EventType.LOOKUP_FAILED, test_delay
        )
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            expected_log,
            "NTP(x) state fields %s changed unexpectedly",
            "Lookup failed notification should generate this log record:\n%s; got: \n%s",
        )
        self._log_handler.log_records.clear()

        test_delay = 79153
        """Any legitimate unique delay amount, just to verify that the value is passed
        to the notification."""
        expected_log = (
            mock_info(
                MOCKED_CALLBACK_MSG % (context2, EventType.SYNC_FAILED, test_delay)
            ),
            mock_info(
                MOCKED_CALLBACK_MSG % (context3, EventType.SYNC_FAILED, test_delay)
            ),
        )
        self.ntp._notify_ntp_event_callbacks(  # pylint:disable=protected-access
            EventType.SYNC_FAILED, test_delay
        )
        self.assertEqual(
            tuple(sorted(self._log_handler.to_tuple(), key=lambda x: x[3])),
            expected_log,
            "Sync failed notification should generate these log records:\n"
            f"{expected_log}; got: \n{self._log_handler.to_tuple()}",
        )
        self._log_handler.log_records.clear()

        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP state fields %s do not match expected after notifications",
            "Log records should have been cleared; got: \n%s",
        )

    def test_register_bad_int_notification(self):  # pylint:disable=invalid-name
        """Test registering a callback for an invalid (too big) event."""
        callback = MockCallback("bad1")
        bad_mask = 0b11111111
        self._verify_bad_notification(bad_mask, callback)

    def test_register_bad_int_zero_notification(self):  # pylint:disable=invalid-name
        """Test registering a callback for an invalid zero event."""
        callback = MockCallback("bad1a")
        bad_mask = 0
        self._verify_bad_notification(bad_mask, callback)

    def _verify_bad_notification(self, bad_mask: int, callback: MockCallback) -> None:
        """Verify an invalid register does not change instance state or generate any log records."""
        type_error = TypeError(BAD_EVENT_MASK_MSG % f"{bad_mask:b}")
        with self.assertRaises(type(type_error)) as context:
            self.ntp.register_ntp_event_callback(callback.mock_callback, bad_mask)
        exc_data = get_context_exception(context)
        self.assertEqual(repr(exc_data), repr(type_error))

        expected_state = DEFAULT_NTP_STATE.copy()
        verify_generic_expected_state_and_log(
            self,
            expected_state,
            (),
            "NTP state fields %s do not match expected",
            "Failing to registering a callback should not add any log records; got:\n %s",
        )


# end class TestNTPRegistrations()


if __name__ == "__main__":
    unittest.main()

mock_cleanup()
