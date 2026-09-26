Ponytail: full intensity. Keep the smallest safe cleanup; verify stored data and external users before removal.

# Legacy Code Assessment

## Executive Summary

- Total findings: 5. Severity: HIGH=0, MEDIUM=2, LOW=3. The main candidates are the retained switch lease schema, the retained decision schema, and an unused switch cost wrapper (`fleet/db.py:40`, `fleet/db.py:119`, `fleet/routability.py:116`).
- Priority order: verify use of `switch_lease`; decide retention for historical `decisions`; then remove the unused wrapper if it has no external callers (`fleet/db.py:40`, `README.md:13`, `fleet/routability.py:116`).
- Potential reduction: 29 source lines in two Python files if all three code candidates are approved: 5 schema lines for `switch_lease`, 16 schema lines for `decisions`, and 8 lines for `measured_switch_cost`. The decision schema is subject to a data retention decision (`fleet/db.py:40`, `fleet/db.py:119`, `fleet/routability.py:116`, `README.md:14`). Test and comment cleanup also touches `tests/test_queries.py:134`, `tests/dashboard-harness.js:17`, `fleet/db.py:1`, and `deploy/stack.yml:126`.
- Scope: Python service with a JavaScript dashboard (`fleet/web.py:19`, `fleet/web.py:59`). Python dependencies and the JavaScript test runner are declared in `requirements.txt:1` and `package.json:4`. This pass used read-only `rg`, `git`, and Python checks; `ruff` and `cloc` executables were not available. No source, dependency, or configuration file was changed.

## Critical Findings

None.

## Medium Findings

### LEGACY-001: Switch lease schema remains after fleet switching was removed

**Class:** NEEDS-VERIFICATION. **Evidence:** Startup still creates `switch_lease` (`fleet/db.py:40`), while the documented fleet switch engines and controls have been removed (`README.md:13`). The current tick collects snapshots, earnings, identities, and scores (`fleet/collector.py:121`, `fleet/collector.py:123`, `fleet/collector.py:124`, `fleet/collector.py:135`); no application SQL outside the schema stanza refers to `switch_lease` (`fleet/db.py:40`).

**Action:** Check direct database clients and live table use. If neither needs the table, stop creating it. Treat any later `DROP TABLE` as a separate data operation. **Reduction:** 5 schema lines (`fleet/db.py:40`).

### LEGACY-002: Historical decision table is still provisioned

**Class:** NEEDS-VERIFICATION. **Evidence:** Startup still creates and alters `decisions` (`fleet/db.py:119`, `fleet/db.py:132`). The README says no new shadow decisions are generated and existing decision history remains in Postgres (`README.md:13`, `README.md:14`). The current status response contains manager and health data without a decision query (`fleet/queries.py:374`, `fleet/queries.py:396`).

**Action:** Set a retention policy and check direct database readers before removing table creation. Preserve or export historical rows if they are still needed. Do not drop the table as part of a code cleanup. **Reduction:** up to 16 schema lines after that decision (`fleet/db.py:119`, `fleet/db.py:134`).

## Low / Debatable Findings

### LEGACY-003: Switch cost guardrail wrapper has no application caller

**Class:** NEEDS-VERIFICATION. **Evidence:** `measured_switch_cost` still describes a removed switch guardrail (`fleet/routability.py:116`, `README.md:13`). The live panel calls `_switch_cost_sessions` and `_usable_measured_cost` directly (`fleet/routability.py:138`, `fleet/routability.py:139`); the wrapper is called by tests (`tests/test_routability.py:37`, `tests/test_routability.py:41`).

**Action:** Check external imports of this public Python function. If there are none, remove only the wrapper and its wrapper-only tests. Keep the session calculation and the three-session display threshold (`fleet/routability.py:112`, `fleet/routability.py:138`). **Reduction:** 8 function lines (`fleet/routability.py:116`, `fleet/routability.py:123`).

### LEGACY-004: Tests still supply retired decision inputs

**Class:** SAFE-TO-REMOVE for unused fixture inputs; retain tests that check retired panels stay absent. **Evidence:** `_status_responses` accepts `decisions` but does not use that argument (`tests/test_queries.py:134`, `tests/test_queries.py:139`). The current status builder has no `recent_decisions` field (`fleet/queries.py:382`, `fleet/queries.py:398`), while dashboard fixtures still supply it (`tests/dashboard-harness.js:17`). A dashboard test uses historical decisions to confirm that retired panels stay absent (`tests/dashboard-view.test.js:95`, `tests/dashboard-view.test.js:103`).

