"""AC-D12 — reproducible ingestion benchmark for the CFO 2.0 four-file scenario (docs/specs/cfo-data-intelligence.md §6.9).

Scenario (owner brief, "Ravi"): Amazon 25,000 rows + Flipkart 18,000 + Meesho 32,000 + an expense file of 5,000 rows = 80,000 rows.

WHAT THIS MEASURES, HONESTLY
  * SYNTHETIC data, generated deterministically from --seed. It is not seller data and it does not validate any adapter's mapping.
  * The three marketplace files go through the REAL job runner (stream -> validate -> classify duplicates -> post, one transaction per file) on
    the sales-side adapters that exist: amazon.mtr_b2c.v1, flipkart.sales_report.v1, meesho.orders.v1.
  * The EXPENSE file is NOT ingested: expense posting (AC-D11) is not built. For it the report records only the stream + profile + mapping-
    validation time, clearly labelled as such. The 60-second target is therefore reported for the 75,000 marketplace rows actually posted and,
    separately, with the expense validation step added — never as "80,000 rows ingested".
  * Two shapes are run. NARROW: only the columns the adapters map. WIDE: plus --wide-columns unmapped filler columns per row, modelling the
    width of real marketplace exports (every unmapped column becomes a V-COL-001 finding per row), which is the realistic cost.
  * Numbers are for THIS machine and this local, untuned Postgres; they are targets' evidence, not guarantees.

USAGE (scratch database only — the script refuses anything but port 5544 unless --allow-dev-db)
    bash backend/scripts/scratch_db.sh up
    eval "$(bash backend/scripts/scratch_db.sh env)"
    python tools/benchmarks/cfo_ingest_benchmark.py --output docs/evaluation/cfo-2-ingest-benchmark.md
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path

import psutil
from sqlalchemy import create_engine, make_url, text

from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.job_runner import JobRunner, RunnerConfig
from data_foundation.ingestion.profiling import collect_profile_input
from data_foundation.ingestion.streaming import StreamLimits, open_csv
from data_foundation.mapping import service as mapping_service
from data_foundation.mapping.validator import MappingLimits
from data_foundation.repositories import ingestion_job_repo as jobs
from data_foundation.repositories.tenant_context import tenant_scope

SCENARIO = (  # (label, adapter id, report kind, marketplace, rows)
    ("Amazon (MTR b2c)", "amazon.mtr_b2c.v1", "SALES", "AMAZON", 25_000),
    ("Flipkart (sales report)", "flipkart.sales_report.v1", "SALES", "FLIPKART", 18_000),
    ("Meesho (orders)", "meesho.orders.v1", "SALES", "MEESHO", 32_000),
)
EXPENSE_ROWS = 5_000
_MONEY = {"gross_item_amount", "taxable_amount", "total_invoice_amount", "gross_settlement_amount", "total_sale_amount", "settlement_amount_value",
          "component_amount", "_ignored_legacy_tax_column"}
TARGET_SECONDS = 60


def headers_of(adapter) -> list[str]:  # type: ignore[no-untyped-def]
    seen: list[str] = []
    for key in adapter.column_map:
        h = key[0] if isinstance(key, tuple) else key
        if h not in seen:
            seen.append(h)
    return seen


def cell(adapter, header: str, i: int, rng: random.Random) -> str:  # type: ignore[no-untyped-def]
    binding = next(b for k, b in adapter.column_map.items() if (k[0] if isinstance(k, tuple) else k) == header)
    cf = binding.canonical_field
    if binding.component_code is not None:
        return f"{rng.randint(1, 400)}.{rng.randint(0, 99):02d}"
    if cf in _MONEY:
        return f"{rng.randint(80, 4000)}.{rng.randint(0, 99):02d}"
    if cf in adapter.enum_maps:
        return next(iter(adapter.enum_maps[cf]), "Delivered")
    if cf.endswith("_date"):
        return f"2026-10-{1 + i % 27:02d}"
    if cf == "gst_rate":
        return "18"
    if cf in ("order_ref", "line_ref"):
        return f"{adapter.marketplace[:3]}-{cf[:1].upper()}{i:09d}"
    return f"{cf}-{rng.randint(0, 99)}"


def write_marketplace_file(path: Path, adapter, rows: int, wide_columns: int, seed: int) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(seed)
    hs = headers_of(adapter)
    filler = [f"Extra Column {k}" for k in range(wide_columns)]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(hs + filler) + "\n")
        for i in range(rows):
            f.write(",".join([cell(adapter, h, i, rng) for h in hs] + [f"v{rng.randint(0, 9)}" for _ in filler]) + "\n")


def write_expense_file(path: Path, rows: int, seed: int) -> None:
    rng = random.Random(seed)
    cats = ["Packaging", "Advertising", "Software", "Rent", "Courier", "Salary", "Owner drawings", "Repairs"]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("Date,Category,Amount,Description,Vendor,Reference\n")
        for i in range(rows):
            f.write(f"{1 + i % 28:02d}/10/2026,{rng.choice(cats)},{rng.randint(50, 90000)}.{rng.randint(0, 99):02d},Item {i},Vendor {rng.randint(1, 60)},REF-{i:06d}\n")


def expense_proposal(_inp):  # type: ignore[no-untyped-def]
    return {"fields": [
        {"source_column": "Date", "index": 0, "canonical_field": "expense_date", "transform": "DATE_DMY"},
        {"source_column": "Category", "index": 1, "canonical_field": "expense_category", "transform": "IDENTITY"},
        {"source_column": "Amount", "index": 2, "canonical_field": "expense_amount", "transform": "RUPEES_TO_PAISE", "sign_convention": "AS_IS"},
        {"source_column": "Description", "index": 3, "canonical_field": "expense_description", "transform": "IDENTITY"},
        {"source_column": "Vendor", "index": 4, "canonical_field": "expense_vendor", "transform": "IDENTITY"},
        {"source_column": "Reference", "index": 5, "canonical_field": "expense_payment_ref", "transform": "IDENTITY"}], "unmapped_columns": []}


class PeakRss:
    def __init__(self) -> None:
        self._proc = psutil.Process()
        self.base = self._proc.memory_info().rss
        self.peak = self.base
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._proc.memory_info().rss)
            time.sleep(0.05)

    def __enter__(self) -> "PeakRss":
        self.base = self.peak = self._proc.memory_info().rss
        self._stop.clear()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a: object) -> None:
        self._stop.set()
        self._t.join()
        self.peak = max(self.peak, self._proc.memory_info().rss)

    @property
    def growth_mib(self) -> float:
        return (self.peak - self.base) / 2**20


@dataclass
class FileResult:
    label: str
    rows: int
    size_mib: float
    status: str
    seconds: float
    posted: int
    chunks: int | None
    rss_growth_mib: float


def run_shape(shape: str, wide_columns: int, chunk_rows: int, seed: int, scale: float, tmp: Path) -> tuple[list[FileResult], dict[str, float]]:
    limits = StreamLimits(chunk_rows=chunk_rows, max_rows=10_000_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
                          max_uncompressed_bytes=4 * 1024**3, max_zip_ratio=200, max_zip_members=500, max_sheets=50)
    mlim = MappingLimits(min_parse_rate=Fraction(98, 100), tax_consistency_rate=Fraction(98, 100), tax_tolerance_paise=1, key_unique_rate=Fraction(98, 100),
                         mixed_sign_low=Fraction(2, 100), max_date_span_years=5, unit_fraction_share=Fraction(2, 100))
    runner = JobRunner(config=RunnerConfig(max_workers=1, stale_after_seconds=3600, profile_rows=5000, sample_rows=20), stream_limits=limits,
                       mapping_limits=mlim, as_of=lambda: date(2026, 10, 21))
    tenant = uuid.uuid4()
    now = datetime.now(timezone.utc)
    results: list[FileResult] = []

    def register(path: Path, marketplace: str, kind: str, adapter_id: str) -> uuid.UUID:
        fid = uuid.uuid4()
        with tenant_scope(tenant) as conn:
            conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)
                                 VALUES (:id,:t,:m,'ORDER_STATUS',:sha,:n,:b,:u,:by,:at)"""),
                         {"id": str(fid), "t": str(tenant), "m": marketplace, "sha": uuid.uuid4().hex * 2, "n": path.name, "b": path.stat().st_size,
                          "u": f"file://{path}", "by": str(uuid.uuid4()), "at": now})
        return jobs.create_job(tenant, report_file_id=fid, report_kind=kind, created_by=uuid.uuid4(), adapter_id=adapter_id)

    total_start = time.perf_counter()
    with PeakRss() as whole:
        for n, (label, adapter_id, kind, marketplace, rows) in enumerate(SCENARIO):
            rows = int(rows * scale)
            path = tmp / f"{shape}-{adapter_id}.csv"
            write_marketplace_file(path, ADAPTER_REGISTRY[adapter_id], rows, wide_columns, seed + n)
            job = register(path, marketplace, kind, adapter_id)
            with PeakRss() as m:
                t0 = time.perf_counter()
                status = runner.run_job(tenant, job)
                dt = time.perf_counter() - t0
            out = (jobs.get_job(tenant, job) or {}).get("outcome") or {}
            results.append(FileResult(label, rows, path.stat().st_size / 2**20, status, dt, int(out.get("persisted_row_count", 0)), out.get("chunks"), m.growth_mib))
    posted_total = time.perf_counter() - total_start

    # Expense file: stream + profile + mapping validation ONLY (AC-D11 posting is not built).
    ex_path = tmp / f"{shape}-expenses.csv"
    ex_rows = int(EXPENSE_ROWS * scale)
    write_expense_file(ex_path, ex_rows, seed + 99)
    with PeakRss() as m:
        t0 = time.perf_counter()
        pinput = collect_profile_input(open_csv(ex_path, limits), profile_rows=5000, sample_rows=20, seed=seed)
        res = mapping_service.propose(tenant, pinput=pinput, report_kind="EXPENSE", marketplace=None, proposer=expense_proposal, proposed_by="MODEL:mock",
                                      limits=mlim, as_of=date(2026, 10, 21))
        ex_dt = time.perf_counter() - t0
    results.append(FileResult("Expenses (stream + profile + validate ONLY; not posted)", ex_rows, ex_path.stat().st_size / 2**20,
                              "VALIDATED_NOT_POSTED" if not res.verdict.has_errors else "VALIDATION_ERRORS", ex_dt, 0, None, m.growth_mib))
    with tenant_scope(tenant) as conn:  # integrity: what was reported as posted is what is in the database
        db_posted = conn.execute(text("SELECT count(*) FROM sales_line WHERE tenant_id = :t"), {"t": str(tenant)}).scalar_one()
    assert db_posted == sum(r.posted for r in results), "reported posted rows differ from rows in the database"
    return results, {"posted_seconds": posted_total, "expense_validation_seconds": ex_dt, "rss_growth_mib": whole.growth_mib, "db_rows": float(db_posted)}


