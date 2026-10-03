"""Estimate daily demand from complete in-stock days in SQLite history.

This module is intentionally limited to historical demand estimation. It does
not read operational state or calculate inventory coverage, risk, or priority.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "inventory.db"

HISTORY_SQL = """
SELECT date, sale_amount, stock_hour6_22_cnt
FROM sales_history
WHERE sku_id = ?
  AND date >= ?
  AND date < ?
ORDER BY date
"""


@dataclass(frozen=True, slots=True)
class DemandEstimate:
    """Result returned by :func:`estimate_daily_demand`."""

    sku_id: int
    as_of_date: str
    estimated_daily_demand: float | None
    demand_confidence: str
    demand_window_days: int
    in_stock_days_used: int
    manual_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly representation of the result."""
        return asdict(self)


def _parse_as_of_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of_date must use ISO format YYYY-MM-DD") from exc
    raise TypeError("as_of_date must be a YYYY-MM-DD string, date, or datetime")


def _read_history(
    sku_id: int, as_of: date, database_path: Path
) -> list[tuple[date, float, int]]:
    """Read only the 30 calendar days strictly before ``as_of``."""
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    window_start = as_of - timedelta(days=30)
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        rows = connection.execute(
            HISTORY_SQL,
            (sku_id, window_start.isoformat(), as_of.isoformat()),
        ).fetchall()

    history = [
        (date.fromisoformat(row_date), float(sale_amount), int(stock_hours))
        for row_date, sale_amount, stock_hours in rows
    ]
    if any(not window_start <= row_date < as_of for row_date, _, _ in history):
        raise RuntimeError("Historical query returned a row outside the 30-day window")
    return history


def estimate_daily_demand(
    sku_id: int,
    as_of_date: str | date | datetime,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> DemandEstimate:
    """Estimate demand using complete in-stock days before an as-of date.

    The 14-day window is ``as_of_date - 14 days <= date < as_of_date``.
    When it has fewer than seven complete in-stock days, the function evaluates
    the analogous 30-day window. A complete in-stock day has
    ``stock_hour6_22_cnt == 0``.

    Args:
        sku_id: SKU identifier stored in ``sales_history``.
        as_of_date: ISO date string, :class:`date`, or :class:`datetime`.
        db_path: SQLite database path. Defaults to ``data/inventory.db``.

    Returns:
        A :class:`DemandEstimate` containing the selected median and confidence.
        If the 30-day window has fewer than seven complete in-stock days, the
        estimate is ``None`` and manual review is required.
    """
    if isinstance(sku_id, bool) or not isinstance(sku_id, int):
        raise TypeError("sku_id must be an integer")

    as_of = _parse_as_of_date(as_of_date)
    history_30 = _read_history(sku_id, as_of, Path(db_path))
    window_14_start = as_of - timedelta(days=14)

    in_stock_sales_30 = [
        sale_amount
        for _, sale_amount, stock_hours in history_30
        if stock_hours == 0
    ]
    in_stock_sales_14 = [
        sale_amount
        for row_date, sale_amount, stock_hours in history_30
        if row_date >= window_14_start and stock_hours == 0
    ]

    in_stock_days_14 = len(in_stock_sales_14)
    if in_stock_days_14 >= 10:
        return DemandEstimate(
            sku_id=sku_id,
            as_of_date=as_of.isoformat(),
            estimated_daily_demand=float(median(in_stock_sales_14)),
            demand_confidence="High",
            demand_window_days=14,
            in_stock_days_used=in_stock_days_14,
            manual_review_required=False,
        )

    if in_stock_days_14 >= 7:
        return DemandEstimate(
            sku_id=sku_id,
            as_of_date=as_of.isoformat(),
            estimated_daily_demand=float(median(in_stock_sales_14)),
            demand_confidence="Medium",
            demand_window_days=14,
            in_stock_days_used=in_stock_days_14,
            manual_review_required=False,
        )

    in_stock_days_30 = len(in_stock_sales_30)
    if in_stock_days_30 >= 7:
        return DemandEstimate(
            sku_id=sku_id,
            as_of_date=as_of.isoformat(),
            estimated_daily_demand=float(median(in_stock_sales_30)),
            demand_confidence="Low",
            demand_window_days=30,
            in_stock_days_used=in_stock_days_30,
            manual_review_required=False,
        )

    return DemandEstimate(
        sku_id=sku_id,
        as_of_date=as_of.isoformat(),
        estimated_daily_demand=None,
        demand_confidence="Insufficient Data",
        demand_window_days=30,
        in_stock_days_used=in_stock_days_30,
        manual_review_required=True,
    )


__all__ = ["DemandEstimate", "estimate_daily_demand"]
