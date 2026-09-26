PONYTAIL MODE ACTIVE — level: full

# AI Slop Assessment

## Executive Summary

- Total issues found: **8**, covering **12 documentation passages** in **8 files**. The location table below lists every passage.
- Severity breakdown: **HIGH=0, MEDIUM=0, LOW=8**. These findings concern incorrect descriptions of existing behavior, not established runtime failures.
- Estimated impact: **33 existing physical lines contain the affected documentation**. This includes one line with CSS. No executable-code deletion is recommended.
- First priority: correct the demand-table description, which still excludes models that the current table displays (`CONFIG.md:137`, `fleet/queries.py:177`, `tests/test_queries.py:300`).
- Second priority: correct references to fleet switch controls and decision writes (`fleet/routability.py:117`, `deploy/stack.yml:126`, `README.md:13`).
- Third priority: document the actual payout and hourly return values (`fleet/remote.py:263`, `fleet/remote.py:268`, `fleet/hourly.py:83`, `fleet/hourly.py:104`).

This assessment uses Agent 8 only. The categories describe observable text defects. They do not establish AI authorship. Every JSON finding has `verified: false`.

### Pre-flight and method

The backend uses Python, FastAPI, Uvicorn, and psycopg (`requirements.txt:1`, `fleet/main.py:10`, `fleet/db.py:10`). The frontend uses JavaScript modules and Vitest (`package.json:3`, `package.json:5`, `fleet/static/dashboard.js:1`). Pytest configuration selects the tests directory (`pyproject.toml:1`). Vitest configuration selects JavaScript tests and browser-module coverage (`vitest.config.js:3`).

The local tool check found `rg`, `python3`, `node`, `npm`, and `eslint` on PATH. The listed Python analysis tools and `cloc` were not on PATH. Agent 8 specifies manual review. No tool installation was needed.

Method: read all runtime modules, search source and tests for artifact patterns, inspect candidate callers, and compare comments with implementation and relevant tests. Python AST inspection found no product `pass` statements. The apparent no-op redirect hook rejects redirects (`fleet/demand.py:18`). The test HTTP handler suppresses request logging (`tests/check_watch_delivery.py:12`, `tests/check_watch_delivery.py:21`). Neither is an unfinished implementation.

Verification was static. No application, browser, deployment, remote host, database, or external review service was started. Existing tests supplied evidence but were not executed. Other cleanup domains are outside this assessment.

### Counts by category

Counts use one issue per correction topic. Related passages share one issue ID.

| Category | Issues | Passages | Evidence |
|---|---:|---:|---|
| DEAD-COMMENT | 8 | 12 | All locations in the table below |
| COMMENT-SLOP | 0 | 0 | No retained finding |
| STUB | 0 | 0 | Excluded candidates: `fleet/demand.py:22`, `tests/check_watch_delivery.py:21` |
| LARP | 0 | 0 | No retained finding |
| OVER-DOCUMENTED | 0 | 0 | No retained finding |
| COMMENTED-OUT-CODE | 0 | 0 | No retained finding |
| WRAPPER-LARP | 0 | 0 | Excluded candidates: `fleet/static/dashboard.js:24`, `fleet/static/ui.js:112`, `fleet/web.py:36` |

Here, DEAD-COMMENT includes stale docstrings and Markdown descriptions. It does not mean that the associated executable code is dead.

### Concentration by file

This table measures flagged passages, not total comment volume. Line counts include complete affected comment or paragraph blocks. They are not estimated deletions.

| File and exact locations | Passages | Affected lines | Findings |
|---|---:|---:|---|
| `CONFIG.md:83`, `CONFIG.md:102`, `CONFIG.md:137` | 3 | 10 | ai-slop-001, ai-slop-007 |
| `fleet/routability.py:1`, `fleet/routability.py:117` | 2 | 10 | ai-slop-003 |
| `fleet/remote.py:19`, `fleet/remote.py:263` | 2 | 3 | ai-slop-004, ai-slop-006 |
| `fleet/db.py:1` | 1 | 5 | ai-slop-002 |
| `tests/test_remote.py:14` | 1 | 2 | ai-slop-006 |
| `fleet/hourly.py:83` | 1 | 1 | ai-slop-005 |
| `fleet/static/dashboard.html:115` | 1 | 1 | ai-slop-005 |
| `deploy/stack.yml:126` | 1 | 1 | ai-slop-008 |
| **Total** | **12** | **33** | **8 issues** |

