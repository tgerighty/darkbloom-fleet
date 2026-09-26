Ponytail: FULL INTENSITY — YAGNI ladder; reuse, standard library, and native features first; minimal diffs; keep trust-boundary validation, security, and accessibility.

# Deduplication Assessment

## Executive Summary

- Total duplicate groups reviewed: **8**. Three are consolidation candidates. Five should stay separate. Severity: **HIGH=1, MEDIUM=1, LOW=6**. The high rating follows the skill's exact-copy rule; it does not mean an active incident. Evidence: `fleet/static/dashboard.js:16`, `fleet/static/host.js:24`, `fleet/earnings_shadow.py:37`, `fleet/attribution.py:46`, `fleet/static/hourly.js:15`, `fleet/static/ui.js:8`.
- Priorities: (1) use the existing payout deduplication SQL in the earnings profile, (2) share the exact age formatter, (3) reuse the existing HTML escape helper in the hourly panel. Evidence: `fleet/earnings_shadow.py:42`, `fleet/attribution.py:46`, `fleet/static/dashboard.js:16`, `fleet/static/host.js:24`, `fleet/static/hourly.js:15`, `fleet/static/ui.js:8`.
- Estimated impact if all three candidates are applied: about 10 source lines removed across five production files. This is an estimate from the cited blocks, not a measured diff. Evidence: `fleet/earnings_shadow.py:37`, `fleet/static/dashboard.js:16`, `fleet/static/host.js:24`, `fleet/static/hourly.js:15`, `fleet/static/ui.js:8`.
- Scope and method: Python service and browser JavaScript, plus their tests. I used read-only searches and a local exact-line scan. Pylint and jscpd were unavailable, so this is a manual assessment, not an automated clone-tool result. Ecosystem evidence: `pyproject.toml:1`, `package.json:1`, `fleet/static/dashboard.js:1`, `tests/dashboard-view.test.js:1`.

## Critical Findings

### dedup-001 — exact age formatter copy — HIGH — CONSOLIDATE

The seven-line `fmtAge(epoch)` body is identical in `fleet/static/dashboard.js:16` and `fleet/static/host.js:24`. Both modules call it for human-readable event ages at `fleet/static/dashboard.js:36` and `fleet/static/host.js:62`. Move the function to the already shared `fleet/static/ui.js:8` and export `fmtAge(epoch)`. Import it in both callers and remove both local copies. This is a small source reduction and gives the two screens one threshold policy. Preserve the current `"never"`, 90-second, and 5400-second behavior shown at `fleet/static/dashboard.js:17` and `fleet/static/host.js:25`. Risk: low, but verify the dashboard's stale subtitle and host age display after the import; those are distinct call sites at `fleet/static/dashboard.js:36` and `fleet/static/host.js:62`.

## Medium Findings

### dedup-002 — payout row selection has two implementations — MEDIUM — CONSOLIDATE

The earnings profile selects one ledger copy with `DISTINCT ON (payout_rowid)` and `ORDER BY payout_rowid` at `fleet/earnings_shadow.py:41`. The existing shared helper selects the same row identity, but prefers a populated provider hash and then orders by host at `fleet/attribution.py:46`. Other payout summaries already use that helper at `fleet/queries.py:215`, `fleet/card.py:98`, and `fleet/hourly.py:23`. Reuse `unique_payouts_sql(columns: str, where: str) -> str` in the `payouts` CTE in `fleet/earnings_shadow.py:37`; retain its time window and `base_reward` filter at `fleet/earnings_shadow.py:43`. This removes a separate policy for picking replicated rows. If two copies have different hash completeness, the current profile can choose either one; the shared helper prefers the populated hash. This is a conditional risk, not an observed wrong total. The regression fixture uses the same hash in both copies at `tests/check_earnings_shadow.py:17`. Risk: medium because attribution affects money totals; check a mixed-hash fixture before any later implementation. Evidence for the existing join: `fleet/earnings_shadow.py:38`, `fleet/earnings_shadow.py:47`.

