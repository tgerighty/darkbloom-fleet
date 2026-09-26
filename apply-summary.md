# Cleanup apply summary — 2026-09-26

Base: `a3d3e98ec1c9398144f23d2b88de9e7f2d97b0e9` (`origin/main`). Scope: the supplied cleanup report only.

| Finding | Result | Test commit | Change commit |
|---|---|---|---|
| P1-1 old fresh snapshot | Recheck age with the configured freshness limit before health classification. | `81f2d31` | `00adfbc` |
| P1-2 duplicate payout | Use shared payout selection in the earnings profile; PostgreSQL check covers a null-hash copy. | `917be58` | `29f1982` |
| P2-3 HTTP bearer request | Reject a non-HTTPS URL before opening an authenticated request. | `e608b71` | `41ba3b2` |
| P2-5 payout backlog | Read at most 500 rows per SSH tick in row ID order. The stored maximum resumes the next tick. | `94d01e2` | `39826d1` |
| P2-6 malformed manager report | Treat non-object `pending_switch` values as absent. | `29d7618` | `fd0363a` |
| P2-8 database checks | Run the existing SQL and alert-delivery checks in a PostgreSQL-backed PR workflow. | Existing checks; null-hash case `917be58` | `ec9e3e9`, `625b62b` |

Skipped:

- P2-4: **YAGNI defer**. The report asks for production-sized `EXPLAIN ANALYZE` measurements before a retention or summary policy. No measured query budget is in the report.
- P2-7: **YAGNI defer**. Pinning an image digest and package versions needs a planned update cadence. The report found no CVE or version to select.
- P3 legacy schema: **defer** until the database retention review specified in the report.
- P3 HTML escape duplication: **defer** until the hourly module changes, as the report recommends.
- **NO-TEST-COVERAGE:** none of the applied items. Each has an existing or added covering check.

Verification:

- Baseline Python suite: 202 passed. Final Python suite: 208 passed.
- PostgreSQL: `tests/check_earnings_shadow.py` and `tests/check_watch_delivery.py` passed against a temporary local server.
- Vitest: 6 files, 65 tests passed.
- Ruff core checks (`E4,E7,E9,F`) and `compileall`: passed. The unrestricted Ruff run reports 13 existing findings; no project Ruff policy or type checker is configured.
- Sonar: PR analysis pending at summary creation. Check the exact tip SHA after opening the PR.
