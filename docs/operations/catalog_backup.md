# Catalog Backup Playbook

- Run `make backup_catalog` to capture the current DuckLake metadata.
  - Produces a timestamped directory under `backups/catalog/<timestamp>/` with:
    - `ducklake_catalog.duckdb` and project `catalog.db`
    - `tables.csv`, `data_files.csv`, `snapshots.csv`, `metadata.csv`
    - `manifest.json` summarising the run (includes generated timestamp and data path)
- The script uploads all artifacts to `s3://lake/ducklake/_catalog_backups/<timestamp>/` using the MinIO credentials in `.env`.
- To restore:
  1. Download the chosen backup set from `_catalog_backups/<timestamp>/`.
  2. Replace `ducklake/catalog.duckdb` and `catalog.db` in the repo root.
  3. Validate parquet objects referenced in `tables.csv`/`data_files.csv` and resume ingestion.
- Retention: keep the most recent few backups; delete older prefixes from `_catalog_backups/` once the new snapshot is verified.
