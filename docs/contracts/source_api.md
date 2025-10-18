# Source API — JSONPlaceholder

## Endpoint
- **Todos URL:** `https://jsonplaceholder.typicode.com/todos`
- **Comments URL:** `https://jsonplaceholder.typicode.com/comments`
- **Method:** `GET`
- **Auth:** None (public test endpoint)
- **Refresh cadence:** On-demand for demos; daily refresh sufficient for regression tests.

## Landing Layout
- **Landing prefix:** `s3://lake/landing/api/<dataset>/load_date=<YYYY-MM-DD>/batch_id=<timestamp>/<object>.parquet`
- **Bronze archive tables:** `ducklake.bronze.api_todos_archive`, `ducklake.bronze.api_comments_archive`
- **Bronze latest views:** `ducklake.bronze.api_todos_latest`, `ducklake.bronze.api_comments_latest` (mirrored at `ducklake.bronze.<table>`)
- **Ingestion commands:** `make ingest_api_todos`, `make ingest_api_comments` (both wrap `scripts/ingest_api.py`)
- **Deterministic runs:** `make ingest_api_todos ARGS="--load-date 2024-01-01 --batch-id 2024-01-01T12:00:00Z"`

## Schema

Todos payload:

| column     | type      | description                               |
|------------|-----------|-------------------------------------------|
| load_date  | DATE      | Snapshot date captured from CLI flag      |
| load_batch | VARCHAR   | Unique batch identifier for ingest run    |
| userId     | INTEGER   | Identifier of the owning user             |
| id         | INTEGER   | Unique todo identifier                    |
| title      | VARCHAR   | Short description of the to-do item       |
| completed  | BOOLEAN   | Completion flag                           |

Comments payload:

| column     | type      | description                               |
|------------|-----------|-------------------------------------------|
| load_date  | DATE      | Snapshot date captured from CLI flag      |
| load_batch | VARCHAR   | Unique batch identifier for ingest run    |
| postId     | INTEGER   | Identifier of the related post            |
| id         | INTEGER   | Unique comment identifier                 |
| name       | VARCHAR   | Comment subject line                      |
| email      | VARCHAR   | Email address of the commenter            |
| body       | VARCHAR   | Full text of the comment                  |

## Notes
- Endpoint returns 200 static placeholder records; use for testing ingestion and end-to-end observability.
- Comments endpoint returns 500 records with similar semantics (`id` as business key).
- Landing prefixes sanitize characters such as `:` into `-` for S3 compatibility; the original batch identifier persists in `load_batch`.
- `ducklake.bronze.api_<dataset>` views surface the latest snapshot per `id`. Query the `_archive` tables for complete history.
- Downstream models should rename fields to `snake_case` if a normalized schema is required.