## Critical Findings

None retained in this domain. This is not a security or runtime-correctness certification.

## Medium Findings

None retained. The findings below justify documentation edits only.

## Low / Debatable Findings

### ai-slop-001 — Demand documentation describes the previous display scope

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

`CONFIG.md:137` says the table includes only eligible models and omits stale snapshots. The implementation lists known installed models independently of manager eligibility (`fleet/queries.py:130`). It can calculate display scores for ineligible models (`fleet/queries.py:79`). Tests retain installed rows after the manager snapshot becomes stale (`tests/test_queries.py:329`). The page already describes the broader display scope (`fleet/static/dashboard.html:145`).

Replace the paragraph with: “The demand table lists installed models separately for each host. Fresh manager snapshots provide ranking inputs. Other display scores use fresh capacity and pricing data when available. The eligibility badge describes manager switching eligibility. Display scores do not change that eligibility.”

Keep the distinction between display ranking and switching eligibility (`fleet/queries.py:178`, `fleet/static/ui.js:25`). Do not change eligibility checks to match the old documentation.

### ai-slop-002 — Schema introduction still describes a single-host service

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

`fleet/db.py:1` calls the service single-host and refers to a README “v1 scope” section. The README instead describes fleet monitoring (`README.md:3`). Configuration discovers multiple hosts (`fleet/config.py:124`), and the application starts collection for each configuration (`fleet/web.py:46`).

Replace the module docstring with: “Postgres schema and connection pool. Host-scoped records use the immutable host ID, not the display label.”

Keep the host-identity explanation. Configuration explicitly distinguishes the database ID from the display label (`fleet/config.py:134`, `CONFIG.md:58`). Do not introduce a hosts table for this documentation correction.

### ai-slop-003 — Routability comments describe a retired switch guardrail

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

Two passages describe switch-control behavior: the module introduction at `fleet/routability.py:1` and the function docstring at `fleet/routability.py:117`. The latter names `DARKBLOOM_SWITCH_COST_SECONDS`. Configuration actually reads `FLEET_SWITCH_COST_SECONDS` (`fleet/config.py:118`). Its documented purpose is a display fallback (`CONFIG.md:77`).

The status builder supplies this value to the routability panel (`fleet/queries.py:381`). The panel returns configured and measured timing fields (`fleet/routability.py:155`). The UI renders those fields (`fleet/static/host.js:181`). The README states that fleet switch controls were removed (`README.md:13`).

Replace the module introduction with: “Dashboard routability observations, per-host request timings, and measured restart delays.”

Replace the function docstring with: “Return median start-to-first-request seconds and session count. Return None until at least three sessions have served a request.”

Preserve the three-session threshold and the account-wide timing limitation (`fleet/routability.py:112`, `fleet/routability.py:29`). This finding does not recommend function removal.

### ai-slop-004 — Payout reader claims to return an hourly rate

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

`fleet/remote.py:263` describes “$/model/hour.” The SQL reads individual payout rows after a row ID (`fleet/remote.py:40`). The function returns `Payout` objects without an hourly aggregation (`fleet/remote.py:268`). Its caller persists those rows (`fleet/collector.py:64`), and the test expects one raw payout object (`tests/test_remote.py:154`).

Replace the docstring with: “Read account-wide payout rows with rowid greater than since_rowid from the remote ledger.”

Keep the read-only SQLite connection and row cursor (`fleet/remote.py:39`, `fleet/remote.py:42`). Do not add aggregation to make the implementation match the old comment.

### ai-slop-005 — Hourly comments confuse API values with rendered glyphs

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

`fleet/hourly.py:83` says the function returns letters or idle dots. The result contains a legend and row objects (`fleet/hourly.py:104`). Each row stores model IDs or `None` in its portions (`fleet/hourly.py:73`). JavaScript converts those values to letters or dots (`fleet/static/hourly.js:51`). Tests explicitly expect model IDs and `None` (`tests/test_hourly.py:41`).

The related CSS comment describes a gap as an entire hour without service (`fleet/static/dashboard.html:115`). The renderer emits one gap glyph for a portion (`fleet/static/hourly.js:53`). Each portion spans 90 seconds (`fleet/hourly.py:13`, `fleet/hourly.py:15`, `fleet/hourly.py:16`). The panel explains that payouts do not measure GPU busy time (`fleet/static/hourly.js:12`).

Replace the Python docstring with: “Return a model legend and hourly rows containing payout counts, model IDs or None per portion, and percentages.”

