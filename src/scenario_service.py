"""Orchestrate in-memory what-if replenishment decisions.

This module reuses the existing baseline replenishment service and decision
engine. It does not query or write SQLite directly, estimate demand, or
implement coverage, risk, or priority rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from numbers import Real
from pathlib import Path
from typing import Any

from src.decision_engine import evaluate_replenishment_decision
from src.demand_service import DEFAULT_DB_PATH
from src.replenishment_service import get_replenishment_decision


@dataclass(frozen=True, slots=True)
class ScenarioDemand:
    """Demand estimate shared by the baseline and scenario decisions."""

    estimated_daily_demand: float | None
    demand_confidence: str
    demand_window_days: int
    in_stock_days_used: int
    manual_review_required: bool


@dataclass(frozen=True, slots=True)
class BaselineDecision:
    """Persisted operational state and its existing decision result."""

    current_inventory: float
    lead_time_days: float
    parameter_source: str
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str


@dataclass(frozen=True, slots=True)
class ScenarioDecision:
    """Temporary overrides, effective inputs, and their decision result."""

    override_current_inventory: Real | None
    override_lead_time_days: Real | None
    effective_current_inventory: float
    effective_lead_time_days: float
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Complete baseline-versus-scenario comparison."""

    sku_id: int
    as_of_date: str
    demand: ScenarioDemand
    baseline: BaselineDecision
    scenario: ScenarioDecision

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly nested representation."""
        return asdict(self)


def get_scenario_decision(
    sku_id: int,
    as_of_date: str | date | datetime,
    *,
    override_lead_time_days: Real | None = None,
    override_current_inventory: Real | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ScenarioResult:
    """Compare the persisted baseline with temporary operational overrides.

    At least one override is required. Overrides are applied only to local
    variables and are never persisted. Demand and the complete baseline are
    obtained from :func:`get_replenishment_decision`; the scenario is then
    evaluated by the existing decision engine using the same demand estimate.
    """
    if override_lead_time_days is None and override_current_inventory is None:
        raise ValueError(
            "At least one of override_lead_time_days or "
            "override_current_inventory must be provided"
        )

    baseline_result = get_replenishment_decision(
        sku_id,
        as_of_date,
        db_path=db_path,
    )

    effective_inventory = (
        override_current_inventory
        if override_current_inventory is not None
        else baseline_result.current_inventory
    )
    effective_lead_time = (
        override_lead_time_days
        if override_lead_time_days is not None
        else baseline_result.lead_time_days
    )

    scenario_result = evaluate_replenishment_decision(
        baseline_result.estimated_daily_demand,
        effective_inventory,
        effective_lead_time,
    )

    return ScenarioResult(
        sku_id=baseline_result.sku_id,
        as_of_date=baseline_result.as_of_date,
        demand=ScenarioDemand(
            estimated_daily_demand=baseline_result.estimated_daily_demand,
            demand_confidence=baseline_result.demand_confidence,
            demand_window_days=baseline_result.demand_window_days,
            in_stock_days_used=baseline_result.in_stock_days_used,
            manual_review_required=baseline_result.manual_review_required,
        ),
        baseline=BaselineDecision(
            current_inventory=baseline_result.current_inventory,
            lead_time_days=float(baseline_result.lead_time_days),
            parameter_source=baseline_result.parameter_source,
            days_of_supply=baseline_result.days_of_supply,
            coverage_gap=baseline_result.coverage_gap,
            coverage_ratio=baseline_result.coverage_ratio,
            stockout_risk=baseline_result.stockout_risk,
            replenishment_priority=baseline_result.replenishment_priority,
        ),
        scenario=ScenarioDecision(
            override_current_inventory=override_current_inventory,
            override_lead_time_days=override_lead_time_days,
            effective_current_inventory=scenario_result.current_inventory,
            effective_lead_time_days=scenario_result.lead_time_days,
            days_of_supply=scenario_result.days_of_supply,
            coverage_gap=scenario_result.coverage_gap,
            coverage_ratio=scenario_result.coverage_ratio,
            stockout_risk=scenario_result.stockout_risk,
            replenishment_priority=scenario_result.replenishment_priority,
        ),
    )


__all__ = [
    "BaselineDecision",
    "ScenarioDecision",
    "ScenarioDemand",
    "ScenarioResult",
    "get_scenario_decision",
]
