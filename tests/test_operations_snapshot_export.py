from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base  # noqa: E402
from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType  # noqa: E402
from tools.export_operations_hr_snapshot import (  # noqa: E402
    CONFIRMATION,
    EXPECTED_RUNTIME_FILE_COUNT,
    EXPECTED_RUNTIME_SHA256,
    SnapshotExportError,
    build_snapshot,
    export_snapshot,
    read_only_session,
    runtime_source_fingerprint,
    target_fingerprint,
)


@pytest.fixture()
def snapshot_engine(tmp_path: Path):
    database_path = tmp_path / "legacy-hr-restored.sqlite3"
    test_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        employee = Employee(
            full_name=" Snapshot Employee ",
            phone=" 6900000000 ",
            role_title=" Operator ",
            department=" Production ",
            location=" Central ",
            hire_date=date(2026, 1, 2),
            annual_leave_days=20,
            is_active=True,
        )
        leave_type = LeaveType(
            code="ANNUAL",
            name="Annual leave",
            counts_against_balance=True,
            color="#112233",
            is_active=True,
        )
        session.add_all([employee, leave_type])
        session.flush()
        session.add(
            LeaveRequest(
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                date_from=date(2026, 2, 2),
                date_to=date(2026, 2, 4),
                days_requested=3,
                note=" Approved request ",
                status="approved",
            )
        )
        session.add(
            LeaveBalance(
                employee_id=employee.id,
                year=2026,
                entitled_days=20,
                used_days=3,
                remaining_days=17,
            )
        )
        session.commit()
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def test_runtime_source_is_bound_to_accepted_characterization() -> None:
    file_count, digest = runtime_source_fingerprint()

    assert file_count == EXPECTED_RUNTIME_FILE_COUNT
    assert digest == EXPECTED_RUNTIME_SHA256


def test_snapshot_matches_operations_v1_contract_deterministically(
    snapshot_engine,
) -> None:
    with read_only_session(snapshot_engine) as session:
        first, first_risks = build_snapshot(session)
    with read_only_session(snapshot_engine) as session:
        second, second_risks = build_snapshot(session)

    assert first == second
    assert first_risks == second_risks == {
        "balance_arithmetic_mismatches": 0,
        "approved_usage_mismatches": 0,
    }
    assert list(first) == [
        "schema_version",
        "source_system",
        "employees",
        "leave_types",
        "leave_balances",
        "leave_requests",
    ]
    assert first["schema_version"] == 1
    assert first["source_system"] == "SKLAVOUNOS_HR"
    assert first["employees"] == [
        {
            "id": 1,
            "employee_number": None,
            "full_name": "Snapshot Employee",
            "phone": "6900000000",
            "role_title": "Operator",
            "department": "Production",
            "location": "Central",
            "hire_date": "2026-01-02",
            "annual_leave_days": 20,
            "is_active": True,
        }
    ]
    assert first["leave_requests"][0]["status"] == "approved"
    assert first["leave_requests"][0]["note"] == "Approved request"


def test_export_is_read_only_checksum_bound_and_no_clobber(
    snapshot_engine,
    tmp_path: Path,
) -> None:
    output = tmp_path / "hr-snapshot.json"
    evidence = tmp_path / "hr-snapshot.evidence.json"
    before = _row_counts(snapshot_engine)

    result = export_snapshot(
        snapshot_engine,
        output_path=output,
        evidence_path=evidence,
        expected_target_sha256=target_fingerprint(snapshot_engine.url),
        confirmation=CONFIRMATION,
        now=datetime(2026, 7, 28, 7, 0, tzinfo=UTC),
    )

    assert _row_counts(snapshot_engine) == before
    snapshot_bytes = output.read_bytes()
    assert result["decision"] == "PASS"
    assert result["transaction_mode"] == "SQLITE_QUERY_ONLY_ROLLBACK"
    assert result["snapshot_sha256"] == hashlib.sha256(snapshot_bytes).hexdigest()
    assert json.loads(evidence.read_text(encoding="utf-8")) == result
    with Session(snapshot_engine) as session:
        employee = session.scalar(select(Employee))
        assert employee is not None
        employee.role_title = "Writable after export"
        session.commit()
    with pytest.raises(SnapshotExportError, match="already exists"):
        export_snapshot(
            snapshot_engine,
            output_path=output,
            evidence_path=evidence,
            expected_target_sha256=target_fingerprint(snapshot_engine.url),
            confirmation=CONFIRMATION,
        )
    assert output.read_bytes() == snapshot_bytes


