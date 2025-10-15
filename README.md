# DuckLake Minimal Lakehouse

## Local Environment Bootstrap

1. Copy `.env.example` to `.env` and customize credentials (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET_NAME`).
2. Start the stack with `make up`. This brings up MinIO, creates the bucket defined in `.env`, and enables object versioning.
3. Visit the MinIO console at `http://localhost:9001` (default) to confirm the bucket status. S3 clients can connect via `http://localhost:9000`.
4. Run `make check` to validate that the bucket exists and versioning is turned on.
5. Execute `make bootstrap` to bring up MinIO (if not already), initialize DuckLake metadata, and load the seed dataset into `ducklake.bronze.seed_demo` as Parquet.
6. Alternatively, run `make create_ducklake` followed by `make check_ducklake` when you need to refresh the catalog only.
7. Tear down the environment with `make down` when finished.

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

Each DuckDB session must load the DuckLake extension and reattach the lake metadata before querying:

```sql
LOAD ducklake;
ATTACH 'ducklake/catalog.duckdb' AS ducklake (TYPE DUCKLAKE, DATA_PATH 'ducklake/data');
USE ducklake;
SELECT * FROM bronze.seed_demo LIMIT 5;
SELECT * FROM ducklake_snapshots('ducklake');
DETACH ducklake;
```

Adjust the paths if you override `DUCKLAKE_METADATA_PATH` or `DUCKLAKE_DATA_PATH` in your environment.
