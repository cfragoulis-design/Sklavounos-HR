from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Engine, Select, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType

SOURCE_SYSTEM = "SKLAVOUNOS_HR"
SCHEMA_VERSION = 1
EVIDENCE_VERSION = 1
EXPECTED_RUNTIME_FILE_COUNT = 39
EXPECTED_RUNTIME_SHA256 = (
    "6b23b2184f23cf0f4cc502c69d68c60b5f324b9effbc770a90752bf9978c23bd"
)
CONFIRMATION = "EXPORT RESTORED HR SNAPSHOT READ ONLY"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TEXT_RUNTIME_SUFFIXES = {".css", ".html", ".js", ".json", ".py", ".txt"}
ALLOWED_REQUEST_STATUSES = {"pending", "approved", "rejected", "cancelled"}


class SnapshotExportError(RuntimeError):
    """Raised before an unsafe or ambiguous snapshot can be produced."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_source_fingerprint(repository_root: Path | None = None) -> tuple[int, str]:
    root = (repository_root or _repository_root()).resolve()
    try:
        tracked_files = sorted(
            subprocess.check_output(
                [
                    "git",
                    "ls-files",
                    "--",
                    "app",
                    "requirements.txt",
                    "Procfile",
                    "railway.json",
                ],
                cwd=root,
                text=True,
            ).splitlines()
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotExportError(
            "The exact Git-tracked legacy runtime cannot be verified"
        ) from exc

    digest = hashlib.sha256()
    for relative_path in tracked_files:
        path = root / relative_path
        if not path.is_file():
            raise SnapshotExportError(
                "A Git-tracked legacy runtime file is missing"
            )
        content = path.read_bytes()
        if path.suffix in TEXT_RUNTIME_SUFFIXES or path.name == "Procfile":
            content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(relative_path.replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return len(tracked_files), digest.hexdigest()


def target_fingerprint(database_url: URL) -> str:
    backend = database_url.get_backend_name().strip().lower()
    if backend == "sqlite":
        database = database_url.database
        if not database or database == ":memory:":
            target = f"{backend}|:memory:"
        else:
            target = f"{backend}|{Path(database).resolve()}"
    else:
        host = (database_url.host or "").strip().lower()
        port = database_url.port or 0
        database = (database_url.database or "").strip()
        target = f"{backend}|{host}|{port}|{database}"
    return hashlib.sha256(target.encode()).hexdigest()


def _validate_source() -> str:
    file_count, source_sha256 = runtime_source_fingerprint()
    if (
        file_count != EXPECTED_RUNTIME_FILE_COUNT
        or source_sha256 != EXPECTED_RUNTIME_SHA256
    ):
        raise SnapshotExportError(
            "Legacy HR runtime fingerprint does not match the accepted baseline"
        )
    return source_sha256


def _normalized_optional(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _ordered(session: Session, statement: Select[Any]) -> list[Any]:
    return list(session.scalars(statement).all())


def build_snapshot(session: Session) -> tuple[dict[str, Any], dict[str, int]]:
    employees = _ordered(session, select(Employee).order_by(Employee.id))
    leave_types = _ordered(session, select(LeaveType).order_by(LeaveType.id))
    leave_balances = _ordered(
        session,
        select(LeaveBalance).order_by(LeaveBalance.id),
    )
    leave_requests = _ordered(
        session,
        select(LeaveRequest).order_by(LeaveRequest.id),
    )

    employee_ids = {employee.id for employee in employees}
    leave_type_ids = {leave_type.id for leave_type in leave_types}
    balance_keys = {
        (balance.employee_id, balance.year): balance
        for balance in leave_balances
    }
    for employee in employees:
        if not employee.full_name.strip():
            raise SnapshotExportError("An employee has an empty full name")
        if employee.annual_leave_days < 0:
            raise SnapshotExportError(
                "An employee has a negative annual leave entitlement"
            )
    for leave_type in leave_types:
        if not leave_type.code.strip() or not leave_type.name.strip():
            raise SnapshotExportError("A leave type has an empty code or name")
    for balance in leave_balances:
        if balance.employee_id not in employee_ids:
            raise SnapshotExportError(
                "A leave balance references an unknown employee"
            )
        if not 2000 <= balance.year <= 2100:
            raise SnapshotExportError(
                "A leave balance uses a year unsupported by Operations"
            )
        if (
            balance.entitled_days < 0
            or balance.used_days < 0
            or balance.remaining_days < 0
        ):
            raise SnapshotExportError(
                "A leave balance has a negative component unsupported by Operations"
            )
    for request in leave_requests:
        status = request.status.strip().lower()
        if request.employee_id not in employee_ids:
            raise SnapshotExportError(
                "A leave request references an unknown employee"
            )
        if request.leave_type_id not in leave_type_ids:
            raise SnapshotExportError(
                "A leave request references an unknown leave type"
            )
        if request.date_to < request.date_from:
            raise SnapshotExportError("A leave request has a reversed date range")
        if request.days_requested <= 0:
            raise SnapshotExportError(
                "A leave request has a non-positive day count"
            )
        if status not in ALLOWED_REQUEST_STATUSES:
            raise SnapshotExportError(
                "A leave request has an unsupported lifecycle status"
            )

    countable_types = {
        leave_type.id
        for leave_type in leave_types
        if leave_type.counts_against_balance
    }
    pending_usage: Counter[tuple[int, int]] = Counter()
    for request in leave_requests:
        if (
            request.status.strip().lower() == "pending"
            and request.leave_type_id in countable_types
        ):
            pending_usage[(request.employee_id, request.date_from.year)] += (
                request.days_requested
            )
    for key, reserved_days in pending_usage.items():
        balance = balance_keys.get(key)
        if balance is None:
            raise SnapshotExportError(
                "A pending countable request has no matching annual balance"
            )
        if reserved_days > balance.remaining_days:
            raise SnapshotExportError(
                "Pending countable requests exceed the stored remaining balance"
            )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source_system": SOURCE_SYSTEM,
        "employees": [
            {
                "id": employee.id,
                "employee_number": None,
                "full_name": employee.full_name.strip(),
                "phone": _normalized_optional(employee.phone),
                "role_title": _normalized_optional(employee.role_title),
                "department": _normalized_optional(employee.department),
                "location": _normalized_optional(employee.location),
                "hire_date": (
                    employee.hire_date.isoformat() if employee.hire_date else None
                ),
                "annual_leave_days": employee.annual_leave_days,
                "is_active": employee.is_active,
            }
            for employee in employees
        ],
        "leave_types": [
            {
                "id": leave_type.id,
                "code": leave_type.code.strip(),
                "name": leave_type.name.strip(),
                "counts_against_balance": leave_type.counts_against_balance,
                "color": _normalized_optional(leave_type.color),
                "is_active": leave_type.is_active,
            }
            for leave_type in leave_types
        ],
        "leave_balances": [
            {
                "id": balance.id,
                "employee_id": balance.employee_id,
                "year": balance.year,
                "entitled_days": balance.entitled_days,
                "used_days": balance.used_days,
                "remaining_days": balance.remaining_days,
            }
            for balance in leave_balances
        ],
        "leave_requests": [
            {
                "id": request.id,
                "employee_id": request.employee_id,
                "leave_type_id": request.leave_type_id,
                "date_from": request.date_from.isoformat(),
                "date_to": request.date_to.isoformat(),
                "days_requested": request.days_requested,
                "note": _normalized_optional(request.note),
                "status": request.status.strip().lower(),
                "decision_note": _normalized_optional(request.decision_note),
            }
            for request in leave_requests
        ],
    }

    approved_usage: Counter[tuple[int, int]] = Counter()
    for request in leave_requests:
        if (
            request.status.strip().lower() == "approved"
            and request.leave_type_id in countable_types
        ):
            approved_usage[(request.employee_id, request.date_from.year)] += (
                request.days_requested
            )
    arithmetic_mismatches = sum(
        balance.remaining_days
        != balance.entitled_days - balance.used_days
        for balance in leave_balances
    )
    approved_usage_mismatches = sum(
        balance.used_days
        != approved_usage.get((balance.employee_id, balance.year), 0)
        for balance in leave_balances
    )
    risk_counts = {
        "balance_arithmetic_mismatches": arithmetic_mismatches,
        "approved_usage_mismatches": approved_usage_mismatches,
    }
    return snapshot, risk_counts


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


@contextmanager
def read_only_session(database_engine: Engine) -> Iterator[Session]:
    with database_engine.connect() as connection:
        transaction = connection.begin()
        dialect = connection.dialect.name
        if dialect == "postgresql":
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
        elif dialect == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only = ON")
        else:
            transaction.rollback()
            raise SnapshotExportError(
                "Only PostgreSQL and SQLite read-only exports are supported"
            )
        session = Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield session
            if session.new or session.dirty or session.deleted:
                raise SnapshotExportError(
                    "The export session unexpectedly contains pending writes"
                )
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()
            if dialect == "sqlite":
                connection.exec_driver_sql("PRAGMA query_only = OFF")
                connection.rollback()


def _outside_repository(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(_repository_root()):
        raise SnapshotExportError(
            "Private HR snapshots and evidence must be written outside the repository"
        )
    if not resolved.parent.is_dir():
        raise SnapshotExportError("The output directory does not exist")
    return resolved


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def export_snapshot(
    database_engine: Engine,
    *,
    output_path: Path,
    evidence_path: Path,
    expected_target_sha256: str,
    confirmation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise SnapshotExportError("The exact read-only confirmation is required")
    normalized_target = expected_target_sha256.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized_target):
        raise SnapshotExportError("Expected target fingerprint must be one SHA-256")
    actual_target = target_fingerprint(database_engine.url)
    if not hmac.compare_digest(normalized_target, actual_target):
        raise SnapshotExportError(
            "Database target fingerprint does not match the approved restored target"
        )

    output = _outside_repository(output_path)
    evidence = _outside_repository(evidence_path)
    if output == evidence:
        raise SnapshotExportError("Snapshot and evidence paths must be distinct")
    if output.exists() or evidence.exists():
        raise SnapshotExportError("Snapshot or evidence target already exists")

    source_sha256 = _validate_source()
    with read_only_session(database_engine) as session:
        snapshot, risk_counts = build_snapshot(session)
    snapshot_bytes = _json_bytes(snapshot)
    snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
    evidence_payload = {
        "evidence_version": EVIDENCE_VERSION,
        "decision": "PASS",
        "generated_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "source_system": SOURCE_SYSTEM,
        "source_runtime_file_count": EXPECTED_RUNTIME_FILE_COUNT,
        "source_runtime_sha256": source_sha256,
        "database_dialect": database_engine.url.get_backend_name(),
        "target_fingerprint_sha256": actual_target,
        "transaction_mode": (
            "REPEATABLE_READ_READ_ONLY"
            if database_engine.url.get_backend_name() == "postgresql"
            else "SQLITE_QUERY_ONLY_ROLLBACK"
        ),
        "snapshot_schema_version": SCHEMA_VERSION,
        "snapshot_sha256": snapshot_sha256,
        "snapshot_counts": {
            "employees": len(snapshot["employees"]),
            "leave_types": len(snapshot["leave_types"]),
            "leave_balances": len(snapshot["leave_balances"]),
            "leave_requests": len(snapshot["leave_requests"]),
        },
        "risk_counts": risk_counts,
    }

    _write_exclusive(output, snapshot_bytes)
    try:
        _write_exclusive(evidence, _json_bytes(evidence_payload))
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return evidence_payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the exact legacy HR snapshot contract from an approved restored "
            "database through a read-only transaction."
        )
    )
    parser.add_argument(
        "--inspect-target",
        action="store_true",
        help="Print only the non-secret target fingerprint; performs no database query.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--expected-target-sha256")
    parser.add_argument("--confirm")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.inspect_target:
        if any(
            value is not None
            for value in (
                args.output,
                args.evidence,
                args.expected_target_sha256,
                args.confirm,
            )
        ):
            raise SnapshotExportError(
                "--inspect-target cannot be combined with export arguments"
            )
        print(
            json.dumps(
                {
                    "database_dialect": engine.url.get_backend_name(),
                    "target_fingerprint_sha256": target_fingerprint(engine.url),
                },
                sort_keys=True,
            )
        )
        return 0
    if (
        args.output is None
        or args.evidence is None
        or args.expected_target_sha256 is None
        or args.confirm is None
    ):
        raise SnapshotExportError(
            "Export requires output, evidence, expected target fingerprint and confirmation"
        )
    result = export_snapshot(
        engine,
        output_path=args.output,
        evidence_path=args.evidence,
        expected_target_sha256=args.expected_target_sha256,
        confirmation=args.confirm,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
