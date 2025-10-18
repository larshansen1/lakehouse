# BACKLOG.md — DuckLake Minimal Lakehouse

## Product Overview

A minimal, open-source lakehouse platform built on **DuckDB**, **DuckLake**, and **MinIO**, optimized for simplicity and local deployment. The system supports analytical (BI) and lightweight ML workloads under 100 GB. Ingestion is batch-based (files, APIs), emphasizing transparent data lineage, observability, and ease of iteration.

The build strategy is **incremental**: start with infrastructure and persistence, introduce a real data source early, then layer transformations, testing, and BI.

---

## Epic 1 — Core Infrastructure & Bootstrap

**Goal:** Provide a functioning local environment with object storage and a working catalog.

## Maintenance Backlog

### Maintenance M1 — Stabilize Python Test Harness ✅

**Goal:** Ensure the automated test suite runs without manual environment tweaks.

**Acceptance Criteria**

* `pytest` executes from the project root without manual `PYTHONPATH` overrides or environment hacks.
* Test discovery works under both local development and CI shells.
* Documentation (`README` or contributing guide) updated with the canonical test command.

### Maintenance M2 — Restore Linting and Type-Check Health ✅

**Goal:** Reinstate the project’s static quality gates.

**Acceptance Criteria**

* `ruff check` runs cleanly with no outstanding warnings in the scripts package.
* `mypy` passes for `scripts/` (fixing current signature/type errors).
* CI/pre-commit configuration updated so lint/type checks run automatically.

### Maintenance M3 — Enforce Schema-Aware Storage Prefixes (Cancelled)

**Goal:** Align DuckLake storage layout with Feature 2.5 requirements.

**Acceptance Criteria**

* Bootstrap/ingest routines set `ducklake_set_option('storage.table_prefix', '<schema>/')` (or equivalent) before table creation.
* Existing bronze tables are re-ingested or migrated so MinIO folders follow the `<schema>/<table>/` convention.
* README and operations docs refreshed to explain the schema-prefixed layout and verification steps.

### Maintenance M4 — Implement Required Build & Audit Targets ✅

**Goal:** Provide the operational commands that AGENTS.md mandates.

**Acceptance Criteria**

* `make demo`, `make dbt_run`, and `make audit` targets exist and execute the expected end-to-end, transformation, and observability flows.
* Associated scripts (e.g., dbt project, audit runner) are present and referenced by CI.
* Status checks in PR guidance map directly to available Make targets.

### Maintenance M5 — Modularise Oversized Ingestion Scripts

**Goal:** Improve maintainability by breaking up monolithic ingestion modules.

**Acceptance Criteria**

* `scripts/ingest_ecb_rates.py` and other >200 line modules are refactored into composable helpers under `scripts/lib/`.
* Unit coverage updated to reflect the refactor (existing tests still pass).
* Developer documentation notes the new module boundaries for future contributions.

### Feature 1.1 — Environment & Container Setup ✅

**Acceptance Criteria**

* `docker-compose up` brings up MinIO and initializes a versioned bucket.
* `.env` variables define credentials and endpoints.
* `make up`/`make down` scripts function consistently on any laptop.
* `make check` validates the bucket exists and versioning is enabled.

### Feature 1.2 — DuckDB + DuckLake Initialization ✅

**Acceptance Criteria**

* `make create_ducklake` installs & loads the DuckLake extension, provisions lake storage, and creates schemas (`bronze`, `silver`, `gold`, `audit`) idempotently.
* Catalog (SQLite) located at `catalog.db` connects to the DuckLake catalog.
* Seed dataset is materialized as Parquet in the lake (e.g., `_vol/minio/data/lake/bronze/seed_demo/`) via DuckLake table creation.
* `make create_ducklake` returns zero exit status and `make check_ducklake` verifies schemas and DuckLake-backed seed table exist with data.

---

## Epic 2 — Data Ingestion

**Goal:** Establish ingestion patterns via file and API; introduce a first real data source.

### Feature 2.1 — File Landing & Bronze Tables ✅

**Acceptance Criteria**

