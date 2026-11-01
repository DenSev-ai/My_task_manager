"""Tests for ui/datetime_picker.py."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ui.datetime_picker import (
    add_minutes,
    format_local_datetime,
    local_to_utc,
    utc_to_local,
)


class TestDateTimeConversions(unittest.TestCase):
    def test_local_to_utc_round_trip(self) -> None:
        local_dt = datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc)
        utc_dt = local_to_utc(local_dt)
        back = utc_to_local(utc_dt)
        self.assertEqual(back, local_dt)

    def test_naive_local_rejected(self) -> None:
        naive = datetime(2026, 11, 2, 15, 30)
        with self.assertRaises(ValueError):
            local_to_utc(naive)

    def test_naive_utc_rejected(self) -> None:
        naive = datetime(2026, 11, 2, 15, 30)
        with self.assertRaises(ValueError):
            utc_to_local(naive)

    def test_add_minutes(self) -> None:
        utc_dt = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        result = add_minutes(utc_dt, 15)
        self.assertEqual(result, datetime(2026, 11, 2, 12, 15, tzinfo=timezone.utc))

    def test_add_minutes_rejects_naive(self) -> None:
        naive = datetime(2026, 11, 2, 12, 0)
        with self.assertRaises(ValueError):
            add_minutes(naive, 5)

    def test_format_local_datetime(self) -> None:
        local_dt = datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc)
        self.assertEqual(format_local_datetime(local_dt), "02.11.2026 15:30")


if __name__ == "__main__":
    unittest.main()
