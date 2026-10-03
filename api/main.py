"""FastAPI transport layer for replenishment decisions.

This module validates HTTP inputs, delegates to ``replenishment_service``, and
serializes its result. It contains no SQL or demand/decision business rules.
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.replenishment_service import (
    OperationalStateNotFoundError,
    get_replenishment_decision,
)


class HealthResponse(BaseModel):
    status: str


class ReplenishmentDecisionResponse(BaseModel):
    sku_id: int
    as_of_date: str
    estimated_daily_demand: float | None
    demand_confidence: str
    demand_window_days: int
    in_stock_days_used: int
    manual_review_required: bool
    current_inventory: float
    lead_time_days: int
    parameter_source: str
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str


app = FastAPI(
    title="Inventory Decision Copilot API",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return a minimal process health response."""
    return HealthResponse(status="ok")


@app.get(
    "/replenishment-decision",
    response_model=ReplenishmentDecisionResponse,
)
def replenishment_decision(
    sku_id: int = Query(..., description="SKU identifier"),
    as_of_date: date = Query(..., description="Decision date in YYYY-MM-DD format"),
) -> ReplenishmentDecisionResponse:
    """Return the existing replenishment-service result as JSON."""
    try:
        result = get_replenishment_decision(sku_id, as_of_date)
    except OperationalStateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ReplenishmentDecisionResponse(**result.to_dict())
