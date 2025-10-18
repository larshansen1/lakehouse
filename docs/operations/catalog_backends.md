# Catalog Backends

DuckLake can store its catalog metadata either in a local DuckDB file or in Postgres. The choice is controlled by the `DUCKLAKE_BACKEND` environment variable and the accompanying settings in `.env`.

## DuckDB (default)

- Metadata lives in `ducklake/catalog.duckdb` alongside the repository.
- `make bootstrap` / `make create_ducklake` create the catalog file, schemas, and seed data automatically.
- Use this mode for the simplest local setup; all state is kept on disk under the repo and `_vol/minio`.

## Postgres

- Set `DUCKLAKE_BACKEND=postgres` and configure `DUCKLAKE_PG_HOST`, `DUCKLAKE_PG_PORT`, `DUCKLAKE_PG_DB`, `DUCKLAKE_PG_USER`, and `DUCKLAKE_PG_PASSWORD`.
- `docker-compose.yml` includes a `postgres` service exposed on `${DUCKLAKE_PG_PORT:-55432}` to avoid clashing with a local Postgres install.
- `make up` starts the database, and the bootstrap scripts automatically load the DuckLake extension with the Postgres connection string.
- State is persisted under `_vol/postgres/data/`; remove this directory to reset the Postgres catalog.
- Tooling automatically switches DuckDB invocations to `:memory:` when using Postgres, so multiple ingestion/analysis sessions can run without fighting over a locked `catalog.db` file.
- The interactive shell (`make ducklake_shell`) still uses an in-memory DuckDB compute session; DuckLake metadata locking semantics currently limit concurrent interactive shells even when Postgres backs the catalog.

## Switching Between Backends

There is no automatic migration between catalog backends. To switch safely:

1. Stop the stack (`make down`) so MinIO and Postgres release their files.
2. Archive or delete the previous catalog artifacts:
   - DuckDB → remove `ducklake/catalog.duckdb`.
   - Postgres → remove `_vol/postgres/data/`.
3. Clear or archive the lake data under `_vol/minio/data/ducklake/` (and the corresponding MinIO bucket prefix) to avoid mixing metadata and data from different backends.
4. Update `.env` with the desired `DUCKLAKE_BACKEND` and associated settings.
5. Bring the stack back up (`make up`) and rerun `make bootstrap` to initialise schemas and seed data on the new backend.

All helper scripts (`make demo`, `make audit`, `make ducklake_shell`, ingestion CLIs) read the same environment variables, so no further changes are required once the backend is configured.
