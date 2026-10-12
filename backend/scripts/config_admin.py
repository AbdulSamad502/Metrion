"""Operator tool: load reference / threshold / entitlement configuration rows with the OWNER role.

Why it exists. The application role (`metrion_app`) can no longer write configuration (migration 20261012_0018): fee schedules, GST rates, anomaly and health thresholds, tolerances
and entitlement caps are changed by an operator, never by the running application. The specs deliberately seed no numbers ("No numeric value in this table is seeded by this spec"),
so the VALUES come from you: this tool only validates your rows against the table's real columns and inserts them, append-only (configuration is versioned by `effective_from` /
`version`; nothing is updated or deleted).

    python scripts/config_admin.py tables
    python scripts/config_admin.py template anomaly_detection_config        # prints the columns and which are required
    python scripts/config_admin.py load anomaly_detection_config rows.json  # DRY RUN: validates and prints what would be inserted and WHERE
    python scripts/config_admin.py load anomaly_detection_config rows.json --apply

Connects with `DATABASE_URL` (the owner / migrate role), never `DATABASE_URL_APP`. The first line printed is the database it will touch (host, port, name): check it before
`--apply`. `rows.json` is a JSON list of objects keyed by column name; JSON/JSONB columns take JSON values. All rows go in one transaction or none do."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from sqlalchemy import create_engine, make_url, text

# Configuration the operator may load. Anything else is refused: this is not a general SQL tool.
TABLES = (
    "anomaly_detection_config",
    "financial_health_config",
    "fee_reference",
    "reconciliation_tolerance_config",
    "severity_config",
    "discount_bearer_config",
    "entitlement_cap_config",
    "hsn_gst_reference",
    "gst_slab_reference",
)
GENERATED = frozenset({"id", "created_at", "recorded_at"})  # filled by the database when absent
_CAST = {"jsonb": "jsonb", "json": "json", "uuid": "uuid", "date": "date", "timestamptz": "timestamptz", "timestamp": "timestamp", "numeric": "numeric", "bool": "boolean"}


class ConfigError(Exception):
    """A problem with the operator's input. The message names the row and column."""


def columns(conn, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT column_name, udt_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"),
        {"t": table},
    ).all()
    if not rows:
        raise ConfigError(f"table {table} does not exist in this database")
    return [{"name": r[0], "type": r[1], "required": r[2] == "NO" and r[3] is None and r[0] not in GENERATED} for r in rows]


def validate(cols: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    known = {c["name"] for c in cols}
    required = [c["name"] for c in cols if c["required"]]
    problems: list[str] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            problems.append(f"row {i}: must be an object of column: value")
            continue
        for name in row:
            if name not in known:
                problems.append(f"row {i}: unknown column '{name}'")
        for name in required:
            if row.get(name) is None:
                problems.append(f"row {i}: required column '{name}' is missing")
    return problems


def insert_sql(table: str, cols: list[dict[str, Any]], row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    by_name = {c["name"]: c for c in cols}
    names = [n for n in row]
    values: dict[str, Any] = {}
    placeholders = []
    for n in names:
        t = by_name[n]["type"]
        v = row[n]
        if t in {"jsonb", "json"}:
            v = json.dumps(v)
        values[n] = v
        cast = _CAST.get(t)
        placeholders.append(f"CAST(:{n} AS {cast})" if cast else f":{n}")
    sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(placeholders)})"  # noqa: S608 - table is whitelisted, columns are checked against the catalog
    return sql, values


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tables")
    t = sub.add_parser("template")
    t.add_argument("table")
    ld = sub.add_parser("load")
    ld.add_argument("table")
    ld.add_argument("file")
    ld.add_argument("--apply", action="store_true", help="actually insert (default: dry run)")
    args = ap.parse_args(argv)

    if args.cmd == "tables":
        print("\n".join(TABLES))
        return 0
    if args.table not in TABLES:
        print(f"refused: '{args.table}' is not a loadable configuration table. Allowed: {', '.join(TABLES)}", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL (the owner role) is not set", file=sys.stderr)
        return 2
    target = make_url(url)
    print(f"database: host={target.host} port={target.port} name={target.database} user={target.username}")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            cols = columns(conn, args.table)
        if args.cmd == "template":
            for c in cols:
                print(f"{c['name']:32s} {c['type']:12s} {'REQUIRED' if c['required'] else 'optional/generated'}")
            return 0
        with open(args.file, encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list) or not rows:
            print("rows.json must be a non-empty JSON list", file=sys.stderr)
            return 2
        problems = validate(cols, rows)
        if problems:
            print("refused, nothing inserted:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        statements = [insert_sql(args.table, cols, r) for r in rows]
        if not args.apply:
            print(f"dry run: {len(statements)} row(s) would be inserted into {args.table}. Add --apply to insert.")
            return 0
        with engine.begin() as conn:  # one transaction: all rows or none
            for sql, values in statements:
                conn.execute(text(sql), values)
        print(f"inserted {len(statements)} row(s) into {args.table}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
