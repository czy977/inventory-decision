"""Orchestrate demand, operational state, and replenishment decisions.

This module is a composition layer only. Demand estimation remains in
``demand_service`` and coverage/risk logic remains in ``decision_engine``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.decision_engine import evaluate_replenishment_decision
from src.demand_service import DEFAULT_DB_PATH, estimate_daily_demand


class OperationalStateNotFoundError(LookupError):
    """Raised when a SKU has no row in ``sku_operational_state``."""


@dataclass(frozen=True, slots=True)
class OperationalState:
    """Operational parameters loaded from SQLite without modification."""

    sku_id: int
    current_inventory: float
    lead_time_days: int
    parameter_source: str


@dataclass(frozen=True, slots=True)
class ReplenishmentResult:
    """Combined output from demand estimation and the decision engine."""

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

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly representation of the result."""
        return asdict(self)


def get_operational_state(
    sku_id: int, *, db_path: str | Path = DEFAULT_DB_PATH
) -> OperationalState:
    """Load one SKU's operational state from SQLite.

    No default values are generated. A missing SKU raises
    :class:`OperationalStateNotFoundError`.
    """
    database_path = Path(db_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        row = connection.execute(
            """
            SELECT current_inventory, lead_time_days, parameter_source
            FROM sku_operational_state
            WHERE sku_id = ?
            """,
            (sku_id,),
        ).fetchone()

    if row is None:
        raise OperationalStateNotFoundError(
            f"No operational state found for sku_id={sku_id}"
        )

    current_inventory, lead_time_days, parameter_source = row
    return OperationalState(
        sku_id=sku_id,
        current_inventory=float(current_inventory),
        lead_time_days=int(lead_time_days),
        parameter_source=str(parameter_source),
    )


def get_replenishment_decision(
    sku_id: int,
    as_of_date: str | date | datetime,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ReplenishmentResult:
    """Run the existing services and combine their results.

    The function deliberately contains no demand, coverage, risk, or priority
    formulas. An Insufficient Data demand result is still passed unchanged to
    the decision engine, which owns the Manual Review rule.
    """
    demand_result = estimate_daily_demand(sku_id, as_of_date, db_path=db_path)
    operational_state = get_operational_state(sku_id, db_path=db_path)
    decision_result = evaluate_replenishment_decision(
        demand_result.estimated_daily_demand,
        operational_state.current_inventory,
        operational_state.lead_time_days,
    )

    return ReplenishmentResult(
        sku_id=demand_result.sku_id,
        as_of_date=demand_result.as_of_date,
        estimated_daily_demand=demand_result.estimated_daily_demand,
        demand_confidence=demand_result.demand_confidence,
        demand_window_days=demand_result.demand_window_days,
        in_stock_days_used=demand_result.in_stock_days_used,
        manual_review_required=demand_result.manual_review_required,
        current_inventory=operational_state.current_inventory,
        lead_time_days=operational_state.lead_time_days,
        parameter_source=operational_state.parameter_source,
        days_of_supply=decision_result.days_of_supply,
        coverage_gap=decision_result.coverage_gap,
        coverage_ratio=decision_result.coverage_ratio,
        stockout_risk=decision_result.stockout_risk,
        replenishment_priority=decision_result.replenishment_priority,
    )


__all__ = [
    "OperationalState",
    "OperationalStateNotFoundError",
    "ReplenishmentResult",
    "get_operational_state",
    "get_replenishment_decision",
]
