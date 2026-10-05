"""HTTP-level tests for the FastAPI transport layer."""

from __future__ import annotations

import json
import unittest

import httpx

from api.main import app
from src.replenishment_service import get_replenishment_decision
from src.scenario_service import get_scenario_decision


class InventoryDecisionApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    def scenario_payload(self, **updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "sku_id": 851,
            "as_of_date": "2024-06-25",
        }
        payload.update(updates)
        return payload

    async def test_health(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_normal_replenishment_decision(self) -> None:
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": 851, "as_of_date": "2024-06-25"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sku_id"], 851)
        self.assertEqual(payload["as_of_date"], "2024-06-25")
        self.assertEqual(payload["estimated_daily_demand"], 1.9)
        self.assertEqual(payload["demand_confidence"], "High")
        self.assertEqual(payload["stockout_risk"], "Medium")
        self.assertEqual(payload["replenishment_priority"], "P2")

    async def test_insufficient_data_serializes_null_and_manual_review(self) -> None:
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": 44, "as_of_date": "2024-05-01"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["estimated_daily_demand"])
        self.assertEqual(payload["demand_confidence"], "Insufficient Data")
        self.assertEqual(payload["demand_window_days"], 30)
        self.assertTrue(payload["manual_review_required"])
        self.assertIsNone(payload["days_of_supply"])
        self.assertIsNone(payload["coverage_gap"])
        self.assertIsNone(payload["coverage_ratio"])
        self.assertIsNone(payload["stockout_risk"])
        self.assertEqual(payload["replenishment_priority"], "Manual Review")

    async def test_missing_sku_returns_404(self) -> None:
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": 999999, "as_of_date": "2024-06-25"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "No operational state found for sku_id=999999"},
        )

    async def test_invalid_date_returns_422(self) -> None:
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": 851, "as_of_date": "2024-02-30"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("detail", response.json())

    async def test_invalid_sku_id_returns_422(self) -> None:
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": "not-an-integer", "as_of_date": "2024-06-25"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("detail", response.json())

    async def test_api_payload_matches_direct_service_call(self) -> None:
        sku_id = 834
        as_of_date = "2024-05-15"
        response = await self.client.get(
            "/replenishment-decision",
            params={"sku_id": sku_id, "as_of_date": as_of_date},
        )
        direct_result = get_replenishment_decision(sku_id, as_of_date)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), direct_result.to_dict())

    async def test_scenario_normal_request(self) -> None:
        request_payload = self.scenario_payload(override_lead_time_days=5)
        response = await self.client.post(
            "/scenario-decision",
            json=request_payload,
        )
        direct_result = get_scenario_decision(
            851,
            "2024-06-25",
            override_lead_time_days=5,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), direct_result.to_dict())

    async def test_scenario_lead_time_override_only(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_lead_time_days=5),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["baseline"]["current_inventory"], 3.2)
        self.assertEqual(payload["baseline"]["lead_time_days"], 2.0)
        self.assertEqual(payload["baseline"]["stockout_risk"], "Medium")
        self.assertEqual(payload["baseline"]["replenishment_priority"], "P2")
        self.assertIsNone(payload["scenario"]["override_current_inventory"])
        self.assertEqual(payload["scenario"]["effective_current_inventory"], 3.2)
        self.assertEqual(payload["scenario"]["effective_lead_time_days"], 5.0)
        self.assertEqual(payload["scenario"]["stockout_risk"], "High")
        self.assertEqual(payload["scenario"]["replenishment_priority"], "P1")

    async def test_scenario_inventory_override_only(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_current_inventory=8.0),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["scenario"]
        self.assertEqual(payload["effective_current_inventory"], 8.0)
        self.assertEqual(payload["effective_lead_time_days"], 2.0)
        self.assertIsNone(payload["override_lead_time_days"])

    async def test_scenario_both_overrides(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(
                override_lead_time_days=4,
                override_current_inventory=6.5,
            ),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["scenario"]
        self.assertEqual(payload["effective_current_inventory"], 6.5)
        self.assertEqual(payload["effective_lead_time_days"], 4.0)

    async def test_scenario_zero_inventory_override(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_current_inventory=0),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["scenario"]
        self.assertEqual(payload["override_current_inventory"], 0.0)
        self.assertEqual(payload["effective_current_inventory"], 0.0)
        self.assertEqual(payload["stockout_risk"], "High")
        self.assertEqual(payload["replenishment_priority"], "P1")

    async def test_scenario_missing_both_overrides_returns_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_explicit_null_overrides_return_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(
                override_lead_time_days=None,
                override_current_inventory=None,
            ),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_zero_lead_time_returns_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_lead_time_days=0),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_negative_lead_time_returns_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_lead_time_days=-1),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_negative_inventory_returns_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(override_current_inventory=-0.01),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_non_finite_overrides_return_422(self) -> None:
        cases = [
            {"override_lead_time_days": float("nan")},
            {"override_lead_time_days": float("inf")},
            {"override_current_inventory": float("nan")},
            {"override_current_inventory": float("inf")},
            {"override_current_inventory": float("-inf")},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                request_body = json.dumps(self.scenario_payload(**overrides))
                response = await self.client.post(
                    "/scenario-decision",
                    content=request_body,
                    headers={"content-type": "application/json"},
                )
                self.assertEqual(response.status_code, 422)

    async def test_scenario_invalid_dates_return_422(self) -> None:
        for invalid_date in ("2024-02-30", "2024/06/25"):
            with self.subTest(as_of_date=invalid_date):
                response = await self.client.post(
                    "/scenario-decision",
                    json=self.scenario_payload(
                        as_of_date=invalid_date,
                        override_lead_time_days=5,
                    ),
                )
                self.assertEqual(response.status_code, 422)

    async def test_scenario_missing_sku_returns_404(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(
                sku_id=999,
                override_lead_time_days=5,
            ),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "No operational state found for sku_id=999"},
        )

    async def test_scenario_extra_field_returns_422(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json=self.scenario_payload(
                override_lead_time_days=5,
                estimated_daily_demand=999,
            ),
        )
        self.assertEqual(response.status_code, 422)

    async def test_scenario_insufficient_data_remains_manual_review(self) -> None:
        response = await self.client.post(
            "/scenario-decision",
            json={
                "sku_id": 44,
                "as_of_date": "2024-05-15",
                "override_lead_time_days": 1,
                "override_current_inventory": 999,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["demand"]["estimated_daily_demand"])
        self.assertEqual(payload["demand"]["demand_confidence"], "Insufficient Data")
        self.assertTrue(payload["demand"]["manual_review_required"])
        for decision_name in ("baseline", "scenario"):
            decision = payload[decision_name]
            self.assertIsNone(decision["days_of_supply"])
            self.assertIsNone(decision["coverage_gap"])
            self.assertIsNone(decision["coverage_ratio"])
            self.assertIsNone(decision["stockout_risk"])
            self.assertEqual(decision["replenishment_priority"], "Manual Review")


if __name__ == "__main__":
    unittest.main()
