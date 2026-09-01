"""Tests for parsing Garmin's ``startTimeGMT`` field.

Garmin formats that field inconsistently. The old code appended ``+00:00``
after blindly dropping the last character, which turned ``2024-08-26T07:28:34.0``
into ``2024-08-26T07:28:34.+00:00`` and made the whole activity summary fail:

    Failed to get activity summary 16863226120:
    Invalid isoformat string: '2024-08-26T07:28:34.+00:00'

A failed summary is silent data loss — the downloaded GPX then carries no
distance, heart rate or start/end time in its extensions block.
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_page"))

from run_page.garmin_sync import parse_garmin_start_time

EXPECTED = dt.datetime(2024, 8, 26, 7, 28, 34, tzinfo=dt.timezone.utc)


class ParseGarminStartTimeTest(unittest.TestCase):
    def test_single_digit_fraction(self):
        """The exact string that broke activity 16863226120."""
        self.assertEqual(parse_garmin_start_time("2024-08-26T07:28:34.0"), EXPECTED)

    def test_millisecond_fraction(self):
        self.assertEqual(parse_garmin_start_time("2024-08-26T07:28:34.000"), EXPECTED)

    def test_trailing_zulu(self):
        self.assertEqual(parse_garmin_start_time("2024-08-26T07:28:34.0Z"), EXPECTED)

    def test_no_fraction(self):
        self.assertEqual(parse_garmin_start_time("2024-08-26T07:28:34"), EXPECTED)

    def test_empty_fraction(self):
        self.assertEqual(parse_garmin_start_time("2024-08-26T07:28:34."), EXPECTED)

    def test_space_instead_of_t(self):
        self.assertEqual(parse_garmin_start_time("2024-08-26 07:28:34"), EXPECTED)

    def test_surrounding_whitespace(self):
        self.assertEqual(parse_garmin_start_time(" 2024-08-26T07:28:34.0 "), EXPECTED)

    def test_fraction_longer_than_microseconds_is_truncated(self):
        """fromisoformat caps at 6 digits; Garmin has been seen sending more."""
        self.assertEqual(
            parse_garmin_start_time("2024-08-26T07:28:34.123456789"),
            EXPECTED.replace(microsecond=123456),
        )

    def test_result_is_utc_aware(self):
        """Downstream adds a timedelta and calls isoformat(), so tzinfo matters."""
        parsed = parse_garmin_start_time("2024-08-26T07:28:34.0")
        self.assertEqual(parsed.tzinfo, dt.timezone.utc)
        self.assertEqual(
            (parsed + dt.timedelta(seconds=90)).isoformat(),
            "2024-08-26T07:30:04+00:00",
        )


if __name__ == "__main__":
    unittest.main()
