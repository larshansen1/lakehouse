#!/usr/bin/env python3
"""Create a DuckLake catalog backup and upload artifacts to MinIO."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Union
from urllib.parse import quote, urlparse

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import EnvConfig, IngestError, build_env_config, ensure_duckdb_binary, project_root


@dataclass(slots=True)
class BackupArtifacts:
    """Files produced during the backup process."""

    catalog_copy: Path
    duckdb_catalog_copy: Path
    tables_csv: Path
    data_files_csv: Path
    snapshots_csv: Path
    metadata_csv: Path
    manifest_json: Path


def timestamp() -> str:
    """Return a UTC timestamp suitable for paths."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_duckdb(db_path: Path, sql: str) -> None:
    """Execute a DuckDB command against a specific database file."""
    duckdb_bin = ensure_duckdb_binary(None)
    result = subprocess.run(
        [duckdb_bin, str(db_path), "-c", sql],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise IngestError(f"DuckDB command failed:\n{result.stderr}\nExecuted SQL:\n{sql}")


def copy_catalogs(backup_dir: Path) -> tuple[Path, Path]:
    """Copy DuckLake catalog and main catalog.db into the backup directory."""
    root = project_root()
    ducklake_catalog = root / "ducklake" / "catalog.duckdb"
    if not ducklake_catalog.exists():
        raise IngestError(f"DuckLake catalog not found at {ducklake_catalog}")
    catalog_db = root / "catalog.db"
    if not catalog_db.exists():
        raise IngestError(f"Root catalog not found at {catalog_db}")

    ducklake_dest = backup_dir / "ducklake_catalog.duckdb"
    duckdb_dest = backup_dir / "catalog.db"
    shutil.copy2(ducklake_catalog, ducklake_dest)
    shutil.copy2(catalog_db, duckdb_dest)
    return ducklake_dest, duckdb_dest


def escape_path(path: Path) -> str:
    """Escape a file path for embedding in SQL."""
    return str(path).replace("'", "''")


def generate_csvs(catalog_copy: Path, backup_dir: Path) -> tuple[Path, Path, Path, Path]:
    """Emit tables, data_files, snapshots, and metadata CSVs from the DuckLake catalog."""
    tables_csv = backup_dir / "tables.csv"
    data_files_csv = backup_dir / "data_files.csv"
    snapshots_csv = backup_dir / "snapshots.csv"
    metadata_csv = backup_dir / "metadata.csv"

    tables_sql = f"""
COPY (
    WITH data_root AS (
        SELECT value AS data_path
        FROM ducklake_metadata
        WHERE key = 'data_path'
    )
    SELECT
        s.schema_name,
        t.table_name,
        t.table_uuid,
        t.begin_snapshot,
        t.end_snapshot,
        t.path AS relative_path,
        t.path_is_relative,
        (SELECT data_path FROM data_root) AS data_path,
        CASE
            WHEN t.path_is_relative THEN (SELECT data_path FROM data_root) || t.path
            ELSE t.path
        END AS storage_location
    FROM ducklake_table t
    JOIN ducklake_schema s ON s.schema_id = t.schema_id
) TO '{escape_path(tables_csv)}' (FORMAT CSV, HEADER TRUE);
"""
    run_duckdb(catalog_copy, tables_sql)

    data_files_sql = f"""
COPY (
    WITH data_root AS (
        SELECT value AS data_path
        FROM ducklake_metadata
        WHERE key = 'data_path'
    )
    SELECT
        s.schema_name,
        t.table_name,
        df.data_file_id,
        df.begin_snapshot,
        df.end_snapshot,
        df.path AS relative_path,
        df.path_is_relative,
        CASE
            WHEN df.path_is_relative THEN (SELECT data_path FROM data_root) || df.path
            ELSE df.path
        END AS storage_location,
        df.record_count,
        df.file_size_bytes,
        sn.snapshot_time
    FROM ducklake_data_file df
    JOIN ducklake_table t ON t.table_id = df.table_id
    JOIN ducklake_schema s ON s.schema_id = t.schema_id
    LEFT JOIN ducklake_snapshot sn ON sn.snapshot_id = df.begin_snapshot
) TO '{escape_path(data_files_csv)}' (FORMAT CSV, HEADER TRUE);
"""
    run_duckdb(catalog_copy, data_files_sql)

    snapshots_sql = f"""
COPY (
    SELECT snapshot_id, snapshot_time, schema_version
    FROM ducklake_snapshot
    ORDER BY snapshot_id
) TO '{escape_path(snapshots_csv)}' (FORMAT CSV, HEADER TRUE);
"""
    run_duckdb(catalog_copy, snapshots_sql)

    metadata_sql = f"""
COPY (
    SELECT key, value
    FROM ducklake_metadata
) TO '{escape_path(metadata_csv)}' (FORMAT CSV, HEADER TRUE);
"""
    run_duckdb(catalog_copy, metadata_sql)

    return tables_csv, data_files_csv, snapshots_csv, metadata_csv


def load_metadata(metadata_csv: Path) -> dict[str, str]:
    """Read key/value metadata csv into a dictionary."""
    metadata: dict[str, str] = {}
    with metadata_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("key")
            value = row.get("value", "")
            if key:
                metadata[key] = value
    return metadata


def write_manifest(manifest_path: Path, generated_at: str, files: Mapping[str, str], metadata: Mapping[str, str]) -> None:
    """Persist a manifest.json describing backup contents."""
    payload = {
        "generated_at": generated_at,
        "data_path": metadata.get("data_path"),
        "catalog_version": metadata.get("version"),
        "created_by": metadata.get("created_by"),
        "artifacts": files,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sign(key: bytes, msg: str) -> bytes:
    """Return HMAC-SHA256 signature."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive AWS SigV4 signing key."""
    k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return k_signing


def upload_file_to_s3(
    env: EnvConfig,
    key: str,
    file_path: Path,
    *,
    content_type: str,
    region: str = "us-east-1",
) -> None:
    """Upload a file to MinIO/S3 using SigV4 signing."""
    if not file_path.exists():
        raise IngestError(f"Backup artifact missing: {file_path}")

    data = file_path.read_bytes()
    parsed = urlparse(env.endpoint_url)
    if parsed.scheme:
        scheme = parsed.scheme
        host = parsed.netloc or parsed.path
    else:
        scheme = "https" if env.use_ssl else "http"
        host = parsed.path or env.endpoint_host
    host = host.rstrip("/")

    amz_date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]

    canonical_uri = f"/{env.bucket}/{quote(key, safe='/~')}"
    canonical_querystring = ""
    payload_hash = hashlib.sha256(data).hexdigest()

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [
            "PUT",
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = signature_key(env.secret_key, date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization_header = (
        f"AWS4-HMAC-SHA256 Credential={env.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Content-Type": content_type,
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization_header,
    }

    import http.client

    connection: Union[http.client.HTTPConnection, http.client.HTTPSConnection]
    if scheme == "https":
        connection = http.client.HTTPSConnection(host)
    else:
        connection = http.client.HTTPConnection(host)
    try:
        connection.request("PUT", canonical_uri, body=data, headers=headers)
        response = connection.getresponse()
        if response.status >= 300:
            body = response.read().decode("utf-8", errors="ignore")
            raise IngestError(f"S3 upload failed ({response.status} {response.reason}): {body}")
    except OSError as exc:
        raise IngestError(f"Failed to connect to MinIO endpoint '{env.endpoint_url}': {exc}") from exc
    finally:
        connection.close()


def main(argv: list[str]) -> int:
    """Entry point."""
    try:
        env = build_env_config()

        ts = timestamp()
        backup_dir = project_root() / "backups" / "catalog" / ts
        backup_dir.mkdir(parents=True, exist_ok=True)

        catalog_copy, duckdb_copy = copy_catalogs(backup_dir)
        tables_csv, data_files_csv, snapshots_csv, metadata_csv = generate_csvs(catalog_copy, backup_dir)

        metadata = load_metadata(metadata_csv)
        manifest_path = backup_dir / "manifest.json"
        files = {
            "ducklake_catalog": catalog_copy.name,
            "duckdb_catalog": duckdb_copy.name,
            "tables_csv": tables_csv.name,
            "data_files_csv": data_files_csv.name,
            "snapshots_csv": snapshots_csv.name,
            "metadata_csv": metadata_csv.name,
        }
        write_manifest(manifest_path, ts, files, metadata)

        artefacts = BackupArtifacts(
            catalog_copy=catalog_copy,
            duckdb_catalog_copy=duckdb_copy,
            tables_csv=tables_csv,
            data_files_csv=data_files_csv,
            snapshots_csv=snapshots_csv,
            metadata_csv=metadata_csv,
            manifest_json=manifest_path,
        )

        destination_prefix = f"_catalog_backups/{ts}"
        upload_manifest = {
            artefacts.catalog_copy.name: ("application/octet-stream", artefacts.catalog_copy),
            artefacts.duckdb_catalog_copy.name: ("application/octet-stream", artefacts.duckdb_catalog_copy),
            artefacts.tables_csv.name: ("text/csv", artefacts.tables_csv),
            artefacts.data_files_csv.name: ("text/csv", artefacts.data_files_csv),
            artefacts.snapshots_csv.name: ("text/csv", artefacts.snapshots_csv),
            artefacts.metadata_csv.name: ("text/csv", artefacts.metadata_csv),
            artefacts.manifest_json.name: ("application/json", artefacts.manifest_json),
        }

        for filename, (content_type, path) in upload_manifest.items():
            key = f"{destination_prefix}/{filename}"
            upload_file_to_s3(env, key, path, content_type=content_type)

        print(f"Catalog backup completed: s3://{env.bucket}/{destination_prefix}/")
        return 0
    except IngestError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
