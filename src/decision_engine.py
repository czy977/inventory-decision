"""Coverage-based inventory decision calculations for the MVP.

``stockout_risk`` is a coverage-based risk level. It is not a statistically
predicted probability of stockout. The 0.5 and 1.0 coverage-ratio cutoffs are
human-defined business thresholds for this project MVP, not industry standards.

This module does not estimate demand and does not access SQLite or APIs.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any


@dataclass(frozen=True, slots=True)
class ReplenishmentDecision:
    """Coverage calculation and rule-based replenishment classification."""

    estimated_daily_demand: float | None
    current_inventory: float
    lead_time_days: float
    days_of_supply: float | None
    coverage_gap: float | None
    coverage_ratio: float | None
    stockout_risk: str | None
    replenishment_priority: str

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly representation of the decision."""
        return asdict(self)


def _finite_number(value: Real, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{field_name} must be finite")
    return numeric_value


def evaluate_replenishment_decision(
    estimated_daily_demand: Real | None,
    current_inventory: Real,
    lead_time_days: Real,
) -> ReplenishmentDecision:
    """Calculate coverage metrics and classify stockout risk and priority.

    A missing, non-finite, zero, or negative demand does not support coverage
    calculations and therefore returns ``Manual Review``. Otherwise:

    - ``days_of_supply = current_inventory / estimated_daily_demand``
    - ``coverage_gap = max(lead_time_days - days_of_supply, 0)``
    - ``coverage_ratio = days_of_supply / lead_time_days``

    The risk labels are coverage-based categories, not predicted probabilities.
    Ratios at or above 1.0 are Low/P3, ratios from 0.5 through less than 1.0
    are Medium/P2, and ratios below 0.5 are High/P1. The thresholds are
    project-specific MVP business choices rather than industry standards.
    """
    inventory = _finite_number(current_inventory, "current_inventory")
    lead_time = _finite_number(lead_time_days, "lead_time_days")
    if inventory < 0:
        raise ValueError("current_inventory must be greater than or equal to zero")
    if lead_time <= 0:
        raise ValueError("lead_time_days must be greater than zero")

    if estimated_daily_demand is None:
        demand: float | None = None
    elif isinstance(estimated_daily_demand, bool) or not isinstance(
        estimated_daily_demand, Real
    ):
        raise TypeError("estimated_daily_demand must be a real number or None")
    else:
        demand = float(estimated_daily_demand)

    if demand is None or not math.isfinite(demand) or demand <= 0:
        return ReplenishmentDecision(
            estimated_daily_demand=demand,
            current_inventory=inventory,
            lead_time_days=lead_time,
            days_of_supply=None,
            coverage_gap=None,
            coverage_ratio=None,
            stockout_risk=None,
            replenishment_priority="Manual Review",
        )

    days_of_supply = inventory / demand
    coverage_gap = max(lead_time - days_of_supply, 0.0)
    coverage_ratio = days_of_supply / lead_time

    # These thresholds are project-specific business rules, not industry norms.
    if coverage_ratio >= 1.0:
        stockout_risk = "Low"
        replenishment_priority = "P3"
    elif coverage_ratio >= 0.5:
        stockout_risk = "Medium"
        replenishment_priority = "P2"
    else:
        stockout_risk = "High"
        replenishment_priority = "P1"

    return ReplenishmentDecision(
        estimated_daily_demand=demand,
        current_inventory=inventory,
        lead_time_days=lead_time,
        days_of_supply=days_of_supply,
        coverage_gap=coverage_gap,
        coverage_ratio=coverage_ratio,
        stockout_risk=stockout_risk,
        replenishment_priority=replenishment_priority,
    )


__all__ = ["ReplenishmentDecision", "evaluate_replenishment_decision"]