Replace only the CSS comment with: “A 90-second portion with no recorded attributed inference payout.” Keep the CSS declaration unchanged.

### ai-slop-006 — SSH framing comments still describe two fields

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

The separator comment says that two documents share one SSH response (`fleet/remote.py:19`). The test helper repeats this description (`tests/test_remote.py:14`). The command emits daemon state, widget metrics, manager state, and a manager-running marker (`fleet/remote.py:22`). The parser splits four fields (`fleet/remote.py:149`), and the test helper constructs four fields (`tests/test_remote.py:16`).

Replace the separator comment with: “Separate daemon, widget, manager, and running-marker fields in one SSH response. A raw separator line cannot occur inside valid JSON.”

Replace the test helper docstring with: “Build the four-field SSH response, including optional manager state and the running marker.”

Keep the separator-safety explanation and optional-field behavior (`fleet/remote.py:20`, `fleet/remote.py:150`). The framing implementation needs no change for this finding.

### ai-slop-007 — Card documentation has an obsolete field count

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

The section introduces two data points (`CONFIG.md:83`) but lists widget metrics, daemon capacity/slots, and load errors (`CONFIG.md:87`, `CONFIG.md:94`, `CONFIG.md:98`). It then describes one added column per item (`CONFIG.md:102`). The schema stores several scalar metric columns, a slots JSONB column, and three load-error columns (`fleet/db.py:68`, `fleet/db.py:78`, `fleet/db.py:79`). The insert supplies these separate values (`fleet/db.py:184`).

Replace the introduction with: “The card combines widget metrics, daemon capacity and slots, and the last model load error from one SSH response.”

Replace the storage paragraph with: “The collector stores these values in daemon_snapshots. Metrics and load-error fields use separate columns. Slots use JSONB.”

Keep the existing explanations of missing metrics and GPU fallback behavior (`CONFIG.md:90`, `CONFIG.md:92`, `fleet/remote.py:94`).

### ai-slop-008 — Deployment comment names writes that no longer occur

**LOW · DEAD-COMMENT · CERTAIN · EDIT**

`deploy/stack.yml:126` explains `stop-first` as protection against duplicate decision writes. The README says that the service creates no new shadow decisions (`README.md:13`). The current collector writes daemon snapshots, earnings, identities, and demand data (`fleet/collector.py:121`, `fleet/collector.py:150`).

Replace the comment with: “Stop the old task before starting its replacement to avoid overlapping collection.”

Keep `order: stop-first` (`deploy/stack.yml:127`). The application starts collection tasks in each process (`fleet/web.py:46`). This finding does not justify changing deployment order.

## Recommendations

1. Correct the demand-table paragraph first. Reuse the current implementation and page wording as the source of truth (`fleet/queries.py:178`, `fleet/static/dashboard.html:145`).
2. Correct the switch-control descriptions together. Preserve timing observations and deployment order (`fleet/routability.py:155`, `deploy/stack.yml:127`, `CONFIG.md:77`).
3. Correct data-contract descriptions where producers and consumers already agree (`fleet/remote.py:268`, `fleet/hourly.py:104`, `fleet/static/hourly.js:51`).
4. Apply the remaining text corrections during the next documentation edit. Preserve immutable identity and missing-data semantics (`fleet/config.py:134`, `fleet/remote.py:150`, `fleet/remote.py:94`).

No new abstraction, dependency, runtime branch, or test framework is needed for these recommendations. Review only the proposed text edits before any application.

## Out of Scope / Flagged for Review

