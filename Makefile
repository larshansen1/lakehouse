SHELL := /bin/sh
COMPOSE ?= docker compose
DUCKDB ?= duckdb
PYTHON ?= python3
DUCKLAKE_METADATA_PATH ?= ducklake/catalog.duckdb
DUCKLAKE_DATA_PATH ?= ducklake/data

.PHONY: up down logs check create_ducklake check_ducklake bootstrap

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
	DUCKDB=$(DUCKDB) DUCKLAKE_METADATA_PATH=$(DUCKLAKE_METADATA_PATH) DUCKLAKE_DATA_PATH=$(DUCKLAKE_DATA_PATH) ./scripts/create_ducklake.sh

check_ducklake:
	$(PYTHON) scripts/check_ducklake.py

bootstrap: up create_ducklake check_ducklake
