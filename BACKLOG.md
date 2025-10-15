# BACKLOG.md — DuckLake Minimal Lakehouse

## Product Overview

A minimal, open-source lakehouse platform built on **DuckDB**, **DuckLake**, and **MinIO**, optimized for simplicity and local deployment. The system supports analytical (BI) and lightweight ML workloads under 100 GB. Ingestion is batch-based (files, APIs), emphasizing transparent data lineage, observability, and ease of iteration.

The build strategy is **incremental**: start with infrastructure and persistence, introduce a real data source early, then layer transformations, testing, and BI.

---

## Epic 1 — Core Infrastructure & Bootstrap

**Goal:** Provide a functioning local environment with object storage and a working catalog.

### Feature 1.1 — Environment & Container Setup

**Acceptance Criteria**

* `docker-compose up` brings up MinIO and initializes a versioned bucket.
* `.env` variables define credentials and endpoints.
* `make up`/`make down` scripts function consistently on any laptop.

### Feature 1.2 — DuckDB + DuckLake Initialization

**Acceptance Criteria**

* `make create_ducklake` creates schemas (`bronze`, `silver`, `gold`, `audit`).
* Catalog (SQLite) connected successfully.
* Seed dataset loaded into a DuckLake table.

---

## Epic 2 — Data Ingestion

**Goal:** Establish ingestion patterns via file and API; introduce a first real data source.

### Feature 2.1 — File Landing & Bronze Tables

**Acceptance Criteria**

* Upload local CSV/Parquet to `s3://lake/landing/...`.
* Bronze tables built from raw data using DuckDB SQL.
* Idempotent ingestion verified through repeated runs.

### Feature 2.2 — API Source Integration

**Acceptance Criteria**

* `scripts/ingest_api.py` fetches and converts sample JSON → Parquet.
* Output uploaded to `s3://lake/landing/api/...`.
* Basic schema documented under `docs/contracts/source_api.md`.

### Feature 2.3 — Public Data Source (Example Integration)

**Goal:** Demonstrate ingestion of an openly available dataset to validate full pipeline and provide realistic BI examples.

**Proposed Dataset:** [European Central Bank (ECB) Exchange Rates API](https://data.ecb.europa.eu/data/exchange-rates) or [NOAA Global Surface Summary of the Day (GSOD)](https://www.ncei.noaa.gov/products/land-based-station/global-summary-day).

**Acceptance Criteria**

* Daily exchange rates or weather data fetched using Python ingest script.
* Data stored as Parquet under `s3://lake/landing/public/ecb_exchange_rates/` or equivalent.
* Corresponding bronze/silver/gold models created:

  * Bronze: raw records.
  * Silver: typed and deduplicated data.
  * Gold: aggregated statistics (e.g., average EUR/USD per month or mean temperature by region).
* Dataset documented in `docs/contracts/source_public.md` with URL, schema, and refresh frequency.

**Acceptance Criteria**

* `scripts/ingest_api.py` fetches and converts sample JSON → Parquet.
* Output uploaded to `s3://lake/landing/api/...`.
* Basic schema documented under `docs/contracts/source_api.md`.

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