## Low / Debatable Findings

### dedup-003 — hourly HTML escape helper — LOW — CONSOLIDATE

`fleet/static/hourly.js:15` has a local three-character text escape function. `fleet/static/ui.js:7` already exports `esc(v)`, which escapes those characters and more. The hourly helper is used for model text at `fleet/static/hourly.js:39`. Replace the local helper with an import from `ui.js`; keep the model text escaped. This is a small reduction and maintains one HTML escaping rule. Risk: low; confirm the rendered legend after the import. The wider escape set can change HTML entity spelling for quotes and backticks, but the characters still display as text. Evidence: `fleet/static/hourly.js:16`, `fleet/static/ui.js:9`.

### dedup-004 — numeric format one-liner — LOW — KEEP SEPARATE

The `num(v, digits)` one-liner is identical at `fleet/static/ui.js:11` and `fleet/static/host.js:41`. It is local to each rendering module, with uses at `fleet/static/ui.js:42` and `fleet/static/host.js:82`. Exporting and importing it would trade one repeated line for more cross-module wiring. Keep the one-liners unless formatting behavior changes. Do not combine this with the age formatter solely to justify a broader formatting API. Evidence: `fleet/static/ui.js:11`, `fleet/static/host.js:41`.

### dedup-005 — three background loop shells — LOW — KEEP SEPARATE

The ingestion, watchdog, and earnings loops each run work in a thread, log exceptions, and wait for a stop event at `fleet/scheduler.py:20`, `fleet/watch.py:136`, and `fleet/earnings_shadow.py:94`. Their cadence and activation rules differ: elapsed-time adjustment in `fleet/scheduler.py:24`, watchdog URL and minimum delay in `fleet/watch.py:137`, and earnings feature gate and fixed wait in `fleet/earnings_shadow.py:95`. A generic loop abstraction would need options or callbacks for those differences. Keep the separate loops.

### dedup-006 — similar host fixtures — LOW — KEEP SEPARATE

Two UI test files define `host(over = {})` with the same opening fields at `tests/dashboard-host-edges.test.js:7` and `tests/dashboard-view.test.js:7`. Their default time, demand, serving, card, and slot values differ at `tests/dashboard-host-edges.test.js:13` and `tests/dashboard-view.test.js:13`. Keep each test's explicit local fixture. A shared fixture would hide which defaults each suite needs. A separate shared harness already exists for poll tests at `tests/dashboard-harness.js:7`.

### dedup-007 — finite-number validation looks similar — LOW — KEEP SEPARATE

`fleet/remote.py:197` and `fleet/scoring.py:16` parse external numeric values, including numeric strings. `fleet/queries.py:41` accepts only numeric Python values and rejects booleans. These are different trust-boundary contracts. A single generic parser could silently widen the manager display inputs or narrow remote payload acceptance. Keep each local contract. Evidence: `fleet/remote.py:200`, `fleet/scoring.py:19`, `fleet/queries.py:42`.

### dedup-008 — similar card test stubs — LOW — KEEP SEPARATE

The test harness card stub and a direct UI test stub repeat three `querySelectorAll` lines at `tests/dashboard-harness.js:43` and `tests/dashboard-refresh.test.js:25`. The harness also models `querySelector`, host membership, and Vitest behavior at `tests/dashboard-harness.js:41`; the direct unit test needs only a small object at `tests/dashboard-refresh.test.js:22`. Keep the local stub. Importing the larger harness into the direct test would add coupling for no meaningful code reduction.

## Recommendations

