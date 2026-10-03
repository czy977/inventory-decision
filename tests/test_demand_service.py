"""Tests for the historical demand estimation service."""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.demand_service import DemandEstimate, estimate_daily_demand


ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = ROOT / "data" / "inventory.db"
AUDIT_PATH = ROOT / "reports" / "demand_audit_detail.csv"


class DemandServiceKnownResultTests(unittest.TestCase):
    def assert_result(
        self,
        sku_id: int,
        as_of_date: str,
        estimate: float | None,
        confidence: str,
        window_days: int,
        in_stock_days: int,
        manual_review: bool,
    ) -> None:
        result = estimate_daily_demand(sku_id, as_of_date, db_path=DATABASE_PATH)
        self.assertIsInstance(result, DemandEstimate)
        self.assertEqual(result.sku_id, sku_id)
        self.assertEqual(result.as_of_date, as_of_date)
        self.assertEqual(result.estimated_daily_demand, estimate)
        self.assertEqual(result.demand_confidence, confidence)
        self.assertEqual(result.demand_window_days, window_days)
        self.assertEqual(result.in_stock_days_used, in_stock_days)
        self.assertEqual(result.manual_review_required, manual_review)

    def test_sku_851_high_confidence_14_day_result(self) -> None:
        self.assert_result(851, "2024-06-25", 1.90, "High", 14, 14, False)

    def test_sku_834_low_confidence_extended_result(self) -> None:
        self.assert_result(834, "2024-05-15", 1.85, "Low", 30, 12, False)

    def test_sku_44_insufficient_result(self) -> None:
        self.assert_result(
            44, "2024-05-01", None, "Insufficient Data", 30, 0, True
        )

    def test_sku_44_medium_confidence_14_day_result(self) -> None:
        self.assert_result(44, "2024-06-25", 1.70, "Medium", 14, 8, False)

    def test_all_25_prior_audit_results(self) -> None:
        with AUDIT_PATH.open(newline="", encoding="utf-8") as handle:
            audit_rows = list(csv.DictReader(handle))

        self.assertEqual(len(audit_rows), 25)
        for row in audit_rows:
            result = estimate_daily_demand(
                int(row["sku_id"]), row["as_of_date"], db_path=DATABASE_PATH
            )
            expected_estimate = (
                None
                if row["estimated_daily_demand"] == ""
                else float(row["estimated_daily_demand"])
            )
            # The current specification explicitly records the final 30-day
            # check for Insufficient Data; the older audit CSV left it blank.
            expected_window = (
                30
                if row["demand_confidence"] == "Insufficient Data"
                else int(row["demand_window_days"])
            )
            if expected_estimate is None:
                self.assertIsNone(result.estimated_daily_demand)
            else:
                self.assertIsNotNone(result.estimated_daily_demand)
                self.assertAlmostEqual(
                    result.estimated_daily_demand, expected_estimate, places=12
                )
            self.assertEqual(result.demand_confidence, row["demand_confidence"])
            self.assertEqual(result.demand_window_days, expected_window)
            self.assertEqual(result.in_stock_days_used, int(row["in_stock_days_used"]))
            self.assertEqual(
                result.manual_review_required,
                row["manual_review_required"] == "True",
            )


class DemandServiceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "boundary.db"
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """
            CREATE TABLE sales_history (
                sku_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                sale_amount REAL NOT NULL,
                stock_hour6_22_cnt INTEGER NOT NULL,
                UNIQUE (sku_id, date)
            )
            """
        )

        as_of = date(2024, 6, 25)
        rows: list[tuple[int, str, float, int]] = []
        for offset in range(14, 0, -1):
            row_date = as_of - timedelta(days=offset)
            stock_hours = 0 if offset >= 5 else 16
            sale_amount = 2.0 if stock_hours == 0 else 999.0
            rows.append((1001, row_date.isoformat(), sale_amount, stock_hours))

        # These values would materially change the median if either the lower
        # boundary, the as-of date, or future dates leaked into the window.
        rows.extend(
            [
                (1001, (as_of - timedelta(days=15)).isoformat(), 999.0, 0),
                (1001, as_of.isoformat(), 999.0, 0),
                (1001, (as_of + timedelta(days=1)).isoformat(), 999.0, 0),
            ]
        )
        connection.executemany("INSERT INTO sales_history VALUES (?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_strict_time_boundaries_and_complete_stock_filter(self) -> None:
        result = estimate_daily_demand(
            1001, "2024-06-25", db_path=self.database_path
        )
        self.assertEqual(result.estimated_daily_demand, 2.0)
        self.assertEqual(result.demand_confidence, "High")
        self.assertEqual(result.demand_window_days, 14)
        self.assertEqual(result.in_stock_days_used, 10)
        self.assertFalse(result.manual_review_required)


if __name__ == "__main__":
    unittest.main()
