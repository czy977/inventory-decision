"""FastAPI transport layer for replenishment decisions.

This module validates HTTP inputs, delegates to the service layer, and
serializes results. It contains no SQL or demand/decision business rules.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from src.replenishment_service import (
    OperationalStateNotFoundError,
    get_replenishment_decision,
)
from src.scenario_service import get_scenario_decision


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


class ScenarioDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: StrictInt
    as_of_date: date
    override_lead_time_days: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    override_current_inventory: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    @field_validator("as_of_date", mode="before")
    @classmethod
    def validate_iso_date(cls, value: Any) -> Any:
        """Require the HTTP request value to use exact YYYY-MM-DD form."""
        if not isinstance(value, str):
            raise ValueError("as_of_date must use ISO format YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of_date must use ISO format YYYY-MM-DD") from exc
        if parsed.isoformat() != value:
            raise ValueError("as_of_date must use ISO format YYYY-MM-DD")
        return parsed

    @field_validator(
        "override_lead_time_days",
        "override_current_inventory",
        mode="before",
    )
    @classmethod
    def validate_numeric_override(cls, value: Any) -> Any:
        """Reject booleans and numeric strings before numeric constraints run."""
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("override values must be numeric")
        return value

    @model_validator(mode="after")
    def require_an_override(self) -> "ScenarioDecisionRequest":
        if (
            self.override_lead_time_days is None
            and self.override_current_inventory is None
        ):
            raise ValueError(
                "At least one of override_lead_time_days or "
                "override_current_inventory must be provided"
            )
        return self


class ScenarioDemandResponse(BaseModel):
    estimated_daily_demand: float | None
    demand_confidence: str
    demand_window_days: int
    in_stock_days_used: int
    manual_review_required: bool


class ScenarioBaselineResponse(BaseModel):
    current_inventory: float
    lead_time_days: float
    parameter_source: str
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str


class ScenarioComparisonResponse(BaseModel):
    override_current_inventory: float | None
    override_lead_time_days: float | None
    effective_current_inventory: float
    effective_lead_time_days: float
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str


class ScenarioDecisionResponse(BaseModel):
    sku_id: int
    as_of_date: str
    demand: ScenarioDemandResponse
    baseline: ScenarioBaselineResponse
    scenario: ScenarioComparisonResponse


app = FastAPI(
    title="Inventory Decision Copilot API",
    version="0.1.0",
)


def _json_safe_validation_detail(value: Any) -> Any:
    """Replace non-finite validation inputs so a standard 422 can be encoded."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {
            key: _json_safe_validation_detail(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_detail(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_error_response(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Preserve FastAPI's 422 shape for non-standard NaN/Infinity input."""
    detail = _json_safe_validation_detail(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(detail)},
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


@app.post(
    "/scenario-decision",
    response_model=ScenarioDecisionResponse,
)
def scenario_decision(
    request: ScenarioDecisionRequest,
) -> ScenarioDecisionResponse:
    """Return a baseline-versus-scenario comparison from existing services."""
    try:
        result = get_scenario_decision(
            request.sku_id,
            request.as_of_date,
            override_lead_time_days=request.override_lead_time_days,
            override_current_inventory=request.override_current_inventory,
        )
    except OperationalStateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ScenarioDecisionResponse(**result.to_dict())