**Action:** Remove the unused Python fixture argument and redundant default fixture fields during a test cleanup. Keep the explicit regression case that passes historical data (`tests/test_queries.py:134`, `tests/dashboard-harness.js:17`, `tests/dashboard-view.test.js:95`). **Reduction:** small test-only change; no product behavior change.

### LEGACY-005: Comments still describe the former control design

**Class:** SAFE-TO-REMOVE or update. **Evidence:** The database module header calls the service `v1` single-host and points to a `README` v1 scope section (`fleet/db.py:1`, `fleet/db.py:4`), while configuration iterates over multiple hosts (`fleet/config.py:124`, `fleet/config.py:126`). The deployment comment says `stop-first` prevents two tasks from writing decisions (`deploy/stack.yml:126`), although the README says the service no longer generates shadow decisions (`README.md:14`).

**Action:** Update the database header to describe the current host key, and delete or correct the deployment comment. Keep the deployment order until its operational reason is reviewed (`fleet/db.py:1`, `deploy/stack.yml:126`, `deploy/stack.yml:127`). **Reduction:** comment-only.

## Recommendations

1. Check direct SQL clients and live rows for `switch_lease`; remove its creation stanza only after that check (`fleet/db.py:40`).
2. Decide whether historical `decisions` must remain queryable. Keep stored rows until the retention decision is complete (`README.md:14`, `fleet/db.py:119`).
3. Check imports of `measured_switch_cost`, then remove the unused wrapper if no external caller exists. Keep the panel's active measurement path (`fleet/routability.py:116`, `fleet/routability.py:138`).
4. Clean stale fixture inputs and comments when those files next change; keep regression coverage for retired panels (`tests/test_queries.py:134`, `tests/dashboard-view.test.js:95`, `fleet/db.py:1`, `deploy/stack.yml:126`).

## Out of Scope / Flagged for Review

- `FLEET_EARNINGS_SHADOW` is enabled in the deployment and checked at runtime. Its optional state is documented. There is no evidence here that this flag is concluded (`deploy/stack.yml:75`, `fleet/earnings_shadow.py:94`, `README.md:68`).
- `FLEET_SWITCH_COST_SECONDS` still supplies a dashboard fallback and is not an old switch control (`fleet/config.py:118`, `fleet/routability.py:155`, `CONFIG.md:77`).
- The JavaScript hourly renderer accepts rows without `portions`. Current server rows include `portions`, but a test explicitly covers a cached legacy row. Keep this small compatibility path until the client and API transition window is known (`fleet/static/hourly.js:53`, `fleet/hourly.py:77`, `tests/hourly.test.js:29`).
- The `ALTER TABLE ... IF NOT EXISTS` statements also initialize existing databases at startup; do not delete them only because a migration ran once (`fleet/db.py:36`, `fleet/db.py:64`, `fleet/main.py:21`). The local compose file remains documented for local use (`README.md:23`, `README.md:28`, `planning/progress.md:47`).
- The `mode` field in `/api/status` is fixed to `MONITOR`, while the bundled card reads `card.manager.mode`. It is a public response field, so external client use needs review before removal (`fleet/queries.py:384`, `fleet/static/host.js:246`).

## Machine-Readable Findings

```json
{"findings": [
  {"id": "legacy-001", "file": "fleet/db.py", "line": 40, "severity": "MEDIUM", "confidence": "LIKELY", "recommendation": "VERIFY_EXTERNAL_USE", "detail": "The retired fleet switch lease table is still created at startup; check direct database use before removing its schema stanza.", "verified": false},
  {"id": "legacy-002", "file": "fleet/db.py", "line": 119, "severity": "MEDIUM", "confidence": "LIKELY", "recommendation": "SET_RETENTION_POLICY", "detail": "The retired decisions table is still provisioned, while the README says its historical rows remain in Postgres.", "verified": false},
  {"id": "legacy-003", "file": "fleet/routability.py", "line": 116, "severity": "LOW", "confidence": "LIKELY", "recommendation": "VERIFY_EXTERNAL_USE", "detail": "The old switch guardrail wrapper has test callers but the live panel uses its underlying functions directly.", "verified": false},
  {"id": "legacy-004", "file": "tests/test_queries.py", "line": 134, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "REMOVE_UNUSED_FIXTURE_INPUT", "detail": "The status response fixture accepts a decisions argument that its body does not use.", "verified": false},
  {"id": "legacy-005", "file": "fleet/db.py", "line": 1, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "UPDATE_COMMENTS", "detail": "The module header and deployment comment still describe the former single-host or fleet switching design.", "verified": false}
]}
```
