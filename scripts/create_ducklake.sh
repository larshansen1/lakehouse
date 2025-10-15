#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUCKDB_BIN="${DUCKDB:-duckdb}"

METADATA_RELATIVE="${DUCKLAKE_METADATA_PATH:-ducklake/catalog.duckdb}"
DATA_RELATIVE="${DUCKLAKE_DATA_PATH:-ducklake/data}"

if [[ "${METADATA_RELATIVE}" = /* ]]; then
  METADATA_PATH="${METADATA_RELATIVE}"
else
  METADATA_PATH="${PROJECT_ROOT}/${METADATA_RELATIVE}"
fi

if [[ "${DATA_RELATIVE}" = /* ]]; then
  DATA_PATH="${DATA_RELATIVE}"
else
  DATA_PATH="${PROJECT_ROOT}/${DATA_RELATIVE}"
fi

mkdir -p "$(dirname "${METADATA_PATH}")"
mkdir -p "${DATA_PATH}"

SEED_CSV="${PROJECT_ROOT}/seeds/demo_seed.csv"
if [[ ! -f "${SEED_CSV}" ]]; then
  echo "Seed CSV not found at ${SEED_CSV}" >&2
  exit 1
fi

"${DUCKDB_BIN}" "${PROJECT_ROOT}/catalog.db" <<SQL
INSTALL ducklake;
LOAD ducklake;

ATTACH '${METADATA_PATH}' AS ducklake (TYPE DUCKLAKE, DATA_PATH '${DATA_PATH}');

CREATE SCHEMA IF NOT EXISTS ducklake.bronze;
CREATE SCHEMA IF NOT EXISTS ducklake.silver;
CREATE SCHEMA IF NOT EXISTS ducklake.gold;
CREATE SCHEMA IF NOT EXISTS ducklake.audit;

CREATE TABLE IF NOT EXISTS ducklake.bronze.seed_demo (
  id INTEGER,
  name VARCHAR,
  load_timestamp TIMESTAMP
);

DELETE FROM ducklake.bronze.seed_demo;

INSERT INTO ducklake.bronze.seed_demo
SELECT
  CAST(id AS INTEGER) AS id,
  CAST(name AS VARCHAR) AS name,
  CAST(load_timestamp AS TIMESTAMP) AS load_timestamp
FROM read_csv_auto(
      '${SEED_CSV}',
      header := true,
      columns := {'id': 'INTEGER', 'name': 'VARCHAR', 'load_timestamp': 'TIMESTAMP'}
    );

DETACH ducklake;
SQL
