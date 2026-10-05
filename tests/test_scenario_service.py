"""Tests for in-memory what-if replenishment orchestration."""

from __future__ import annotations

import unittest

from src.decision_engine import ReplenishmentDecision, evaluate_replenishment_decision
from src.replenishment_service import get_operational_state
from src.scenario_service import ScenarioResult, get_scenario_decision


class ScenarioServiceTests(unittest.TestCase):
    sku_id = 851
    as_of_date = "2024-06-25"

    def assert_scenario_matches_engine(
        self,
        result: ScenarioResult,
        expected: ReplenishmentDecision,
    ) -> None:
        scenario = result.scenario
        self.assertEqual(
            scenario.effective_current_inventory,
            expected.current_inventory,
        )
        self.assertEqual(
            scenario.effective_lead_time_days,
            expected.lead_time_days,
        )
        self.assertEqual(scenario.days_of_supply, expected.days_of_supply)
        self.assertEqual(scenario.coverage_gap, expected.coverage_gap)
        self.assertEqual(scenario.coverage_ratio, expected.coverage_ratio)
        self.assertEqual(scenario.stockout_risk, expected.stockout_risk)
        self.assertEqual(
            scenario.replenishment_priority,
            expected.replenishment_priority,
        )

    def test_override_lead_time_only_matches_decision_engine(self) -> None:
        result = get_scenario_decision(
            self.sku_id,
            self.as_of_date,
            override_lead_time_days=5,
        )

        self.assertEqual(result.baseline.current_inventory, 3.2)
        self.assertEqual(result.baseline.lead_time_days, 2.0)
        self.assertEqual(result.baseline.stockout_risk, "Medium")
        self.assertEqual(result.baseline.replenishment_priority, "P2")
        self.assertIsNone(result.scenario.override_current_inventory)
        self.assertEqual(result.scenario.override_lead_time_days, 5)
        self.assertEqual(result.scenario.effective_current_inventory, 3.2)
        self.assertEqual(result.scenario.effective_lead_time_days, 5.0)

        expected = evaluate_replenishment_decision(
            result.demand.estimated_daily_demand,
            result.baseline.current_inventory,
            5,
        )
        self.assert_scenario_matches_engine(result, expected)

    def test_override_inventory_only_matches_decision_engine(self) -> None:
        result = get_scenario_decision(
            self.sku_id,
            self.as_of_date,
            override_current_inventory=8.0,
        )

        self.assertEqual(result.baseline.current_inventory, 3.2)
        self.assertEqual(result.baseline.lead_time_days, 2.0)
        self.assertEqual(result.scenario.override_current_inventory, 8.0)
        self.assertIsNone(result.scenario.override_lead_time_days)
        self.assertEqual(result.scenario.effective_current_inventory, 8.0)
        self.assertEqual(result.scenario.effective_lead_time_days, 2.0)

        expected = evaluate_replenishment_decision(
            result.demand.estimated_daily_demand,
            8.0,
            result.baseline.lead_time_days,
        )
        self.assert_scenario_matches_engine(result, expected)

    def test_override_both_operational_values(self) -> None:
        result = get_scenario_decision(
            self.sku_id,
            self.as_of_date,
            override_lead_time_days=4,
            override_current_inventory=6.5,
        )

        self.assertEqual(result.scenario.effective_current_inventory, 6.5)
        self.assertEqual(result.scenario.effective_lead_time_days, 4.0)
        expected = evaluate_replenishment_decision(
            result.demand.estimated_daily_demand,
            6.5,
            4,
        )
        self.assert_scenario_matches_engine(result, expected)

    def test_zero_inventory_is_a_valid_override(self) -> None:
        result = get_scenario_decision(
            self.sku_id,
            self.as_of_date,
            override_current_inventory=0,
        )

        self.assertEqual(result.baseline.current_inventory, 3.2)
        self.assertEqual(result.scenario.override_current_inventory, 0)
        self.assertEqual(result.scenario.effective_current_inventory, 0.0)
        self.assertEqual(result.scenario.stockout_risk, "High")
        self.assertEqual(result.scenario.replenishment_priority, "P1")

    def test_baseline_operational_state_is_not_modified(self) -> None:
        before = get_operational_state(self.sku_id)
        get_scenario_decision(
            self.sku_id,
            self.as_of_date,
            override_lead_time_days=9,
            override_current_inventory=99.0,
        )
        after = get_operational_state(self.sku_id)

        self.assertEqual(after, before)
        self.assertEqual(after.current_inventory, 3.2)
        self.assertEqual(after.lead_time_days, 2)

    def test_insufficient_data_remains_manual_review(self) -> None:
        result = get_scenario_decision(
            44,
            "2024-05-15",
            override_lead_time_days=1,
            override_current_inventory=999.0,
        )

        self.assertIsNone(result.demand.estimated_daily_demand)
        self.assertEqual(result.demand.demand_confidence, "Insufficient Data")
        self.assertTrue(result.demand.manual_review_required)
        for decision in (result.baseline, result.scenario):
            self.assertIsNone(decision.days_of_supply)
            self.assertIsNone(decision.coverage_gap)
            self.assertIsNone(decision.coverage_ratio)
            self.assertIsNone(decision.stockout_risk)
            self.assertEqual(decision.replenishment_priority, "Manual Review")

    def test_risk_monotonicity_for_operational_overrides(self) -> None:
        risk_severity = {"Low": 0, "Medium": 1, "High": 2}
        cases = [
            ("lead time increase", {"override_lead_time_days": 5}, False),
            ("lead time decrease", {"override_lead_time_days": 1}, True),
            ("inventory decrease", {"override_current_inventory": 1.0}, False),
            ("inventory increase", {"override_current_inventory": 10.0}, True),
        ]

        for label, overrides, should_not_worsen in cases:
            with self.subTest(case=label):
                result = get_scenario_decision(
                    self.sku_id,
                    self.as_of_date,
                    **overrides,
                )
                baseline_severity = risk_severity[result.baseline.stockout_risk]
                scenario_severity = risk_severity[result.scenario.stockout_risk]
                if should_not_worsen:
                    self.assertLessEqual(scenario_severity, baseline_severity)
                else:
                    self.assertGreaterEqual(scenario_severity, baseline_severity)

    def test_exact_risk_boundaries_via_inventory_overrides(self) -> None:
        cases = [
            (3.8, 1.0, "Low", "P3"),
            (1.9, 0.5, "Medium", "P2"),
            (1.0, None, "High", "P1"),
        ]

        for inventory, exact_ratio, expected_risk, expected_priority in cases:
            with self.subTest(inventory=inventory):
                result = get_scenario_decision(
                    self.sku_id,
                    self.as_of_date,
                    override_current_inventory=inventory,
                )
                if exact_ratio is None:
                    self.assertLess(result.scenario.coverage_ratio, 0.5)
                else:
                    self.assertEqual(result.scenario.coverage_ratio, exact_ratio)
                self.assertEqual(result.scenario.stockout_risk, expected_risk)
                self.assertEqual(
                    result.scenario.replenishment_priority,
                    expected_priority,
                )

    def test_at_least_one_override_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one"):
            get_scenario_decision(self.sku_id, self.as_of_date)


if __name__ == "__main__":
    unittest.main()
