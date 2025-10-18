# Source Public — ECB Euro FX Reference Rates

## Endpoint
- **URL (90-day window):** `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml`
- **Format:** XML (Cube entries with `time`, `currency`, `rate` attributes)
- **Auth:** None (public)
- **Refresh cadence:** Daily on ECB business days (~16:00 CET publish)
- **Business key:** `currency_code`

## Landing Layout
- **Landing prefix:** `s3://lake/landing/public/ecb_exchange_rates/load_date=<YYYY-MM-DD>/batch_id=<timestamp>/rates.parquet`
- **Bronze archive table:** `ducklake.bronze.ecb_exchange_rates_archive`
- **Bronze latest view:** `ducklake.bronze.ecb_exchange_rates_latest` (mirrored at `ducklake.bronze.ecb_exchange_rates`)
- **Ingestion command:** `make ingest_ecb_rates` (wraps `scripts/ingest_ecb_rates.py`)
- **Deterministic run:** `make ingest_ecb_rates ARGS="--rate-date 2024-01-15 --load-date 2024-01-16 --batch-id ecb-2024-01-15T00:00:00Z"`

## Snapshot Semantics
- Each ingest writes a Parquet snapshot for the requested `rate_date` and appends to the bronze archive with `load_date`/`load_batch` metadata.
- If an ingest reruns with the same `load_date` and `load_batch`, the loader skips inserting duplicate rows, keeping the archive idempotent for identical batches.
- Landing prefixes sanitize characters such as `:` into `-` for S3 compatibility; the original batch identifier persists in `load_batch`.
- The latest view returns the newest record per currency, prioritizing `rate_date` and then ingest metadata (`load_date`, `load_batch`), keeping compatibility with downstream silver models that expect a `ducklake.bronze.ecb_exchange_rates` relation.

## Schema (Bronze Archive)

| column        | type          | description                                          |
|---------------|---------------|------------------------------------------------------|
| load_date     | DATE          | Ingestion load date (CLI flag, defaults to UTC date) |
| load_batch    | VARCHAR       | Batch identifier for the ingest run                  |
| rate_date     | DATE          | ECB business date for the published rates            |
| currency_code | VARCHAR       | ISO 4217 currency code (base currency = EUR)         |
| currency_name | VARCHAR NULL  | Friendly currency name (if known)                    |
| fx_rate       | DECIMAL(18,6) | Quoted rate (1 EUR → currency_code)                  |

## Quality & Monitoring
- Bronze archive deduplicates via `load_date`/`load_batch`; silver models should enforce `(rate_date, currency_code)` uniqueness with dbt/SQLMesh tests.
- Add assertions for minimum active currency count (e.g., ≥15 per rate_date) to detect publication gaps.
- Include integration tests that mock the ECB XML payload to keep ingest logic deterministic and offline-friendly.

## Usage Notes
- ECB publishes rates for business days only; expect missing entries for weekends and certain holidays.
- Historical data beyond 90 days is available from `eurofxref-hist.xml`; adjust `--endpoint` if longer lookbacks are needed.
- When building SCD2 datasets or trend aggregations, source data from `ducklake.bronze.ecb_exchange_rates_archive`; use the `<table>_latest` view for current-state snapshots.
