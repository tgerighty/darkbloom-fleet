Ponytail: full intensity. Climb the YAGNI ladder; prefer reuse, stdlib, and native features; keep diffs minimal. Preserve trust-boundary validation, security, and accessibility.

# Dead Code Assessment

## Executive Summary

- Total findings: **4**. Severity: **HIGH=0, MEDIUM=0, LOW=4**. Two findings concern unused exports, one concerns an unused test parameter, and one concerns a schema object with no in-repo consumer (`fleet/static/host.js:103`, `tests/dashboard-harness.js:3`, `tests/test_queries.py:134`, `fleet/db.py:40`).
- Priorities: review the `switch_lease` table before changing schema initialization; remove the unused `decisions` test-helper parameter; remove two unused `export` keywords if the module interfaces are owned only by this repo (`fleet/db.py:40`, `tests/test_queries.py:134`, `fleet/static/host.js:103`, `tests/dashboard-harness.js:3`).
- Potential whole-line reduction: **CERTAIN 0 LOC; LIKELY 5 LOC; UNCERTAIN 0 LOC**. The 5 likely lines are the `switch_lease` creation statement; the other findings need only token edits (`fleet/db.py:40`, `fleet/db.py:44`, `tests/test_queries.py:134`, `fleet/static/host.js:103`, `tests/dashboard-harness.js:3`). Four files contain the findings (`fleet/db.py:40`, `tests/test_queries.py:134`, `fleet/static/host.js:103`, `tests/dashboard-harness.js:3`).
- Install-size reduction supported by this review: **0**. The Python runtime dependencies are declared in `requirements.txt:1`, `requirements.txt:2`, and `requirements.txt:3` and used by the app at `fleet/web.py:14`, `fleet/main.py:10`, and `fleet/db.py:10`. Vitest is imported by `tests/dashboard-view.test.js:2`; the coverage adapter is configured through `vitest.config.js:4` and `vitest.config.js:5`, so a missing direct import does not show that it is unused (`package.json:5`, `package.json:6`).
- No unused whole file or type was substantiated by the cross-check: the service starts through its module entry point, and the shared dataclasses feed ingestion and persistence (`Dockerfile:22`, `fleet/main.py:32`, `fleet/types.py:11`, `fleet/remote.py:10`, `fleet/db.py:14`).

The repo has a Python service entry point (`Dockerfile:22`) and browser ES modules (`fleet/static/dashboard.html:151`). The requested `vulture`, `ruff`, `autoflake`, and `pip-extra-reqs` tools, and a local Knip installation, were unavailable. I used read-only Python AST scans and exact reference searches for candidate discovery. I checked runtime entry points, route decorators, static module imports, tests, deployment configuration, and history before classifying candidates (`fleet/main.py:32`, `fleet/web.py:61`, `fleet/web.py:67`, `fleet/static/dashboard.js:1`, `fleet/static/dashboard.html:151`, `deploy/stack.yml:75`). All JSON findings remain unverified for downstream application.

## Critical Findings

None.

## Medium Findings

None.

## Low / Debatable Findings

### dead-001 — Unused `switch_lease` schema creation — LIKELY

`SCHEMA_SQL` still creates `switch_lease` and its three columns on startup (`fleet/db.py:40`, `fleet/db.py:44`, `fleet/db.py:142`, `fleet/main.py:21`). Exact references in this worktree found no query, insert, update, or delete for the table outside that creation statement (`fleet/db.py:40`). The service now describes itself as read-only monitoring with fleet switch controls removed (`README.md:3`, `README.md:13`). The creation statement is 5 lines, but an external SQL client or retained lease data is not visible from this worktree. Review live database consumers before omitting this creation statement; do not infer that an existing table can be dropped (`fleet/db.py:40`, `README.md:13`). `git blame` attributes this line to commit `fdeeb026` on 2026-09-14 (`fleet/db.py:40`).

### dead-002 — Unused `decisions` parameter in a test helper — CERTAIN

`_status_responses` accepts `decisions`, but its return list does not use that parameter (`tests/test_queries.py:134`, `tests/test_queries.py:139`, `tests/test_queries.py:144`). Three calls still pass a decisions argument (`tests/test_queries.py:153`, `tests/test_queries.py:227`, `tests/test_queries.py:257`), and its docstring still names decisions as a returned result (`tests/test_queries.py:135`, `tests/test_queries.py:137`). Remove the parameter, those three arguments, and the stale docstring reference. Keep tests that deliberately pass `recent_decisions` to prove the old panel stays absent (`tests/dashboard-view.test.js:45`, `tests/dashboard-view.test.js:103`). `git blame` shows the helper predates the 2026-09-16 switch-control removal (`tests/test_queries.py:134`, `README.md:13`).

