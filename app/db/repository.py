"""Scan session persistence.

Every read and write is scoped by ``tenant_id``. The PostgreSQL
implementation additionally sets ``app.tenant_id`` per transaction so the
row-level security policy hides other tenants' rows even if a query forgot
its tenant predicate.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from importlib import resources
from typing import Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

_JSON_COLUMNS = ("images", "extraction", "quality", "worker", "corrected_fields")


@dataclass
class ScanRecord:
    scan_id: str
    tenant_id: str
    request_id: str
    document_type: str
    country: str
    status: str
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    images: list = field(default_factory=list)
    extraction: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    worker: dict = field(default_factory=dict)
    worker_schema_ref: str | None = None
    corrected_fields: list = field(default_factory=list)
    document_hash: str | None = None
    document_number_last4: str | None = None
    portrait_detected: bool = False
    qr_present: bool = False
    created_by: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    idempotency_key: str | None = None
    request_fingerprint: str | None = None


_COLUMNS = tuple(f.name for f in fields(ScanRecord))


class ScanRepository(Protocol):
    def create(self, record: ScanRecord, actor: str | None) -> None: ...

    def get(self, tenant_id: str, scan_id: str) -> ScanRecord | None: ...

    def get_by_idempotency_key(self, tenant_id: str, key: str) -> ScanRecord | None: ...

    def list_recent(
        self, tenant_id: str, *, limit: int, cursor: str | None = None
    ) -> tuple[list[ScanRecord], str | None]: ...

    def confirm(
        self,
        tenant_id: str,
        scan_id: str,
        *,
        extraction: dict,
        corrected_fields: list,
        document_hash: str | None,
        document_number_last4: str | None,
        confirmed_by: str | None,
        confirmed_at: datetime,
    ) -> ScanRecord | None: ...

    def ping(self) -> bool: ...


class DuplicateIdempotencyKey(RuntimeError):
    pass


class ConfirmConflict(RuntimeError):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class InMemoryScanRepository:
    """Test/dev implementation with the same tenant semantics."""

    def __init__(self) -> None:
        self._rows: dict[str, ScanRecord] = {}
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def create(self, record: ScanRecord, actor: str | None) -> None:
        with self._lock:
            if record.idempotency_key and self.get_by_idempotency_key(record.tenant_id, record.idempotency_key):
                raise DuplicateIdempotencyKey(record.idempotency_key)
            self._rows[record.scan_id] = copy.deepcopy(record)
            self.events.append(
                {"scan_id": record.scan_id, "tenant_id": record.tenant_id, "event": "created", "actor": actor}
            )

    def get(self, tenant_id: str, scan_id: str) -> ScanRecord | None:
        row = self._rows.get(scan_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return copy.deepcopy(row)

    def get_by_idempotency_key(self, tenant_id: str, key: str) -> ScanRecord | None:
        for row in self._rows.values():
            if row.tenant_id == tenant_id and row.idempotency_key == key:
                return copy.deepcopy(row)
        return None

    def list_recent(
        self, tenant_id: str, *, limit: int, cursor: str | None = None
    ) -> tuple[list[ScanRecord], str | None]:
        rows = sorted(
            (r for r in self._rows.values() if r.tenant_id == tenant_id),
            key=lambda r: (r.created_at, r.scan_id),
            reverse=True,
        )
        if cursor:
            indexes = [i for i, row in enumerate(rows) if row.scan_id == cursor]
            if not indexes:
                return [], None
            rows = rows[indexes[0] + 1 :]
        page = rows[: limit + 1]
        next_cursor = page[limit - 1].scan_id if len(page) > limit else None
        return [copy.deepcopy(r) for r in page[:limit]], next_cursor

    def confirm(self, tenant_id, scan_id, **changes) -> ScanRecord | None:
        with self._lock:
            row = self._rows.get(scan_id)
            if row is None or row.tenant_id != tenant_id:
                return None
            if row.status != "pending_review":
                raise ConfirmConflict(row.status)
            for key, value in changes.items():
                setattr(row, key, copy.deepcopy(value))
            row.status = "confirmed"
            row.updated_at = changes["confirmed_at"]
            self.events.append(
                {
                    "scan_id": scan_id,
                    "tenant_id": tenant_id,
                    "event": "confirmed",
                    "actor": changes.get("confirmed_by"),
                }
            )
            return copy.deepcopy(row)

    def all_rows(self) -> list[dict]:
        return [asdict(r) for r in self._rows.values()]

    def ping(self) -> bool:
        return True


def _migrations() -> list[tuple[str, str]]:
    pkg = resources.files("app.db").joinpath("migrations")
    files = sorted((p for p in pkg.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name)
    return [(p.name, p.read_text(encoding="utf-8")) for p in files]


class PostgresScanRepository:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, open=True, kwargs={"row_factory": dict_row}
        )

    def close(self) -> None:
        self._pool.close()

    def migrate(self) -> list[str]:
        """Apply pending migrations under an advisory lock. Idempotent."""
        applied: list[str] = []
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('document_intelligence_migrations'))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
            for version, sql in _migrations():
                if version in done:
                    continue
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied.append(version)
        return applied

    @staticmethod
    def _to_record(row: dict | None) -> ScanRecord | None:
        if row is None:
            return None
        return ScanRecord(**{k: row[k] for k in _COLUMNS})

    def create(self, record: ScanRecord, actor: str | None) -> None:
        values = asdict(record)
        params = [Jsonb(values[c]) if c in _JSON_COLUMNS else values[c] for c in _COLUMNS]
        placeholders = ", ".join(["%s"] * len(_COLUMNS))
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (record.tenant_id,))
            try:
                with conn.transaction():
                    conn.execute(
                        f"INSERT INTO document_scans ({', '.join(_COLUMNS)}) VALUES ({placeholders})",  # noqa: S608
                        params,
                    )
            except psycopg.errors.UniqueViolation as exc:
                raise DuplicateIdempotencyKey(record.idempotency_key) from exc
            conn.execute(
                "INSERT INTO document_scan_events (scan_id, tenant_id, event, actor, details)"
                " VALUES (%s, %s, %s, %s, %s)",
                (record.scan_id, record.tenant_id, "created", actor, Jsonb({"status": record.status})),
            )

    def get(self, tenant_id: str, scan_id: str) -> ScanRecord | None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            row = conn.execute(
                "SELECT * FROM document_scans WHERE tenant_id = %s AND scan_id = %s", (tenant_id, scan_id)
            ).fetchone()
        return self._to_record(row)

    def get_by_idempotency_key(self, tenant_id: str, key: str) -> ScanRecord | None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            row = conn.execute(
                "SELECT * FROM document_scans WHERE tenant_id = %s AND idempotency_key = %s", (tenant_id, key)
            ).fetchone()
        return self._to_record(row)

    def list_recent(
        self, tenant_id: str, *, limit: int, cursor: str | None = None
    ) -> tuple[list[ScanRecord], str | None]:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            params: list[object] = [tenant_id]
            where = "tenant_id = %s"
            if cursor:
                marker = conn.execute(
                    "SELECT created_at, scan_id FROM document_scans WHERE tenant_id = %s AND scan_id = %s",
                    (tenant_id, cursor),
                ).fetchone()
                if marker is None:
                    return [], None
                where += " AND (created_at, scan_id) < (%s, %s)"
                params.extend([marker["created_at"], marker["scan_id"]])
            params.append(limit + 1)
            rows = conn.execute(
                f"SELECT * FROM document_scans WHERE {where} ORDER BY created_at DESC, scan_id DESC LIMIT %s",  # noqa: S608
                params,
            ).fetchall()
        page = [self._to_record(row) for row in rows]
        records = [row for row in page if row is not None]
        next_cursor = records[limit - 1].scan_id if len(records) > limit else None
        return records[:limit], next_cursor

    def confirm(
        self,
        tenant_id,
        scan_id,
        *,
        extraction,
        corrected_fields,
        document_hash,
        document_number_last4,
        confirmed_by,
        confirmed_at,
    ) -> ScanRecord | None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            current = conn.execute(
                "SELECT status FROM document_scans WHERE tenant_id = %s AND scan_id = %s FOR UPDATE",
                (tenant_id, scan_id),
            ).fetchone()
            if current is None:
                return None
            if current["status"] != "pending_review":
                raise ConfirmConflict(current["status"])
            row = conn.execute(
                "UPDATE document_scans SET status = 'confirmed', extraction = %s, corrected_fields = %s,"
                " document_hash = %s, document_number_last4 = %s, confirmed_by = %s, confirmed_at = %s,"
                " updated_at = %s WHERE tenant_id = %s AND scan_id = %s RETURNING *",
                (
                    Jsonb(extraction),
                    Jsonb(corrected_fields),
                    document_hash,
                    document_number_last4,
                    confirmed_by,
                    confirmed_at,
                    confirmed_at,
                    tenant_id,
                    scan_id,
                ),
            ).fetchone()
            conn.execute(
                "INSERT INTO document_scan_events (scan_id, tenant_id, event, actor, details)"
                " VALUES (%s, %s, 'confirmed', %s, %s)",
                (scan_id, tenant_id, confirmed_by, Jsonb({"corrected_fields": corrected_fields})),
            )
        return self._to_record(row)

    def ping(self) -> bool:
        try:
            with self._pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - readiness must never raise
            return False
