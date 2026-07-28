# Operations HR snapshot export

Status date: 28 July 2026.

## Boundary

`tools/export_operations_hr_snapshot.py` produces the exact private `HrSnapshotV1` input
accepted by Sklavounos Operations. It reads an explicitly approved restored legacy-HR database;
it is not a live synchronization service and it never imports, changes or repairs business data.

The exporter fails closed unless all of these conditions hold:

- the Git-tracked 39-file legacy runtime still matches accepted SHA-256
  `6b23b2184f23cf0f4cc502c69d68c60b5f324b9effbc770a90752bf9978c23bd`;
- the configured database target matches an explicitly supplied, non-secret target
  fingerprint;
- the exact confirmation phrase is supplied;
- PostgreSQL can use a repeatable-read, read-only transaction, or the disposable SQLite test
  target can use query-only mode;
- every employee/type/request reference, lifecycle status, date range and day count is valid;
- the private snapshot and its evidence are new files outside the Git repository.

The snapshot contains names, phone numbers and leave notes. Keep it in the approved private
operations channel, never commit it, and delete it according to the approved migration retention
decision. Console output and evidence contain only counts, hashes, dialect and transaction mode.
They never contain database URLs, credentials, names, phone numbers or leave notes.

## Approved restored-target execution

Set `DATABASE_URL` only to the approved restored non-production HR database. First obtain its
non-secret fingerprint without connecting or reading rows:

```powershell
.\.venv\Scripts\python.exe -m tools.export_operations_hr_snapshot --inspect-target
```

Review and approve that fingerprint against the restored target. Then write the private files to
an existing secure directory outside this repository:

```powershell
.\.venv\Scripts\python.exe -m tools.export_operations_hr_snapshot `
  --output C:\secure\hr-snapshot.json `
  --evidence C:\secure\hr-snapshot.evidence.json `
  --expected-target-sha256 <approved-fingerprint> `
  --confirm "EXPORT RESTORED HR SNAPSHOT READ ONLY"
```

Both paths are no-clobber. A second run must use new paths. The evidence binds the snapshot
SHA-256, exact source runtime, target fingerprint, transaction mode, entity counts and two
privacy-safe risk counts:

- stored balance arithmetic mismatches;
- stored used-days mismatches against approved countable requests.

A non-zero risk count does not rewrite the snapshot. It keeps the exact legacy values and must
be reconciled with the business owner before Operations `--apply`.

## Operations import sequence

1. Validate the evidence and snapshot checksum.
2. Run the existing Operations `import-hr --snapshot ...` dry run.
3. Resolve every master-data warning/conflict and every exporter risk count.
4. Back up and restore-test the exact Operations staging database.
5. Apply only after explicit approval.
6. Run `reconcile-hr --snapshot ...`; one mismatch keeps the workflow open.

This checkpoint does not authorize live-HR access, Operations import, HR cutover or any production
deployment.