def git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def render(shapes: list[tuple[str, int, list[FileResult], dict[str, float]]], args: argparse.Namespace, pg_version: str) -> str:
    L: list[str] = []
    L += ["# CFO 2.0 — ingestion benchmark (AC-D12)", "",
          f"Generated by `tools/benchmarks/cfo_ingest_benchmark.py` at {datetime.now(timezone.utc).isoformat(timespec='seconds')}. **Synthetic data**, deterministic from the seed. "
          "Targets are not guarantees; these numbers describe this machine only.", "",
          "## Environment", "",
          f"- Commit: `{git('rev-parse', '--short', 'HEAD')}` (code paths {'clean' if not git('status', '--porcelain', '--', 'packages', 'backend', 'tools', 'docs/specs') else 'have uncommitted changes'})",
          f"- OS: {platform.platform()} · Python {platform.python_version()}",
          f"- CPU: {os.cpu_count()} logical · RAM: {psutil.virtual_memory().total / 2**30:.1f} GiB",
          f"- Database: {pg_version} (local Docker scratch instance on :5544, no tuning)",
          f"- Settings: chunk_rows={args.chunk_rows} · workers=1 · seed={args.seed} · scale={args.scale} · wide columns={args.wide_columns}", "",
          "Reproduce:", "", "```", "bash backend/scripts/scratch_db.sh up", 'eval "$(bash backend/scripts/scratch_db.sh env)"',
          f"python tools/benchmarks/cfo_ingest_benchmark.py --seed {args.seed} --chunk-rows {args.chunk_rows} --scale {args.scale} --wide-columns {args.wide_columns} --output <report.md>", "```", "",
          "## What is and is not measured", "",
          "- **Measured:** the three marketplace files (Amazon, Flipkart, Meesho) through the real job runner: stream, validate, classify duplicates, post in one transaction each.",
          "- **NOT measured / NOT built:** expense posting (**AC-D11 is not built**; the expense file below is only streamed, profiled and mapping-validated and is **not ingested**), "
          "advertising ingestion, XLSX throughput, settlement-side files, and any real seller export.",
          "- The adapters map only a subset of each marketplace's columns, so *narrow* files understate the cost of real reports; *wide* adds unmapped columns per row to model real width.", ""]
    for shape, wide, results, totals in shapes:
        marketplace_rows = sum(r.rows for r in results if r.posted or r.status in ("DONE", "FAILED"))
        posted = sum(r.posted for r in results)
        L += [f"## Shape: {shape}" + (f" (+{wide} unmapped columns per row)" if wide else ""), "",
              "| File | Rows | Size (MiB) | Status | Seconds | Rows/s | Posted | Chunks | Peak memory growth (MiB) |", "|---|---:|---:|---|---:|---:|---:|---:|---:|"]
        for r in results:
            L.append(f"| {r.label} | {r.rows:,} | {r.size_mib:.1f} | {r.status} | {r.seconds:.1f} | {r.rows / r.seconds:,.0f} | {r.posted:,} | {r.chunks if r.chunks is not None else '—'} | {r.rss_growth_mib:.0f} |")
        ps = totals["posted_seconds"]
        both = ps + totals["expense_validation_seconds"]
        expense_rows = results[-1].rows
        L += ["", f"- **Marketplace rows posted:** {posted:,} of {marketplace_rows:,} in **{ps:.1f} s** ({posted / ps:,.0f} rows/s).",
              f"- **Against the 60 s target for the 80,000-row scenario:** {posted:,} rows posted plus {expense_rows:,} expense rows only stream-validated (not posted) took "
              f"{both:.1f} s in total — **{'within' if both <= TARGET_SECONDS else 'OUTSIDE'} the target**. This is *not* a measurement of 80,000 rows ingested, because expense posting is not built.",
              f"- **Whole-scenario peak memory growth:** {totals['rss_growth_mib']:.0f} MiB. Peak memory scales with chunk size × row width (a wide row carries one finding per unmapped column) "
              "plus one small digest per distinct row in the duplicate index; it never holds the file.",
              f"- **Integrity:** rows reported as posted equal rows in the database ({int(totals['db_rows']):,}).", ""]
    L += ["## Verdict", "",
          "Status of AC-D12: the script and this report are committed and reproducible. The four-file scenario is **only partly measurable today** because expense posting is not built; "
          "the claim above is limited accordingly and must be re-run when AC-D11 lands.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--chunk-rows", type=int, default=5000)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply every row count (1.0 = the 80,000-row scenario)")
    ap.add_argument("--wide-columns", type=int, default=40, help="unmapped filler columns per row in the WIDE shape")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--allow-dev-db", action="store_true", help="run against a database that is not the :5544 scratch instance (never do this)")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL_APP")
    if not url:
        print("DATABASE_URL_APP is not set. Use the scratch database: eval \"$(bash backend/scripts/scratch_db.sh env)\"", file=sys.stderr)
        return 2
    if make_url(url).port != 5544 and not args.allow_dev_db:
        print("Refusing to benchmark against anything but the scratch database on port 5544 (pass --allow-dev-db to override).", file=sys.stderr)
        return 2
    eng = create_engine(os.environ.get("DATABASE_URL", url))
    with eng.connect() as c:
        pg_version = str(c.execute(text("select version()")).scalar_one()).split(" on ")[0]
    eng.dispose()

    shapes = []
    with tempfile.TemporaryDirectory(prefix="cfo-bench-") as d:
        for shape, wide in (("NARROW", 0), ("WIDE", args.wide_columns)):
            results, totals = run_shape(shape, wide, args.chunk_rows, args.seed, args.scale, Path(d))
            shapes.append((shape, wide, results, totals))
            print(f"{shape}: posted {sum(r.posted for r in results):,} marketplace rows in {totals['posted_seconds']:.1f}s", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(shapes, args, pg_version), encoding="utf-8")
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
