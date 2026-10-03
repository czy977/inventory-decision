#!/usr/bin/env python3
"""Build and validate the phase-2 SQLite data foundation."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = ROOT / "freshretail_mvp.csv"
DATA_DIR = ROOT / "data"
DATABASE_PATH = DATA_DIR / "inventory.db"
VALIDATION_PATH = ROOT / "reports" / "inventory_db_validation.json"

EXPECTED_SKUS = {44, 167, 316, 834, 851}
OPERATIONAL_STATE = [
    (851, 2, 3.20, "simulated"),
    (167, 3, 3.60, "simulated"),
    (316, 4, 7.00, "simulated"),
    (834, 5, 11.00, "simulated"),
    (44, 3, 4.50, "simulated"),
]

SCHEMA_SQL = """
CREATE TABLE sales_history (
    sku_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    sale_amount REAL NOT NULL,
    stock_hour6_22_cnt INTEGER NOT NULL,
    CONSTRAINT uq_sales_history_sku_date UNIQUE (sku_id, date),
    CONSTRAINT ck_sales_history_stock_hours
        CHECK (stock_hour6_22_cnt BETWEEN 0 AND 16)
);

CREATE TABLE sku_operational_state (
    sku_id INTEGER PRIMARY KEY,
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days > 0),
    current_inventory REAL NOT NULL CHECK (current_inventory >= 0),
    parameter_source TEXT NOT NULL
        CHECK (parameter_source = 'simulated')
);
"""


def read_sales_history() -> list[tuple[int, str, float, int]]:
    rows: list[tuple[int, str, float, int]] = []
    with SOURCE_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected_columns = {
            "store_id",
            "product_id",
            "dt",
            "sale_amount",
            "stock_hour6_22_cnt",
        }
        if set(reader.fieldnames or []) != expected_columns:
            raise ValueError(f"Unexpected MVP columns: {reader.fieldnames}")

        for source_row in reader:
            sku_id = int(source_row["product_id"])
            row_date = date.fromisoformat(source_row["dt"]).isoformat()
            sale_amount = float(source_row["sale_amount"])
            stock_hours = int(source_row["stock_hour6_22_cnt"])
            rows.append((sku_id, row_date, sale_amount, stock_hours))

    if len(rows) != 450:
        raise ValueError(f"Expected 450 sales rows, found {len(rows)}")
    if {row[0] for row in rows} != EXPECTED_SKUS:
        raise ValueError("Unexpected SKU set in MVP source")
    if len({(row[0], row[1]) for row in rows}) != len(rows):
        raise ValueError("MVP source contains duplicate sku_id + date keys")
    if any(not 0 <= row[3] <= 16 for row in rows):
        raise ValueError("stock_hour6_22_cnt is outside the documented 0–16 range")
    return rows


def create_database(sales_rows: list[tuple[int, str, float, int]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(
        prefix="inventory.", suffix=".db.tmp", dir=DATA_DIR
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)

    try:
        connection = sqlite3.connect(temp_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA_SQL)
            with connection:
                connection.executemany(
                    """
                    INSERT INTO sales_history
                        (sku_id, date, sale_amount, stock_hour6_22_cnt)
                    VALUES (?, ?, ?, ?)
                    """,
                    sales_rows,
                )
                connection.executemany(
                    """
                    INSERT INTO sku_operational_state
                        (sku_id, lead_time_days, current_inventory, parameter_source)
                    VALUES (?, ?, ?, ?)
                    """,
                    OPERATIONAL_STATE,
                )
        finally:
            connection.close()

        os.replace(temp_path, DATABASE_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def constraint_rejects(connection: sqlite3.Connection, sql: str, values: tuple) -> bool:
    connection.execute("SAVEPOINT constraint_test")
    try:
        connection.execute(sql, values)
    except sqlite3.IntegrityError:
        connection.execute("ROLLBACK TO constraint_test")
        connection.execute("RELEASE constraint_test")
        return True
    else:
        connection.execute("ROLLBACK TO constraint_test")
        connection.execute("RELEASE constraint_test")
        return False


def validate_database() -> dict[str, object]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        sales_count = connection.execute(
            "SELECT COUNT(*) FROM sales_history"
        ).fetchone()[0]
        state_count = connection.execute(
            "SELECT COUNT(*) FROM sku_operational_state"
        ).fetchone()[0]
        duplicate_sales = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT sku_id, date
                FROM sales_history
                GROUP BY sku_id, date
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        duplicate_states = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT sku_id
                FROM sku_operational_state
                GROUP BY sku_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        unique_constraint_rejects_duplicate = constraint_rejects(
            connection,
            """
            INSERT INTO sales_history
                (sku_id, date, sale_amount, stock_hour6_22_cnt)
            VALUES (?, ?, ?, ?)
            """,
            (851, "2024-03-28", 999.0, 0),
        )
        primary_key_rejects_duplicate = constraint_rejects(
            connection,
            """
            INSERT INTO sku_operational_state
                (sku_id, lead_time_days, current_inventory, parameter_source)
            VALUES (?, ?, ?, ?)
            """,
            (851, 9, 999.0, "simulated"),
        )
        source_check_rejects_non_simulated = constraint_rejects(
            connection,
            """
            INSERT INTO sku_operational_state
                (sku_id, lead_time_days, current_inventory, parameter_source)
            VALUES (?, ?, ?, ?)
            """,
            (999, 1, 1.0, "manual"),
        )

        by_sku_count = connection.execute(
            "SELECT COUNT(*) FROM sales_history WHERE sku_id = ?", (851,)
        ).fetchone()[0]
        range_rows = connection.execute(
            """
            SELECT sku_id, date, sale_amount, stock_hour6_22_cnt
            FROM sales_history
            WHERE sku_id = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (834, "2024-06-01", "2024-06-07"),
        ).fetchall()
        operational_rows = connection.execute(
            """
            SELECT sku_id, lead_time_days, current_inventory, parameter_source
            FROM sku_operational_state
            ORDER BY CASE sku_id
                WHEN 851 THEN 1 WHEN 167 THEN 2 WHEN 316 THEN 3
                WHEN 834 THEN 4 WHEN 44 THEN 5 END
            """
        ).fetchall()
        index_rows = connection.execute("PRAGMA index_list('sales_history')").fetchall()

        checks = {
            "sales_history_has_450_rows": sales_count == 450,
            "sku_operational_state_has_5_rows": state_count == 5,
            "sales_history_has_no_duplicate_sku_date": duplicate_sales == 0,
            "sku_operational_state_has_no_duplicate_sku": duplicate_states == 0,
            "unique_constraint_rejects_duplicate_sku_date": unique_constraint_rejects_duplicate,
            "primary_key_rejects_duplicate_sku": primary_key_rejects_duplicate,
            "parameter_source_check_rejects_non_simulated": source_check_rejects_non_simulated,
            "query_by_sku_returns_90_rows": by_sku_count == 90,
            "query_by_sku_and_date_range_returns_7_rows": len(range_rows) == 7,
            "sales_history_unique_index_exists": any(row[2] == 1 for row in index_rows),
            "all_parameter_sources_are_simulated": all(
                row["parameter_source"] == "simulated" for row in operational_rows
            ),
        }

        return {
            "passed": all(checks.values()),
            "database": str(DATABASE_PATH.relative_to(ROOT)),
            "sqlite_version": sqlite3.sqlite_version,
            "checks": checks,
            "record_counts": {
                "sales_history": sales_count,
                "sku_operational_state": state_count,
            },
            "operational_state": [dict(row) for row in operational_rows],
            "example_query": {
                "sql": (
                    "SELECT sku_id, date, sale_amount, stock_hour6_22_cnt "
                    "FROM sales_history WHERE sku_id = 834 "
                    "AND date BETWEEN '2024-06-01' AND '2024-06-07' ORDER BY date;"
                ),
                "rows": [dict(row) for row in range_rows],
            },
        }
    finally:
        connection.close()


def main() -> None:
    sales_rows = read_sales_history()
    create_database(sales_rows)
    validation = validate_database()
    if not validation["passed"]:
        raise AssertionError(f"Database validation failed: {validation['checks']}")
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Created {DATABASE_PATH}")
    print(json.dumps(validation["record_counts"], ensure_ascii=False))
    print(f"Validation passed: {VALIDATION_PATH}")


if __name__ == "__main__":
    main()