1. First, reuse `unique_payouts_sql` in the earnings profile and add a later regression case in which replicated rows differ in provider-hash completeness. This keeps the existing payout selection policy and protects attributed totals. Evidence: `fleet/attribution.py:46`, `fleet/earnings_shadow.py:41`, `tests/check_earnings_shadow.py:17`.
2. Next, export `fmtAge(epoch)` from the shared UI module and use it in both callers. Keep the current labels and thresholds. Evidence: `fleet/static/ui.js:8`, `fleet/static/dashboard.js:16`, `fleet/static/host.js:24`.
3. Then, import the existing `esc(v)` into the hourly module. Keep HTML text escaping in the hourly legend. Evidence: `fleet/static/ui.js:8`, `fleet/static/hourly.js:15`, `fleet/static/hourly.js:39`.
4. Leave the one-line number formatters, background loops, and local test stubs in place. Their current differences or small size make an abstraction cost more than it saves. Evidence: `fleet/static/ui.js:11`, `fleet/static/host.js:41`, `fleet/scheduler.py:20`, `fleet/watch.py:136`, `tests/dashboard-refresh.test.js:22`.

## Out of Scope / Flagged for Review

- The scoring formula and public-feed call pattern refer to another project at `fleet/scoring.py:1` and `fleet/demand.py:1`. This assessment stays within this worktree and does not judge cross-repository duplication.
- The serving-time rules appear in a Python window calculation and a SQL lifetime aggregate at `fleet/queries.py:288` and `fleet/queries.py:258`. They process different ranges and formats, so a shared source would need SQL generation or a larger data read. Keep them separate pending a measured need to change both.
- No product code, tests, dependencies, or configuration were changed. The assessment covers the source and tests named above. Evidence of the relevant source and test locations: `fleet/static/dashboard.js:1`, `fleet/earnings_shadow.py:1`, `tests/dashboard-view.test.js:1`.

## Machine-Readable Findings

```json
{"findings": [
  {"id": "dedup-001", "file": "fleet/static/dashboard.js", "line": 16, "severity": "HIGH", "confidence": "CERTAIN", "recommendation": "CONSOLIDATE", "detail": "Exact fmtAge copy at fleet/static/dashboard.js:16 and fleet/static/host.js:24; export fmtAge(epoch) from fleet/static/ui.js:8.", "verified": false},
  {"id": "dedup-002", "file": "fleet/earnings_shadow.py", "line": 42, "severity": "MEDIUM", "confidence": "CERTAIN", "recommendation": "CONSOLIDATE", "detail": "Payout CTE at fleet/earnings_shadow.py:42 repeats unique payout selection with a different order than fleet/attribution.py:46; reuse unique_payouts_sql(columns, where).", "verified": false},
  {"id": "dedup-003", "file": "fleet/static/hourly.js", "line": 15, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "CONSOLIDATE", "detail": "Local text esc at fleet/static/hourly.js:15 overlaps existing exported esc at fleet/static/ui.js:8; import the existing helper.", "verified": false},
  {"id": "dedup-004", "file": "fleet/static/host.js", "line": 41, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "KEEP SEPARATE", "detail": "One-line num copy at fleet/static/host.js:41 and fleet/static/ui.js:11 is cheaper to keep than to wire across modules.", "verified": false},
  {"id": "dedup-005", "file": "fleet/scheduler.py", "line": 20, "severity": "LOW", "confidence": "LIKELY", "recommendation": "KEEP SEPARATE", "detail": "Loop shells at fleet/scheduler.py:20, fleet/watch.py:136, and fleet/earnings_shadow.py:94 have different timing and activation rules.", "verified": false},
  {"id": "dedup-006", "file": "tests/dashboard-host-edges.test.js", "line": 7, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "KEEP SEPARATE", "detail": "Host fixtures at tests/dashboard-host-edges.test.js:7 and tests/dashboard-view.test.js:7 share a shape but have distinct defaults.", "verified": false},
  {"id": "dedup-007", "file": "fleet/remote.py", "line": 197, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "KEEP SEPARATE", "detail": "Numeric parsers at fleet/remote.py:197, fleet/scoring.py:16, and fleet/queries.py:41 enforce different input contracts.", "verified": false},
  {"id": "dedup-008", "file": "tests/dashboard-harness.js", "line": 43, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "KEEP SEPARATE", "detail": "Card stubs at tests/dashboard-harness.js:43 and tests/dashboard-refresh.test.js:25 share selectors but serve different test scopes.", "verified": false}
]}
```
