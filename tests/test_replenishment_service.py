"""Integration tests for the replenishment orchestration service."""

from __future__ import annotations

import unittest

from src.decision_engine import evaluate_replenishment_decision
from src.demand_service import estimate_daily_demand
from src.replenishment_service import (
    OperationalStateNotFoundError,
    get_operational_state,
    get_replenishment_decision,
)


class ReplenishmentServiceTests(unittest.TestCase):
    def test_high_confidence_demand_case(self) -> None:
        result = get_replenishment_decision(851, "2024-06-25")
        self.assertEqual(result.estimated_daily_demand, 1.9)
        self.assertEqual(result.demand_confidence, "High")
        self.assertEqual(result.demand_window_days, 14)
        self.assertEqual(result.in_stock_days_used, 14)
        self.assertEqual(result.current_inventory, 3.2)
        self.assertEqual(result.lead_time_days, 2)
        self.assertEqual(result.parameter_source, "simulated")
        self.assertEqual(result.stockout_risk, "Medium")
        self.assertEqual(result.replenishment_priority, "P2")

    def test_low_confidence_demand_case(self) -> None:
        result = get_replenishment_decision(834, "2024-05-15")
        self.assertEqual(result.estimated_daily_demand, 1.85)
        self.assertEqual(result.demand_confidence, "Low")
        self.assertEqual(result.demand_window_days, 30)
        self.assertEqual(result.in_stock_days_used, 12)
        self.assertEqual(result.current_inventory, 11.0)
        self.assertEqual(result.lead_time_days, 5)
        self.assertEqual(result.parameter_source, "simulated")
        self.assertEqual(result.stockout_risk, "Low")
        self.assertEqual(result.replenishment_priority, "P3")

    def test_insufficient_data_reaches_decision_engine_manual_review(self) -> None:
        result = get_replenishment_decision(44, "2024-05-01")
        self.assertIsNone(result.estimated_daily_demand)
        self.assertEqual(result.demand_confidence, "Insufficient Data")
        self.assertTrue(result.manual_review_required)
        self.assertIsNone(result.days_of_supply)
        self.assertIsNone(result.coverage_gap)
        self.assertIsNone(result.coverage_ratio)
        self.assertIsNone(result.stockout_risk)
        self.assertEqual(result.replenishment_priority, "Manual Review")

    def test_missing_sku_raises_clear_exception(self) -> None:
        with self.assertRaisesRegex(
            OperationalStateNotFoundError,
            "No operational state found for sku_id=999999",
        ):
            get_replenishment_decision(999999, "2024-06-25")

    def test_combined_result_matches_individual_service_calls(self) -> None:
        cases = [
            (851, "2024-06-25"),
            (834, "2024-05-15"),
            (44, "2024-05-01"),
            (44, "2024-06-25"),
        ]
        for sku_id, as_of_date in cases:
            with self.subTest(sku_id=sku_id, as_of_date=as_of_date):
                demand = estimate_daily_demand(sku_id, as_of_date)
                state = get_operational_state(sku_id)
                decision = evaluate_replenishment_decision(
                    demand.estimated_daily_demand,
                    state.current_inventory,
                    state.lead_time_days,
                )
                combined = get_replenishment_decision(sku_id, as_of_date)

                self.assertEqual(combined.sku_id, demand.sku_id)
                self.assertEqual(combined.as_of_date, demand.as_of_date)
                self.assertEqual(
                    combined.estimated_daily_demand,
                    demand.estimated_daily_demand,
                )
                self.assertEqual(combined.demand_confidence, demand.demand_confidence)
                self.assertEqual(combined.demand_window_days, demand.demand_window_days)
                self.assertEqual(combined.in_stock_days_used, demand.in_stock_days_used)
                self.assertEqual(
                    combined.manual_review_required,
                    demand.manual_review_required,
                )
                self.assertEqual(combined.current_inventory, state.current_inventory)
                self.assertEqual(combined.lead_time_days, state.lead_time_days)
                self.assertEqual(combined.parameter_source, state.parameter_source)
                self.assertEqual(combined.days_of_supply, decision.days_of_supply)
                self.assertEqual(combined.coverage_gap, decision.coverage_gap)
                self.assertEqual(combined.coverage_ratio, decision.coverage_ratio)
                self.assertEqual(combined.stockout_risk, decision.stockout_risk)
                self.assertEqual(
                    combined.replenishment_priority,
                    decision.replenishment_priority,
                )


if __name__ == "__main__":
    unittest.main()
