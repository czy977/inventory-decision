"""Tests for the coverage-based replenishment decision engine."""

from __future__ import annotations

import unittest

from src.decision_engine import (
    ReplenishmentDecision,
    evaluate_replenishment_decision,
)


class DecisionEngineTests(unittest.TestCase):
    def assert_valid_decision(
        self,
        *,
        demand: float,
        inventory: float,
        lead_time: float,
        days_of_supply: float,
        coverage_gap: float,
        coverage_ratio: float,
        risk: str,
        priority: str,
    ) -> None:
        result = evaluate_replenishment_decision(demand, inventory, lead_time)
        self.assertIsInstance(result, ReplenishmentDecision)
        self.assertEqual(result.estimated_daily_demand, demand)
        self.assertEqual(result.current_inventory, inventory)
        self.assertEqual(result.lead_time_days, lead_time)
        self.assertAlmostEqual(result.days_of_supply, days_of_supply)
        self.assertAlmostEqual(result.coverage_gap, coverage_gap)
        self.assertAlmostEqual(result.coverage_ratio, coverage_ratio)
        self.assertEqual(result.stockout_risk, risk)
        self.assertEqual(result.replenishment_priority, priority)

    def assert_manual_review(self, demand: float | None) -> None:
        result = evaluate_replenishment_decision(demand, 4.5, 3)
        self.assertEqual(result.estimated_daily_demand, demand)
        self.assertEqual(result.current_inventory, 4.5)
        self.assertEqual(result.lead_time_days, 3.0)
        self.assertIsNone(result.days_of_supply)
        self.assertIsNone(result.coverage_gap)
        self.assertIsNone(result.coverage_ratio)
        self.assertIsNone(result.stockout_risk)
        self.assertEqual(result.replenishment_priority, "Manual Review")

    def test_low_risk(self) -> None:
        self.assert_valid_decision(
            demand=2.0,
            inventory=6.0,
            lead_time=2.0,
            days_of_supply=3.0,
            coverage_gap=0.0,
            coverage_ratio=1.5,
            risk="Low",
            priority="P3",
        )

    def test_medium_risk(self) -> None:
        self.assert_valid_decision(
            demand=2.0,
            inventory=3.0,
            lead_time=2.0,
            days_of_supply=1.5,
            coverage_gap=0.5,
            coverage_ratio=0.75,
            risk="Medium",
            priority="P2",
        )

    def test_high_risk(self) -> None:
        self.assert_valid_decision(
            demand=2.0,
            inventory=1.0,
            lead_time=2.0,
            days_of_supply=0.5,
            coverage_gap=1.5,
            coverage_ratio=0.25,
            risk="High",
            priority="P1",
        )

    def test_null_demand_requires_manual_review(self) -> None:
        self.assert_manual_review(None)

    def test_zero_demand_requires_manual_review(self) -> None:
        self.assert_manual_review(0.0)

    def test_coverage_ratio_exactly_one_is_low_p3(self) -> None:
        self.assert_valid_decision(
            demand=2.0,
            inventory=4.0,
            lead_time=2.0,
            days_of_supply=2.0,
            coverage_gap=0.0,
            coverage_ratio=1.0,
            risk="Low",
            priority="P3",
        )

    def test_coverage_ratio_exactly_half_is_medium_p2(self) -> None:
        self.assert_valid_decision(
            demand=2.0,
            inventory=2.0,
            lead_time=2.0,
            days_of_supply=1.0,
            coverage_gap=1.0,
            coverage_ratio=0.5,
            risk="Medium",
            priority="P2",
        )


if __name__ == "__main__":
    unittest.main()