@pytest.mark.parametrize(
    ("target", "confirmation", "message"),
    [
        ("0" * 64, CONFIRMATION, "target fingerprint"),
        ("invalid", CONFIRMATION, "one SHA-256"),
        ("0" * 64, "EXPORT", "confirmation"),
    ],
)
def test_export_fails_closed_before_query_on_wrong_authority(
    snapshot_engine,
    tmp_path: Path,
    target: str,
    confirmation: str,
    message: str,
) -> None:
    output = tmp_path / f"{message}.json"
    evidence = tmp_path / f"{message}.evidence.json"

    with pytest.raises(SnapshotExportError, match=message):
        export_snapshot(
            snapshot_engine,
            output_path=output,
            evidence_path=evidence,
            expected_target_sha256=target,
            confirmation=confirmation,
        )

    assert not output.exists()
    assert not evidence.exists()


def test_private_output_is_rejected_inside_repository(snapshot_engine) -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(SnapshotExportError, match="outside the repository"):
        export_snapshot(
            snapshot_engine,
            output_path=repository_root / "forbidden-snapshot.json",
            evidence_path=repository_root / "forbidden-evidence.json",
            expected_target_sha256=target_fingerprint(snapshot_engine.url),
            confirmation=CONFIRMATION,
        )


def test_invalid_lifecycle_and_orphan_data_fail_closed(
    snapshot_engine,
) -> None:
    with Session(snapshot_engine) as session:
        request = session.scalar(select(LeaveRequest))
        assert request is not None
        request.status = "mystery"
        session.commit()
    with read_only_session(snapshot_engine) as session:
        with pytest.raises(SnapshotExportError, match="unsupported lifecycle"):
            build_snapshot(session)

    with Session(snapshot_engine) as session:
        request = session.scalar(select(LeaveRequest))
        assert request is not None
        request.status = "approved"
        request.employee_id = 999_999
        session.commit()
    with read_only_session(snapshot_engine) as session:
        with pytest.raises(SnapshotExportError, match="unknown employee"):
            build_snapshot(session)


def test_known_stale_balance_is_exported_exactly_and_flagged(
    snapshot_engine,
) -> None:
    with Session(snapshot_engine) as session:
        request = session.scalar(select(LeaveRequest))
        balance = session.scalar(select(LeaveBalance))
        assert request is not None
        assert balance is not None
        request.status = "cancelled"
        balance.used_days = 3
        balance.remaining_days = 17
        session.commit()

    with read_only_session(snapshot_engine) as session:
        snapshot, risk_counts = build_snapshot(session)

    assert snapshot["leave_balances"][0]["used_days"] == 3
    assert snapshot["leave_balances"][0]["remaining_days"] == 17
    assert risk_counts == {
        "balance_arithmetic_mismatches": 0,
        "approved_usage_mismatches": 1,
    }


def test_pending_reservation_requires_sufficient_matching_balance(
    snapshot_engine,
) -> None:
    with Session(snapshot_engine) as session:
        request = session.scalar(select(LeaveRequest))
        balance = session.scalar(select(LeaveBalance))
        assert request is not None
        assert balance is not None
        request.status = "pending"
        session.delete(balance)
        session.commit()
    with read_only_session(snapshot_engine) as session:
        with pytest.raises(SnapshotExportError, match="no matching annual balance"):
            build_snapshot(session)

    with Session(snapshot_engine) as session:
        request = session.scalar(select(LeaveRequest))
        assert request is not None
        session.add(
            LeaveBalance(
                employee_id=request.employee_id,
                year=request.date_from.year,
                entitled_days=20,
                used_days=19,
                remaining_days=1,
            )
        )
        session.commit()
    with read_only_session(snapshot_engine) as session:
        with pytest.raises(
            SnapshotExportError,
            match="exceed the stored remaining balance",
        ):
            build_snapshot(session)


def _row_counts(database_engine) -> dict[str, int]:
    with Session(database_engine) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model)
            )
            for model in (Employee, LeaveType, LeaveBalance, LeaveRequest)
        }