- **Keep security no-ops and validation.** `_NoRedirect.redirect_request` prevents authenticated redirects (`fleet/demand.py:18`, `fleet/demand.py:28`). Inventory parsing checks shape and size (`fleet/remote.py:125`). These are not removable stubs.
- **Keep test doubles.** The HTTP receiver implements POST handling and suppresses default logging (`tests/check_watch_delivery.py:16`, `tests/check_watch_delivery.py:21`). The fake database records SQL and returns supplied rows (`tests/conftest.py:24`). These support real checks.
- **Keep small helpers with concrete uses.** `subtitleEl` has two callers (`fleet/static/dashboard.js:24`, `fleet/static/dashboard.js:29`, `fleet/static/dashboard.js:34`). Focus helpers preserve keyboard focus (`fleet/static/ui.js:112`, `fleet/static/ui.js:130`, `tests/dashboard-refresh.test.js:174`). The static-file override adds cache headers (`fleet/web.py:36`). A short body alone does not establish wrapper noise.
- **Keep explanations of non-obvious behavior.** Account-wide payout ownership and vote rules explain attribution (`fleet/attribution.py:1`, `fleet/attribution.py:16`). The scheduler documents safe shutdown (`fleet/scheduler.py:21`). Neither is restating obvious syntax.
- **Keep linked work and historical records.** The model exclusion cites upstream issues (`deploy/stack.yml:71`). Progress entries name real PR work (`planning/progress.md:17`, `planning/progress.md:41`). The future watcher task requires owner review, not automatic deletion (`planning/progress.md:80`). No planned-work stub was accepted as a finding.
- **Defer dead-code and legacy decisions.** Historical decision schema remains present (`fleet/db.py:119`), and the README explicitly retains decision history (`README.md:14`). The measured-cost helper has tests (`tests/test_routability.py:37`). This assessment recommends no schema, function, or historical-record deletion.
- **Do not infer a palette defect from a comment.** The stylesheet claims prior palette validation (`fleet/static/dashboard.html:101`). This assessment does not verify that external claim or recommend removal of accessibility protections.

## Machine-Readable Findings

```json
{
  "findings": [
    {
      "id": "ai-slop-001",
      "file": "CONFIG.md",
      "line": 137,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Correct the eligible-only demand description using fleet/queries.py:177 and tests/test_queries.py:300, without changing eligibility logic.",
      "locations": [{"file": "CONFIG.md", "line": 137, "end_line": 141}],
      "verified": false
    },
    {
      "id": "ai-slop-002",
      "file": "fleet/db.py",
      "line": 1,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Replace the single-host framing with immutable host-ID semantics supported by fleet/config.py:124 and fleet/web.py:46.",
      "locations": [{"file": "fleet/db.py", "line": 1, "end_line": 5}],
      "verified": false
    },
    {
      "id": "ai-slop-003",
      "file": "fleet/routability.py",
      "line": 117,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Replace retired guardrail and environment-variable descriptions with timing-observation semantics supported by fleet/config.py:118 and fleet/routability.py:155.",
      "locations": [
        {"file": "fleet/routability.py", "line": 1, "end_line": 6},
        {"file": "fleet/routability.py", "line": 117, "end_line": 120}
      ],
      "verified": false
    },
    {
      "id": "ai-slop-004",
      "file": "fleet/remote.py",
      "line": 263,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Describe raw account-wide payout rows after since_rowid, matching fleet/remote.py:40 and fleet/remote.py:268, instead of claiming hourly rates.",
      "locations": [{"file": "fleet/remote.py", "line": 263, "end_line": 263}],
      "verified": false
    },
    {
      "id": "ai-slop-005",
      "file": "fleet/hourly.py",
      "line": 83,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Describe API portions as model IDs or None and rendered dots as payout gaps, matching fleet/hourly.py:73 and fleet/static/hourly.js:51.",
      "locations": [
        {"file": "fleet/hourly.py", "line": 83, "end_line": 83},
        {"file": "fleet/static/dashboard.html", "line": 115, "end_line": 115}
      ],
      "verified": false
    },
    {
      "id": "ai-slop-006",
      "file": "fleet/remote.py",
      "line": 19,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Describe all four SSH response fields in the separator and fixture comments, matching fleet/remote.py:149 and tests/test_remote.py:16.",
      "locations": [
        {"file": "fleet/remote.py", "line": 19, "end_line": 20},
        {"file": "tests/test_remote.py", "line": 14, "end_line": 15}
      ],
      "verified": false
    },
    {
      "id": "ai-slop-007",
      "file": "CONFIG.md",
      "line": 102,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Correct the card data and storage counts to match separate metric and load-error columns plus slots JSONB at fleet/db.py:68 and fleet/db.py:78.",
      "locations": [
        {"file": "CONFIG.md", "line": 83, "end_line": 85},
        {"file": "CONFIG.md", "line": 102, "end_line": 103}
      ],
      "verified": false
    },
    {
      "id": "ai-slop-008",
      "file": "deploy/stack.yml",
      "line": 126,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "category": "DEAD-COMMENT",
      "recommendation": "EDIT",
      "detail": "Describe overlapping collection instead of retired decision writes, as supported by fleet/web.py:46 and README.md:13, while preserving stop-first.",
      "locations": [{"file": "deploy/stack.yml", "line": 126, "end_line": 126}],
      "verified": false
    }
  ]
}
```
