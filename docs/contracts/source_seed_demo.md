# Source File — Demo Seed Dataset

## Source
- **File:** `seeds/demo_seed.csv`
- **Refresh cadence:** Manual (trigger via `make ingest_seed_demo` during development or demos).
- **Business key:** `id`

## Landing Layout
- **Landing prefix:** `s3://lake/landing/seed_demo/load_date=<YYYY-MM-DD>/batch_id=<timestamp>/seed_demo.parquet`
- **Bronze archive table:** `ducklake.bronze.seed_demo_archive`
- **Bronze latest view:** `ducklake.bronze.seed_demo_latest` (mirrored at `ducklake.bronze.seed_demo`)
- **Ingestion command:** `make ingest_seed_demo` (wraps `scripts/ingest_file.py`)

## Snapshot Semantics
- Every run appends rows into `ducklake.bronze.seed_demo_archive` with `load_date` (DATE) and `load_batch` (identifier string) columns that map to the landing prefix. Landing prefixes sanitize characters such as `:` into `-` for S3 compatibility; the original batch identifier is kept verbatim in `load_batch`.
- `ducklake.bronze.seed_demo_latest` surfaces the newest rows per `id` by ordering on `load_date`, then `load_batch`. Use this view for silver models that need point-in-time data.
- To replay or test deterministically, pass `--load-date` (`YYYY-MM-DD`) and `--batch-id` (`YYYY-MM-DDTHH:MM:SSZ`) to `scripts/ingest_file.py`. The resulting parquet is written to the matching partition hierarchy.

## Schema

| column         | type      | description                                   |
|----------------|-----------|-----------------------------------------------|
| load_date      | DATE      | Snapshot date captured from the CLI flag      |
| load_batch     | VARCHAR   | Unique batch identifier for the ingest run    |
| id             | INTEGER   | Business key for each record                  |
| name           | VARCHAR   | Demo customer name                            |
| load_timestamp | TIMESTAMP | Demo load timestamp from the source CSV file  |

## Notes
- Historical snapshots remain queryable via `ducklake.bronze.seed_demo_archive` for audit and QA workflows.
- `ducklake.bronze.seed_demo` is a compatibility view pointing to the latest snapshot; prefer `seed_demo_latest` explicitly in new models.