### dead-003 — `chip` is exported only for in-module use — LIKELY

`chip` is exported from the served `host.js` module, while its only in-repo call is in `hostCard` (`fleet/static/host.js:103`, `fleet/static/host.js:269`). The dashboard imports `esc` and `renderHosts` from this module, and the JavaScript tests import other named exports, not `chip` (`fleet/static/dashboard.js:2`, `tests/dashboard-view.test.js:4`, `tests/dashboard-host-edges.test.js:3`). If no outside script imports `/static/host.js`, remove only the `export` keyword; keep the function and HTML escaping (`fleet/static/dashboard.html:151`, `fleet/static/host.js:103`, `fleet/static/host.js:109`). `git blame` dates this export to 2026-09-13 (`fleet/static/host.js:103`).

### dead-004 — `nowSec` is exported only for test-helper use — CERTAIN

`nowSec` is exported from the test harness, but this worktree uses it only in that file's `host` fixture (`tests/dashboard-harness.js:3`, `tests/dashboard-harness.js:7`, `tests/dashboard-harness.js:13`). The test that imports harness helpers imports `host` and other helpers, not `nowSec` (`tests/dashboard-poll.test.js:3`, `tests/dashboard-poll.test.js:5`). Remove only the `export` keyword; keep the clock helper because the fixture uses it (`tests/dashboard-harness.js:3`, `tests/dashboard-harness.js:13`). `git blame` dates this export to 2026-09-13 (`tests/dashboard-harness.js:3`).

## Recommendations

1. Check external SQL consumers and retained lease data, then decide whether to omit the five-line `switch_lease` creation statement from schema initialization (`fleet/db.py:40`, `fleet/db.py:44`, `fleet/db.py:142`). This is a review step, not an instruction to drop a live table.
2. Remove the unused test-helper parameter and adjust its three calls and docstring (`tests/test_queries.py:134`, `tests/test_queries.py:137`, `tests/test_queries.py:153`, `tests/test_queries.py:227`, `tests/test_queries.py:257`).
3. If this repo owns the complete JavaScript module interface, remove only the unused export modifiers (`fleet/static/host.js:103`, `tests/dashboard-harness.js:3`). The functions still have local callers (`fleet/static/host.js:269`, `tests/dashboard-harness.js:13`).

## Out of Scope / Flagged for Review

- The `decisions` table has no in-repo active consumer, but project documentation explicitly says to retain historical decisions (`fleet/db.py:119`, `README.md:13`, `CONFIG.md:122`). Do not classify it as safe to remove.
- `fan_rpm` and `peak_temperature_c` have no dashboard rendering path, but they are read from the widget and persisted as history, which the documentation says is queryable (`fleet/remote.py:92`, `fleet/remote.py:93`, `fleet/db.py:184`, `fleet/db.py:193`, `CONFIG.md:89`, `CONFIG.md:103`). Likewise, `mtp_enabled` is stored with slot data even though the current renderer displays `mtp_active` (`fleet/remote.py:232`, `fleet/db.py:197`, `fleet/static/host.js:165`, `CONFIG.md:96`). These are data-retention decisions, not confirmed dead code.
- The status API emits top-level `mode` and `daemon_fresh`; browser code does not use these fields, but tests assert them and external API clients were not inventoried (`fleet/queries.py:384`, `fleet/queries.py:386`, `tests/test_queries.py:158`, `tests/test_queries.py:159`, `fleet/web.py:67`). No removal recommendation follows from this review.
- The manual check scripts have executable entry points or documented invocations, so test discovery alone does not establish that they are unused (`tests/check_reward_accounting.py:1`, `tests/check_watch_delivery.py:1`, `tests/check_earnings_shadow.py:1`).

## Machine-Readable Findings

```json
{"findings": [
  {"id": "dead-001", "file": "fleet/db.py", "line": 40, "severity": "LOW", "confidence": "LIKELY", "recommendation": "REVIEW", "detail": "switch_lease is created at startup but has no in-repo SQL consumer; check external clients before omitting the creation statement.", "verified": false},
  {"id": "dead-002", "file": "tests/test_queries.py", "line": 134, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "REMOVE", "detail": "The decisions parameter is never read by _status_responses; remove it, three call arguments, and the stale docstring reference.", "verified": false},
  {"id": "dead-003", "file": "fleet/static/host.js", "line": 103, "severity": "LOW", "confidence": "LIKELY", "recommendation": "REVIEW", "detail": "chip has an in-module caller but no in-repo import; remove only its export modifier after checking external module consumers.", "verified": false},
  {"id": "dead-004", "file": "tests/dashboard-harness.js", "line": 3, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "REMOVE_EXPORT", "detail": "nowSec is called by the local host fixture but never imported from the test harness; remove only its export modifier.", "verified": false}
]}
```
