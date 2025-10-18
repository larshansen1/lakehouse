# DuckLake Minimal Lakehouse

## Local Environment Bootstrap

1. Copy `.env.example` to `.env` and customize credentials (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET_NAME`). Choose a catalog backend by setting `DUCKLAKE_BACKEND=duckdb` (default) or `DUCKLAKE_BACKEND=postgres`. When using Postgres, adjust the `DUCKLAKE_PG_*` variables (default port `55432`) and ensure they stay in sync with the Compose service. Keep `DUCKLAKE_DATA_PATH` pointed at the same bucket defined by `MINIO_BUCKET_NAME` (e.g., `s3://lake/ducklake`) so managed tables land in object storage without 404s.
2. Start the stack with `make up`. This brings up MinIO, creates the bucket defined in `.env`, and enables object versioning.
3. Visit the MinIO console at `http://localhost:9001` (default) to confirm the bucket status. S3 clients can connect via `http://localhost:9000`.
4. Run `make check` to validate that the bucket exists and versioning is turned on.
5. Execute `make bootstrap` to bring up MinIO (if not already), initialize DuckLake metadata, and load the seed dataset into `ducklake.bronze.seed_demo` as Parquet.
6. Alternatively, run `make create_ducklake` followed by `make check_ducklake` when you need to refresh the catalog only.
7. Tear down the environment with `make down` when finished.

### Catalog Backends

DuckLake supports both file-based (DuckDB) and Postgres-backed catalogs.

- `duckdb` (default): metadata lives at `ducklake/catalog.duckdb`. This mode keeps everything on the local filesystem and works out of the box with the demo commands.
- `postgres`: metadata is stored in the `postgres` service defined in `docker-compose.yml` (exposed on `${DUCKLAKE_PG_PORT:-55432}` to avoid clashing with a local Postgres). Configure the connection values in `.env` and re-run `make bootstrap` to initialise schemas.
- Switching backends: stop the stack with `make down`, archive or delete the previous catalog (`ducklake/catalog.duckdb`) and MinIO lake data (`_vol/minio/data/ducklake/`) so the new backend starts clean, then bring the stack back up and run `make bootstrap`. Clearing `_vol/postgres/data/` is recommended when moving away from Postgres.
- When the backend is Postgres, all helper scripts use an in-memory DuckDB session to avoid file locks; interactive shells spawned via `make ducklake_shell` now do the same, so you can ingest and query concurrently without closing the shell.
- `make ducklake_shell` runs DuckDB in read-only mode when Postgres backs the catalog, preventing lock conflicts with background ingestion while still letting you inspect data.
- See `docs/operations/catalog_backends.md` for a detailed checklist and troubleshooting tips.

### Persistence Layout

MinIO data and configuration persist under the `_vol` directory:

```text
_vol/
  minio/
    config/
    data/
```

These paths map directly into the container, keeping the catalog and object storage state between runs.

`make bootstrap`, `make create_ducklake`, and `make check_ducklake` are idempotent; rerun them anytime you need to recreate the schemas or reload the seed dataset.

### Querying DuckLake Tables

Each DuckDB session must load the DuckLake extension, configure MinIO credentials, and reattach the lake metadata before querying. Use the snippet that matches your configured backend.

DuckDB-backed catalog:

```sql
INSTALL httpfs;
LOAD httpfs;
SET s3_endpoint='127.0.0.1:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='ducklake';
SET s3_secret_access_key='ducklake-insecure-change-me';
LOAD ducklake;
ATTACH 'ducklake/catalog.duckdb' AS ducklake (TYPE DUCKLAKE, DATA_PATH 's3://lake/ducklake');
USE ducklake;
SELECT * FROM bronze.seed_demo LIMIT 5;
SELECT * FROM ducklake_snapshots('ducklake');
DETACH ducklake;
```

Postgres-backed catalog:

```sql
INSTALL httpfs;
LOAD httpfs;
INSTALL postgres;
LOAD postgres;
SET s3_endpoint='127.0.0.1:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='ducklake';
SET s3_secret_access_key='ducklake-insecure-change-me';
INSTALL ducklake;
LOAD ducklake;
ATTACH 'host=127.0.0.1 port=55432 dbname=ducklake user=ducklake password=ducklake-insecure-change-me sslmode=disable'
  AS ducklake (TYPE DUCKLAKE, DATA_PATH 's3://lake/ducklake');
USE ducklake;
SELECT * FROM bronze.seed_demo LIMIT 5;
SELECT * FROM ducklake_snapshots('ducklake');
DETACH ducklake;
```

Adjust the credentials, endpoint, and connection string if you override `MINIO_*`, `DUCKLAKE_METADATA_PATH`, `DUCKLAKE_DATA_PATH`, or `DUCKLAKE_PG_*`.

### Ingestion Commands

- `make ingest_seed_demo` — stage `seeds/demo_seed.csv` to `s3://lake/landing/seed_demo/load_date=<date>/batch_id=<batch>/seed_demo.parquet`, append to `ducklake.bronze.seed_demo_archive`, and refresh the `ducklake.bronze.seed_demo_latest` view (aliased at `ducklake.bronze.seed_demo`). Pass additional CLI flags with `make ingest_seed_demo ARGS="--load-date 2024-01-01 --batch-id 2024-01-01T12:00:00Z"`.
- `make ingest_api_todos` — fetch JSONPlaceholder todos to `s3://lake/landing/api/todos/load_date=<date>/batch_id=<batch>/todos.parquet`, append to `ducklake.bronze.api_todos_archive`, and refresh `ducklake.bronze.api_todos_latest`. Pass overrides with `make ingest_api_todos ARGS="--load-date 2024-01-01 --batch-id 2024-01-01T12:00:00Z"`.
- `make ingest_api_comments` — fetch JSONPlaceholder comments and apply the same archival flow; override metadata via `ARGS="--load-date ... --batch-id ..."` or adjust the endpoint/object name as needed.
- `make ingest_ecb_rates` — download the ECB Euro FX reference rates feed, land it under `s3://lake/landing/public/ecb_exchange_rates/load_date=<date>/batch_id=<batch>/rates.parquet`, append to `ducklake.bronze.ecb_exchange_rates_archive`, and refresh `ducklake.bronze.ecb_exchange_rates_latest`. Override business date or metadata with `make ingest_ecb_rates ARGS="--rate-date 2024-01-15 --batch-id ecb-2024-01-15T00:00:00Z"`.
- `make backfill_ecb_rates ARGS="2023"` — prefetch the full ECB historical feed and run the ingest once per business day in the given year (honors `--start-date/--end-date`, `--duckdb`, `--batch-prefix`, and `--dry-run` flags). Each batch reuses the existing loader and defaults `--load-date/--batch-id` to the rate date for idempotency; adjust `--batch-prefix` if you need to force new snapshots.
- `make ducklake_shell` — launch an interactive DuckDB shell with MinIO credentials and the DuckLake catalog pre-attached (runs `INSTALL httpfs; ... USE ducklake;` automatically). Use `ARGS="--duckdb /path/to/duckdb"` to override the CLI binary if needed.
- `make demo` — orchestrate bootstrap, offline-friendly ingests, silver/gold transforms, and an audit pass (idempotent).
- `make dbt_run` — surrogate for downstream transforms; materialises the silver/gold views used by analytics demos.
- `make audit` — recomputes row-count telemetry and appends results to `ducklake.audit.table_health`.

Implementation note: the ingestion scripts are thin CLI wrappers—shared logic now lives under `scripts/lib/` (`api_ingest.py`, `file_ingest.py`, and `ecb_rates_ingest.py`) so unit tests and future extensions can reuse the same building blocks.

For deterministic runs, pass the optional flags directly to the ingest script:

```sh
python scripts/ingest_file.py \
  --dataset seed_demo \
  --source seeds/demo_seed.csv \
  --table seed_demo \
  --load-date 2024-01-01 \
  --batch-id 2024-01-01T12:00:00Z
```

Historical snapshot parquet files live under `s3://lake/landing/<dataset>/load_date=<date>/batch_id=<batch>/`. Archive tables store these values in `load_date` and `load_batch` columns so downstream consumers can query either the full history (`ducklake.bronze.seed_demo_archive`, `ducklake.bronze.api_todos_archive`, `ducklake.bronze.ecb_exchange_rates_archive`, etc.) or the rolling latest snapshot (via `<table>_latest`). Re-running an ingest with the same `--load-date/--batch-id` skips the archive append to keep runs idempotent. When batch identifiers contain characters that are not S3-friendly (e.g., colons), they are sanitized to safe tokens in the object path while the original string is preserved in `load_batch`. See `docs/contracts/source_public.md` for the ECB schema and refresh guidance.

## Testing

Run the Python unit tests from the project root:

```sh
pytest
```

### Linting & Type Checks

Install and run the automated style gates via pre-commit:

```sh
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
```

This executes `ruff` and `mypy` locally—the same checks that should gate CI.

Generate a branch-coverage snapshot for the core pipeline modules:

```sh
pytest --cov=scripts.run_demo \
       --cov=scripts.run_transforms \
       --cov=scripts.run_audit \
       --cov=scripts.lib.load_utils \
       --cov-branch
```

### Catalog Backups

- `make backup_catalog` — copies `ducklake/catalog.duckdb`, the project `catalog.db`, and manifest CSVs to `s3://lake/ducklake/_catalog_backups/<timestamp>/`.
- Artifacts include `tables.csv`, `data_files.csv`, `snapshots.csv`, `metadata.csv`, and a `manifest.json` summarizing the run.
- To restore, download a backup set from `_catalog_backups/<timestamp>/`, replace `ducklake/catalog.duckdb` and `catalog.db`, then validate objects against the manifest before resuming ingestion.
- Prune old backups by removing dated prefixes under `_catalog_backups/` once newer snapshots are verified.
