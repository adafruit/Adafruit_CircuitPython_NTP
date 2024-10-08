# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Unittests for the EventType class used by adafruit_ntp. This is an emulated enum, based on
a custom IntFlag class which allows bitwise operations on the event types.
"""

import unittest
from tests.shared_for_testing import mock_cleanup
from adafruit_ntp import EventType


class TestEventType(unittest.TestCase):
    """Unittests for the EventType (emulated enum) class based on the custom IntFlag."""

    def test_basic_event_types(self):
        """Test basic event types and their values."""
        self.assertEqual(EventType.NO_EVENT, 0b000)  # 0
        self.assertEqual(EventType.SYNC_COMPLETE, 0b001)  # 1
        self.assertEqual(EventType.SYNC_FAILED, 0b010)  # 2
        self.assertEqual(EventType.LOOKUP_FAILED, 0b100)  # 4
        self.assertEqual(EventType.ALL_EVENTS, 0b111)  # 7

    def test_event_combination(self):
        """Test bitwise OR combination of event types."""
        combined_event = EventType.SYNC_COMPLETE | EventType.LOOKUP_FAILED
        self.assertEqual(combined_event, 0b101)  # 1 | 4 = 5

        combined_event = EventType.SYNC_COMPLETE | EventType.SYNC_FAILED
        self.assertEqual(combined_event, 0b011)  # 1 | 2 = 3

        combined_event = EventType.SYNC_FAILED | EventType.LOOKUP_FAILED
        self.assertEqual(combined_event, 0b110)  # 2 | 4 = 6

    def test_event_intersection(self):
        """Test bitwise AND intersection of event types."""
        combined_event = EventType.SYNC_COMPLETE | EventType.LOOKUP_FAILED
        intersect_event = combined_event & EventType.SYNC_COMPLETE
        self.assertEqual(intersect_event, 0b001)  # 5 & 1 = 1

        intersect_event = combined_event & EventType.SYNC_FAILED
        self.assertEqual(intersect_event, 0b000)  # 5 & 2 = 0

    def test_event_complement(self):
        """Test bitwise NOT complement of event types."""
        complement_event = (~EventType.SYNC_COMPLETE) & 0b111
        # Expected to be the bitwise complement of SYNC_COMPLETE within the range of all flags
        expected_value = 2 | EventType.SYNC_FAILED | EventType.LOOKUP_FAILED
        self.assertEqual(complement_event, expected_value)
        self.assertNotEqual(complement_event, EventType.SYNC_COMPLETE)
        self.assertEqual(complement_event & EventType.SYNC_COMPLETE, 0b000)
        self.assertEqual(complement_event & EventType.SYNC_COMPLETE, EventType.NO_EVENT)

    def test_event_equality(self):
        """Test equality between event types."""
        event1 = EventType.SYNC_COMPLETE
        event2 = EventType.SYNC_COMPLETE
        self.assertEqual(event1, event2)

    def test_event_xor(self):
        """Test bitwise XOR operation of event types."""
        xor_event = EventType.SYNC_COMPLETE ^ EventType.SYNC_FAILED
        self.assertEqual(xor_event, 0b011)  # 1 ^ 2 = 3

        xor_event = EventType.SYNC_COMPLETE ^ EventType.SYNC_COMPLETE
        self.assertEqual(xor_event, 0b000)  # 1 ^ 1 = 0

    def test_event_to_bool(self):
        """Test conversion of event types to bool."""
        self.assertTrue(bool(EventType.SYNC_COMPLETE))
        self.assertFalse(bool(EventType.NO_EVENT))


if __name__ == "__main__":
    unittest.main()

mock_cleanup()
