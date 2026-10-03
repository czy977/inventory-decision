"""HTTP-level tests for the FastAPI transport layer."""

from __future__ import annotations

import unittest

import httpx

from api.main import app
from src.replenishment_service import get_replenishment_decision


class InventoryDecisionApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

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


if __name__ == "__main__":
    unittest.main()
