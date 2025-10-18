#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUCKDB_BIN="${DUCKDB:-duckdb}"
PYTHON_BIN="${PYTHON:-python3}"

# Load .env if available so defaults mirror runtime configuration.
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${PROJECT_ROOT}/.env"
  set +a
fi

MINIO_ROOT_USER="${MINIO_ROOT_USER:-ducklake}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-ducklake-insecure-change-me}"
MINIO_BUCKET_NAME="${MINIO_BUCKET_NAME:-lake}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"

BACKEND_RAW="${DUCKLAKE_BACKEND:-duckdb}"
BACKEND="$(printf "%s" "${BACKEND_RAW}" | tr '[:upper:]' '[:lower:]')"

DATA_RELATIVE="${DUCKLAKE_DATA_PATH:-}"
DEFAULT_DATA_S3="s3://${MINIO_BUCKET_NAME}/ducklake"
if [[ -z "${DATA_RELATIVE}" || ( "${DATA_RELATIVE}" != s3://* && "${DATA_RELATIVE}" != http://* && "${DATA_RELATIVE}" != https://* ) ]]; then
  if [[ -n "${DATA_RELATIVE}" && "${DATA_RELATIVE}" != "${DEFAULT_DATA_S3}" ]]; then
    echo "Info: overriding DUCKLAKE_DATA_PATH='${DATA_RELATIVE}' with '${DEFAULT_DATA_S3}' for MinIO-backed storage." >&2
  fi
  DATA_RELATIVE="${DEFAULT_DATA_S3}"
fi

DATA_PATH="${DATA_RELATIVE%/}"

ATTACH_TARGET_RAW=""
BACKEND_SQL=""
METADATA_PATH=""

case "${BACKEND}" in
  duckdb)
    METADATA_RELATIVE="${DUCKLAKE_METADATA_PATH:-ducklake/catalog.duckdb}"
    if [[ "${METADATA_RELATIVE}" = /* ]]; then
      METADATA_PATH="${METADATA_RELATIVE}"
    else
      METADATA_PATH="${PROJECT_ROOT}/${METADATA_RELATIVE}"
    fi
    mkdir -p "$(dirname "${METADATA_PATH}")"
    ATTACH_TARGET_RAW="${METADATA_PATH}"
    ;;
  postgres)
    PG_HOST="${DUCKLAKE_PG_HOST:-127.0.0.1}"
    PG_PORT="${DUCKLAKE_PG_PORT:-55432}"
    PG_DB="${DUCKLAKE_PG_DB:-ducklake}"
    PG_USER="${DUCKLAKE_PG_USER:-ducklake}"
    PG_PASSWORD="${DUCKLAKE_PG_PASSWORD:-}"
    PG_SSLMODE="${DUCKLAKE_PG_SSLMODE:-disable}"
    PG_CONN="host=${PG_HOST} port=${PG_PORT} dbname=${PG_DB} user=${PG_USER}"
    if [[ -n "${PG_PASSWORD}" ]]; then
      PG_CONN+=" password=${PG_PASSWORD}"
    fi
    if [[ -n "${PG_SSLMODE}" ]]; then
      PG_CONN+=" sslmode=${PG_SSLMODE}"
    fi
    ATTACH_TARGET_RAW="${PG_CONN}"
    BACKEND_SQL=$'INSTALL postgres;\nLOAD postgres;\n'
    ;;
  *)
    echo "Unsupported DUCKLAKE_BACKEND '${BACKEND_RAW}'. Use 'duckdb' or 'postgres'." >&2
    exit 1
    ;;
esac

if [[ -z "${ATTACH_TARGET_RAW}" ]]; then
  echo "Unable to resolve DuckLake catalog target for backend '${BACKEND}'." >&2
  exit 1
fi

if [[ "${MINIO_ENDPOINT}" == http://* ]]; then
  S3_ENDPOINT="${MINIO_ENDPOINT#http://}"
  S3_USE_SSL=false
elif [[ "${MINIO_ENDPOINT}" == https://* ]]; then
  S3_ENDPOINT="${MINIO_ENDPOINT#https://}"
  S3_USE_SSL=true
else
  S3_ENDPOINT="${MINIO_ENDPOINT}"
  S3_USE_SSL=false
fi
S3_ENDPOINT="${S3_ENDPOINT%/}"

escape_sql() {
  printf "%s" "$1" | sed "s/'/''/g"
}

S3_ENDPOINT_ESCAPED="$(escape_sql "${S3_ENDPOINT}")"
ACCESS_KEY_ESCAPED="$(escape_sql "${MINIO_ROOT_USER}")"
SECRET_KEY_ESCAPED="$(escape_sql "${MINIO_ROOT_PASSWORD}")"
ATTACH_TARGET_ESCAPED="$(escape_sql "${ATTACH_TARGET_RAW}")"
DATA_PATH_ESCAPED="$(escape_sql "${DATA_PATH}")"

SEED_CSV="${PROJECT_ROOT}/seeds/demo_seed.csv"
[[ -f "${SEED_CSV}" ]] || {
  echo "Seed CSV not found at ${SEED_CSV}" >&2
  exit 1
}

DUCKDB_DATABASE="${PROJECT_ROOT}/catalog.db"
if [[ "${BACKEND}" == "postgres" ]]; then
  DUCKDB_DATABASE=":memory:"
fi

"${DUCKDB_BIN}" "${DUCKDB_DATABASE}" <<SQL
INSTALL httpfs;
LOAD httpfs;
${BACKEND_SQL}INSTALL ducklake;
LOAD ducklake;

SET s3_endpoint='${S3_ENDPOINT_ESCAPED}';
SET s3_url_style='path';
SET s3_use_ssl=${S3_USE_SSL};
SET s3_access_key_id='${ACCESS_KEY_ESCAPED}';
SET s3_secret_access_key='${SECRET_KEY_ESCAPED}';

ATTACH '${ATTACH_TARGET_ESCAPED}' AS ducklake (TYPE DUCKLAKE, DATA_PATH '${DATA_PATH_ESCAPED}', OVERRIDE_DATA_PATH true);

CREATE SCHEMA IF NOT EXISTS ducklake.bronze;
CREATE SCHEMA IF NOT EXISTS ducklake.silver;
CREATE SCHEMA IF NOT EXISTS ducklake.gold;
CREATE SCHEMA IF NOT EXISTS ducklake.audit;

DETACH ducklake;
SQL

export DUCKLAKE_BACKEND="${BACKEND}"
export DUCKLAKE_DATA_PATH="${DATA_PATH}"
if [[ -n "${METADATA_PATH}" ]]; then
  export DUCKLAKE_METADATA_PATH="${METADATA_PATH}"
else
  unset DUCKLAKE_METADATA_PATH
fi

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/ingest_file.py" \
  --dataset seed_demo \
  --source "${SEED_CSV}" \
  --table seed_demo
