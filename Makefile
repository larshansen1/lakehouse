SHELL := /bin/sh
COMPOSE ?= docker compose
DUCKDB ?= duckdb
PYTHON ?= python3

.PHONY: up down logs check create_ducklake check_ducklake bootstrap ingest_seed_demo ingest_api_todos ingest_api_comments ingest_ecb_rates backfill_ecb_rates ducklake_shell backup_catalog demo dbt_run audit

ARGS ?=

up:
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down --remove-orphans

logs:
	$(COMPOSE) logs -f minio

check:
	$(COMPOSE) exec -T minio-init /bin/sh -c "\
		mc alias list ducklake >/dev/null && \
		mc stat ducklake/\$$MINIO_BUCKET_NAME >/dev/null && \
		mc version info ducklake/\$$MINIO_BUCKET_NAME >/dev/null && \
		echo 'MinIO bucket exists and versioning is enabled.' \
	"

create_ducklake:
	DUCKDB=$(DUCKDB) PYTHON=$(PYTHON) ./scripts/create_ducklake.sh

check_ducklake:
	$(PYTHON) scripts/check_ducklake.py

ingest_seed_demo:
	$(PYTHON) scripts/ingest_file.py --dataset seed_demo --source seeds/demo_seed.csv --table seed_demo $(ARGS)

ingest_api_todos:
	$(PYTHON) scripts/ingest_api.py --dataset api/todos --table api_todos --object-name todos --endpoint https://jsonplaceholder.typicode.com/todos $(ARGS)

ingest_api_comments:
	$(PYTHON) scripts/ingest_api.py --dataset api/comments --table api_comments --object-name comments --endpoint https://jsonplaceholder.typicode.com/comments $(ARGS)

ingest_ecb_rates:
	$(PYTHON) scripts/ingest_ecb_rates.py $(ARGS)

ducklake_shell:
	$(PYTHON) scripts/open_ducklake_shell.py $(ARGS)

backfill_ecb_rates:
	$(PYTHON) scripts/backfill_ecb_rates.py $(ARGS)

bootstrap: up create_ducklake check_ducklake

backup_catalog:
	$(PYTHON) scripts/backup_catalog.py

demo:
	$(PYTHON) scripts/run_demo.py $(ARGS)

dbt_run:
	$(PYTHON) scripts/run_transforms.py $(ARGS)

audit:
	$(PYTHON) scripts/run_audit.py $(ARGS)
