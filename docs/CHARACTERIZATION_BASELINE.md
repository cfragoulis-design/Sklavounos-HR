# Sklavounos HR Characterization Baseline

Status date: 28 July 2026.

## Boundary

This checkpoint freezes the current legacy HR behavior from exact `main` commit
`530d5673945a76fbed6db69a7b01c037766d72b3`. It adds tests, test dependencies, ignore rules and
test-only GitHub CI on `codex/hr-characterization`. It does not change application source,
database schema, Railway configuration, environment variables, credentials, business data or
the live HR deployment.

The exact legacy runtime surface contains 39 Git-tracked files under `app/` plus
`requirements.txt`, `Procfile` and `railway.json`. Its deterministic, line-ending-independent
path/content SHA-256 is
`6b23b2184f23cf0f4cc502c69d68c60b5f324b9effbc770a90752bf9978c23bd`.

## Captured behavior

- 34 exact runtime method/path pairs, including framework documentation endpoints.
- Exact file-set and content fingerprint for the full legacy runtime surface.
- Public health and session-status reads.
- Existing administrator login/logout and protected page boundary.
- Employee creation and immutable audit entry.
- Leave creation, approval, cancellation, annual balance recalculation and audit sequence.
- Existing Sunday and fixed Greek-holiday day-counting behavior, including the currently
  inverted fixed-holiday comparison.
- Existing validation for negative annual entitlement and reversed leave dates.

All database behavior runs only on a disposable SQLite file under ignored `test-results/`.

## Findings that remain unchanged

The characterization deliberately records, but does not approve or fix, the following legacy
risks:

1. `/debug/seed-sample` is an unauthenticated database mutation.
2. startup calls `create_all`, performs an inline `ALTER TABLE`, and seeds defaults without a
   reviewed migration boundary;
3. source defaults exist for the session secret and administrator credentials, and the session
   cookie is configured with `https_only=False`;
4. state-changing form routes have no explicit CSRF token;
5. leave transitions are administrator-only but have no optimistic version, idempotency key,
   overlap guard, reserved-balance rule or transition-state guard;
6. dependencies are unpinned in the production requirements file;
7. `app/routers/exports.py` and `app/routers/employee_leave.py` exist but are not included in the
   runtime application.
8. cancelling an approved request commits `cancelled` and audit history but leaves the persisted
   balance at its pre-cancellation used/remaining values;
9. fixed holidays are declared as `DD-MM` while the calculator compares `MM-DD`, so dates such as
   25 March are currently counted as leave days.

These are migration/hardening inputs. No production fix should be bundled with this baseline.

## Verification

The branch gate installs the exact compatibility versions in `requirements-dev.txt`, runs Ruff
only on the new tests, verifies the dependency graph and runs the complete characterization suite
on Python 3.11. The production `requirements.txt` remains unchanged and its lack of pins remains
an explicit finding. CI has read-only repository permissions and no deployment step or production
secret.