* `make ingest_seed_demo` stages `seeds/demo_seed.csv` into MinIO at `s3://lake/landing/seed_demo/seed_demo.parquet` using credentials from `.env`.
* Bronze table `ducklake.bronze.seed_demo` rebuilt from landing objects via a checked-in DuckDB SQL workflow (no manual console steps).
* DuckLake managed storage (`DUCKLAKE_DATA_PATH`) points at the MinIO bucket so bronze tables materialize in `s3://lake/ducklake/...`.
* Ingestion command is idempotent: reruns overwrite the landing object, refresh the bronze table, and report an unchanged row count.
* Script emits a success summary (row counts + object path) so CI or tests can assert ingestion succeeded.

### Feature 2.2 — API Source Integration ✅

**Acceptance Criteria**

* `scripts/ingest_api.py` fetches and converts sample JSON → Parquet using the open endpoint `https://jsonplaceholder.typicode.com/todos`.
* Output uploaded to `s3://lake/landing/api/...`.
* Basic schema documented under `docs/contracts/source_api.md`, including the selected endpoint URL and refresh guidance.

### Feature 2.3 — Public Data Source (Example Integration)

**Goal:** Demonstrate ingestion of an openly available dataset to validate full pipeline and provide realistic BI examples.

**Selected Dataset:** [European Central Bank (ECB) Euro Foreign Exchange Reference Rates](https://data.ecb.europa.eu/explorer/api).

**Rationale**

* Public, stable JSON/CSV API with predictable structure and daily availability.
* Lightweight footprint (≤10 KB/day) yet realistic enough to showcase time-series modelling.
* Aligns with eventual gold-layer analytics such as FX conversions and trend monitoring.

**Acceptance Criteria**

* Add a dedicated CLI (`scripts/ingest_ecb_rates.py` or an `ingest_api.py` mode) and `make ingest_ecb_rates` target that retrieves the ECB reference rates for a requested business date (default: latest published) and writes them to `s3://lake/landing/public/ecb_exchange_rates/load_date=<date>/batch_id=<batch>/rates.parquet`.
* Bronze table `ducklake.bronze.ecb_exchange_rates_archive` (append-only) captures `load_date`, `load_batch`, `rate_date`, `currency_code`, `currency_name`, and `fx_rate` columns. A `ducklake.bronze.ecb_exchange_rates_latest` view exposes the newest rate per currency, keeping the legacy name `ducklake.bronze.ecb_exchange_rates` aliased to the latest view.
* Silver model normalizes datatypes, enforces EUR base currency, deduplicates on `(rate_date, currency_code)`, and flags any missing rates or structural drift via dbt/SQLMesh tests (`not_null`, `relationships`, and a custom check ensuring ≥15 active currencies per load).
* Gold model derives monthly and quarterly aggregates (e.g., average EUR→USD, min/max per currency) and exposes convenience columns for downstream BI/ML.
* Comprehensive documentation in `docs/contracts/source_public.md`: endpoint URLs, query parameters, refresh cadence, schema, constraints, and sample queries illustrating how to locate historical snapshots vs. the latest view.
* Automated coverage: pytest or integration test stubs that mock the ECB response, plus dbt/SQLMesh tests validating the bronze and silver outputs. Include the new ingestion target in the regression checklist (`make demo` or similar).

### Feature 2.4 — Bronze Snapshot Archive & Latest View ✅

**Goal:** Preserve every full-load snapshot in bronze while exposing a clean “latest records” view for downstream layers.

**Acceptance Criteria**

* File-based ingesters accept optional `--load-date` (YYYY-MM-DD) and `--batch-id` (defaults to current UTC timestamp) and write landing data to `s3://lake/landing/<dataset>/load_date=<date>/batch_id=<batch_id>/...`.
* Bronze archive table `ducklake.bronze.seed_demo_archive` appends every ingest with both `load_date` and `load_batch` columns; no `CREATE OR REPLACE` statements that drop history.
* View (or materialized table) `ducklake.bronze.seed_demo_latest` returns the most recent row per business key using `ORDER BY load_date DESC, load_batch DESC`, backing existing silver models.
* README documents how to run ingest scripts with fixed `--load-date`/`--batch-id` values for deterministic development/testing and explains the partition hierarchy.
* Contract/docs updated to mention archive vs. latest semantics and where historical snapshots live.

### Feature 2.5 — Schema-Aware Storage Prefixes (Cancelled)

**Goal:** Ensure DuckLake writes managed tables under schema-specific prefixes (e.g., `bronze/seed_demo/`) to make backup/recovery and browsing in MinIO intuitive.

**Acceptance Criteria**

* DuckLake ingest/bootstrap logic sets `ducklake_set_option('storage.table_prefix', '<schema>/')` (or equivalent) before creating tables so managed data lands under `s3://lake/ducklake/<schema>/<table>/...`.
* README documents the configuration and how to verify the folder layout in MinIO.
* Ingest scripts respect the prefix automatically; no manual steps required.
* Existing tables are migrated or re-ingested so bronze data appears under the new schema-prefixed path.

### Feature 2.6 — Catalog Backup Manifests ✅

**Goal:** Produce human-readable and restorable snapshots of DuckLake metadata alongside parquet data to simplify disaster recovery.

**Acceptance Criteria**

* Add a command (e.g., `make backup_catalog`) that exports the DuckLake catalog (SQLite) and a JSON/CSV manifest of schemas, tables, snapshots, and storage locations to `s3://lake/ducklake/_catalog_backups/<timestamp>/`.
* Document how to restore from the backup (copy catalog DB + ensure parquet paths exist) and reference it in README.
* CI or local checklist updated to remind contributors to run the backup command before major changes/releases.
* Contracts/docs mention where catalog backups are stored and how long they are retained.

---

## Epic 3 — Transformation Pipeline

**Goal:** Enable structured transformation flow from bronze → silver → gold.

### Feature 3.1 — dbt/SQLMesh Setup

**Acceptance Criteria**

* dbt project compiles and runs against DuckDB.
* Bronze, silver, and gold folders contain model examples.
* Basic dbt tests (`not_null`, `unique`) pass.

### Feature 3.2 — Silver Model Standardization

**Acceptance Criteria**

* Silver models cast datatypes and clean raw data.
* Schema tests reach ≥95% pass rate.
* Schema contracts updated accordingly.

### Feature 3.3 — Gold Analytical Views

**Acceptance Criteria**

* At least one aggregation (e.g., sales summary) materialized.
* Gold models documented with lineage to upstream tables.
* BI tools can query gold schema via DuckDB.

---

## Epic 4 — Observability & Lineage

**Goal:** Provide simple, reliable visibility into data state and provenance.

### Feature 4.1 — Data Health Auditing

**Acceptance Criteria**

* `make audit` populates `dl.audit.table_health` with row counts and timestamps.
* Audit logs persisted daily via cron or CI artifact.

### Feature 4.2 — Lineage Visualization

**Acceptance Criteria**

* `dbt docs generate` (or SQLMesh equivalent) produces lineage HTML.
* Generated documentation published or versioned in `/docs/lineage/`.

---

## Epic 5 — BI Integration

**Goal:** Make gold data explorable by non‑technical users.

### Feature 5.1 — Metabase Connection

**Acceptance Criteria**

* Metabase connects to DuckDB file (read-only credentials).
* Queries and dashboards validated.

### Feature 5.2 — Example Dashboard

**Acceptance Criteria**

* Demo dashboard using gold tables (e.g., revenue by date/product).
* Configuration documented under `metabase/connection-notes.md`.

---

## Epic 6 — Quality, CI/CD & Governance

**Goal:** Automate checks, ensure reproducibility, and maintain documentation.

### Feature 6.1 — Linting & Testing

**Acceptance Criteria**

* Python code passes `ruff` and `mypy`.
* SQL passes `sqlfluff`.
* Unit tests (pytest) cover ≥80% of branches.

### Feature 6.2 — CI/CD Pipeline

**Acceptance Criteria**

* CI executes `make demo`, `make dbt_run`, and `make audit`.
* Artifacts (audit CSV + lineage HTML) uploaded to build output.

### Feature 6.3 — Contracts & Documentation

**Acceptance Criteria**

* Each dataset described under `docs/contracts/`.
* `.env.example` reflects required keys.
* Changelog updated on releases.

---

## Build Order Summary

1. **Epic 1:** Infrastructure foundation.
2. **Epic 2:** Real data source integration (early validation).
3. **Epic 3:** Transformations and modeling.
4. **Epic 4:** Observability and lineage.
5. **Epic 5:** BI exposure and dashboards.
6. **Epic 6:** Quality, automation, and governance.

Each epic delivers a usable increment—by Epic 2 you already have live data flowing through the system.
