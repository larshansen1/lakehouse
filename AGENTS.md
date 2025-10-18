# AGENTS.md — Development, Deployment & Testing Guidelines

This document provides practical guidelines for developing, testing, and deploying code in the **DuckLake Minimal Lakehouse** project. It replaces high-level product description with actionable standards for contributors and automation agents (e.g., Codex).

---

## 0. Git, Branching & Release Flow

### .gitignore
- **Always consider .gitignore** - never commit things like:
- Data dirs (including docker volumes)
- Virtual Environments
- Logfiles and dirs
- Local database files
- Etc.

### Branching Strategy
- **Trunk-based with short-lived feature branches.** Create a branch **per feature/ticket**; keep it small and focused.
- Naming: `feat/ep2-2-api-ingest`, `feat/public-ecb-source`, `fix/audit-null-bug`, `chore/ci-cache`, `docs/contracts-ecb`.
- Lifetime: ≤ 3–5 days. Rebase regularly on `main` to avoid drift.

### Commits & Merges
- Use **Conventional Commits** with a scope when helpful: `feat(models): add silver normalization for sales`.
- Prefer **squash-merge** to keep history linear and tie the branch to one commit on `main`.
- Keep commits atomic: code + tests + docs for one concern.

### PR Policy
- Size target: **≤ 400 changed lines** (excluding generated files). Split larger changes.
- Required checklist (CI enforces most): lint, type-check, unit tests, `dbt run && dbt test`, docs/contracts updated.
- Request review from **CODEOWNERS** for impacted areas (`dbt/models/**`, `sql/**`, `scripts/**`).

### Release & Tags
- Tag releases as `v0.x.y`. Use GitHub Releases to attach lineage HTML and audit snapshot.
- Hotfixes: branch from the tagged commit (`hotfix/v0.x.y+1`), PR back to `main`, retag.

### Pre-commit Hooks (recommended)
- Install a local **pre-commit** config that runs: `ruff format`, `ruff check`, `mypy`, `sqlfluff lint`, and `pytest -q` (fast set).
- Block commits if any of the above fail.

## 1. Development Environment

### Languages and Tools
- **Python 3.11+** for scripts and orchestration.
- **DuckDB** CLI for local analytics and SQL execution.
- **dbt-duckdb** or **SQLMesh** for ELT transformations.
- **MinIO** (via Docker) as S3-compatible storage backend.

### Setup & Bootstrapping
- Clone the repo, create `.env` from `.env.example`, and run `make demo`.
- Use `docker compose up -d` to bring up MinIO and supporting services.
- Run SQL files with `duckdb < sql/bootstrap_ducklake.sql` to (re)initialize catalog and schemas.

### Coding Guidelines
- Follow **PEP 8** with 4-space indentation and clear docstrings.
- Use **type hints** for public functions.
- Favor **functional, idempotent scripts** that read/write from S3 and avoid global state.
- Keep Python modules under 200 lines; reuse logic under `scripts/lib/`.
- For SQL, prefer readable, ANSI-compliant DuckDB syntax with lowercase identifiers and snake_case tables.
- Before implementing new capabilities, ensure the work is represented in `BACKLOG.md` (create/update the relevant entry first).

### Linting & Quality
- Run `ruff check` for Python linting.
- Run `mypy` for static type checking.
- Run `sqlfluff lint` (dialect `duckdb`) for SQL style consistency.

---

## 2. Testing & Validation

### Unit & Integration Tests
- Use **pytest** for Python testing.
- Include tests for:
  - API ingest scripts (mock requests/responses).
  - File ingestion idempotence.
  - Schema validation for bronze/silver models.
- Store tests under `tests/` with mirrors of module structure.
- Maintain ≥80% branch coverage.

### Data Validation (dbt/SQLMesh)
- Use built-in **dbt tests** (`not_null`, `unique`, `relationships`) on silver/gold models.
- Add custom tests for business rules where appropriate.
- Run `dbt run && dbt test` before committing changes.

### Manual Smoke Tests
- Run `make demo` to verify end-to-end build.
- Confirm that:
  - Seeds load correctly into bronze tables.
  - Silver and gold models compile and execute.
  - `make audit` records row counts in `dl.audit.table_health`.

---

## 3. Deployment & Automation

### Local Deployment
- The platform runs locally with Docker only — no external services needed.
- Ensure persistence for MinIO and catalog (volumes mounted under `_vol/`).

### CI/CD
- **Branch policy:** Every feature is a branch with a PR into `main`. CI runs on PRs and on `main`.
- **Concurrency:** Use a CI concurrency group to **cancel in-progress** runs for the same branch when new commits arrive.
- **Caching:** Cache Python venv and dbt packages; reuse Docker layers for MinIO images.
- **Matrix (optional):** Run Python `3.11` and `3.12` if you touch Python-heavy logic.

**Recommended pipeline stages:**
1. **Setup**
   - Check out repo; restore caches; install Python deps; `docker compose up -d` (MinIO).
   - Export env from `.env.example` with CI-safe defaults.
2. **Build & Test**
   - `make demo` **or** `make dbt_run` (for faster cycles on PRs touching only SQL).
   - Run `ruff check`, `mypy`, `sqlfluff lint`, `pytest`.
   - `dbt test` must pass; fail the build on any data test failure.
3. **Audit**
   - `make audit`; export `dl.audit.table_health` as CSV and upload as artifact.
4. **Lineage Docs**
   - `dbt docs generate`; upload the HTML site as an artifact named `lineage`.
5. **Security (optional but recommended)**
   - Secrets scan (`gitleaks` or `trufflehog`); dependency scan for Python (`pip-audit`).

**Status checks required to merge:** Build, Lint, Tests, dbt tests, Lineage generated.

### Catalog & Backup
- The catalog (SQLite) is stored locally as `catalog.db`.
- Run `make backup_catalog` regularly to version the metadata.
- Enable versioning in MinIO for Parquet data.

---

## 4. Code Review & Pull Requests
- Use **Conventional Commits** (`feat:`, `fix:`, `chore:`).
- Each PR must include:
  - Passing test and lint results.
  - Updated `.env.example` and `README` if environment variables changed.
  - Schema updates documented under `docs/contracts/`.
- Avoid committing generated artifacts (lineage docs, compiled SQL) unless explicitly versioned.

---

## 5. Security & Configuration Hygiene
- Never commit secrets or tokens.
- Document required keys in `.env.example`.
- Use separate credentials for read/write roles when accessing MinIO.
- Apply principle of least privilege when exposing BI connections.

---

## 6. Observability & Troubleshooting
- Logs should be printed to stdout/stderr; avoid persistent logs unless critical.
- `make audit` serves as a lightweight data health monitor.
- For failures, run `duckdb` interactively and inspect `duckdb_tables()` and `ducklake.history()`.

---

## 7. Release & Versioning
- Tag releases using semantic versioning (`v0.x.y`).
- Document breaking schema changes in `CHANGELOG.md` and relevant contract docs.
- Keep releases reproducible: same dataset + same SQL = same results.

---

**Summary Checklist**
- [ ] Code formatted (`ruff format`) and type-checked (`mypy`).
- [ ] Unit and dbt tests green.
- [ ] `make demo` runs successfully.
- [ ] Updated docs/contracts and `.env.example`.
- [ ] Artifacts (audit, lineage) generated and verified.

