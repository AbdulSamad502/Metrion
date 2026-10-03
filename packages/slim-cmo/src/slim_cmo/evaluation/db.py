"""Writes `vision_eval_run` as the ADMIN role (`DATABASE_URL`, `metrion_migrate`). The application role has SELECT
only on this table; an evaluation is therefore an operator action, never reachable from the API."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text


class PostgresEvalWriter:
    def __init__(self, admin_url: str) -> None:
        if not admin_url:
            raise ValueError("an admin DATABASE_URL is required")
        self._url = admin_url

    def write(
        self, *, provider: str, model: str, schema_version: str, dataset_ref: str, metrics: dict[str, Any],
        bar_ref: str, passed: bool, run_by: str,
    ) -> UUID:
        engine = create_engine(self._url)
        try:
            with engine.begin() as conn:
                row = conn.execute(
                    text(
                        "INSERT INTO vision_eval_run (provider, model, schema_version, dataset_ref, metrics, bar_ref, passed, run_by) "
                        "VALUES (:provider, :model, :schema_version, :dataset_ref, CAST(:metrics AS jsonb), :bar_ref, :passed, :run_by) RETURNING id"
                    ),
                    {"provider": provider, "model": model, "schema_version": schema_version, "dataset_ref": dataset_ref,
                     "metrics": json.dumps(metrics), "bar_ref": bar_ref, "passed": passed, "run_by": run_by},
                ).one()
        finally:
            engine.dispose()
        run_id: UUID = row.id
        return run_id
