PONYTAIL MODE ACTIVE — level: full

# Type Consolidation Assessment

## Executive Summary

- Total findings: **2**, both low-priority design judgments, not demonstrated runtime defects. The evidence is six identical `Row` aliases and five copies of the self-route tuple annotation. Sources: `fleet/attribution.py:14`, `fleet/card.py:14`, `fleet/health.py:10`, `fleet/hourly.py:11`, `fleet/queries.py:25`, `fleet/routability.py:11`, `fleet/routability.py:15`, `fleet/routability.py:127`, `fleet/queries.py:369`, `fleet/queries.py:375`, `fleet/web.py:104`.
- Severity breakdown: **HIGH=0, MEDIUM=0, LOW=2**. No duplicate domain class needs a merge: the shared ingestion records are `CapacitySample`, `Slot`, `DaemonState`, and `Payout`; configuration has its own owner. Sources: `fleet/types.py:11`, `fleet/types.py:25`, `fleet/types.py:34`, `fleet/types.py:70`, `fleet/config.py:43`.
- Top three priorities: (1) consider one self-route alias when those signatures next change; (2) keep the trivial `Row` aliases local; (3) preserve the existing ingestion records and the differences between stored rows and display data. Sources: `fleet/routability.py:15`, `fleet/queries.py:25`, `fleet/types.py:34`, `fleet/db.py:179`, `fleet/card.py:116`.
- Estimated impact: the two findings cover seven distinct production files. Only the optional self-route change warrants a migration plan: five annotation sites in three files, approximately 8–12 source lines touched after imports and the alias are included. No net LOC saving is claimed. Sources: `fleet/attribution.py:14`, `fleet/card.py:14`, `fleet/health.py:10`, `fleet/hourly.py:11`, `fleet/routability.py:15`, `fleet/routability.py:127`, `fleet/queries.py:369`, `fleet/queries.py:375`, `fleet/web.py:104`.

## Scope and Pre-flight

Analysis target: `darkbloom-fleet`, commit `a3d3e98ec1c9398144f23d2b88de9e7f2d97b0e9`. This assessment applies only the required skill's Agent 2 prompt: catalog definitions, trace their users, compare meanings, and propose small consolidation steps. It does not perform the later independent verification stage. All machine-readable findings remain `verified: false`.

The deployment uses Python 3.12, FastAPI, Uvicorn, and psycopg. The browser uses JavaScript ES modules. The repository configures pytest discovery and Vitest. Sources: `Dockerfile:1`, `requirements.txt:1`, `requirements.txt:2`, `requirements.txt:3`, `package.json:3`, `package.json:5`, `pyproject.toml:1`, `vitest.config.js:1`.

Read-only checks performed in this worktree:

- `git ls-files`, `rg`, numbered file reads, and a Python stdlib `ast` pass over all 42 tracked Python files. The source inventory also found 12 tracked JavaScript files. The catalog below records every class and type alias found; the JavaScript class is a test stub at `tests/dashboard-harness.js:133`.
- The AST pass found **14 Python classes**: seven production classes and seven test classes. It found **seven aliases**: six `Row` aliases and `Json`. Each definition and its location is listed below.
- Command lookup found `python3`, `rg`, `node`, and `npm`. It did not find `mypy`, `pyright`, `ruff`, `pylint`, `tsc`, or `cloc` on PATH. Local `.venv/bin/mypy`, `venv/bin/mypy`, `node_modules/.bin/tsc`, and `node_modules/.bin/vitest` were absent. These are session observations, not a claim that checks pass.
- No tools were installed. No application modules, remote probes, database checks, or browser tests were executed. The runtime tests cited below were read as contract evidence. Some standalone checks create temporary database tables or start a local HTTP server, so they were not used for this report-only task. Sources: `tests/check_earnings_shadow.py:8`, `tests/check_watch_delivery.py:29`, `tests/check_watch_delivery.py:42`.

## Type Catalog and Usage Map

### Production classes

| Domain | Definition and shape | Users and ownership decision |
| --- | --- | --- |
| Capacity and scoring | Frozen `CapacitySample`: model, request/provider counts, pressure, and optional throughput. `fleet/types.py:10`, `fleet/types.py:11`. | Parsed by `fleet/scoring.py:31`; returned by `fleet/demand.py:62`; passed through `fleet/collector.py:46`; scored at `fleet/scoring.py:58`; stored at `fleet/db.py:147`. **KEEP** the shared definition in `fleet/types.py`. |
| Resident backend | Frozen `Slot`: model, KV backend, and MTP fields. `fleet/types.py:24`, `fleet/types.py:25`. | Constructed by `fleet/remote.py:222`; composed into `DaemonState` at `fleet/types.py:56`; converted with `dataclasses.asdict` at `fleet/db.py:197`; read as JSON by `fleet/static/host.js:162`. **KEEP**. The JSON form is derived, not a second class to merge. |
| Daemon observation | Frozen `DaemonState`: session, trust, resources, slots, load error, inventory, manager report, and attestation key. `fleet/types.py:33`, `fleet/types.py:34`. | Produced by `fleet/remote.py:62`; enriched by `fleet/collector.py:101`; used for identity lookup at `fleet/collector.py:73`; stored by `fleet/db.py:179`. **KEEP** in `fleet/types.py`. |
| Ledger ingestion | Frozen `Payout`: row ID, model, tokens, integer micro-USD, creation time, and provider hash. `fleet/types.py:69`, `fleet/types.py:70`. | Produced by `fleet/remote.py:262`; passed through `fleet/collector.py:62`; stored by `fleet/db.py:210`. **KEEP** in `fleet/types.py`. |
| Configuration | Frozen `Config`: host identity, connection settings, scoring settings, and probe settings. `fleet/config.py:42`, `fleet/config.py:43`. | Direct production imports: `fleet/remote.py:9`, `fleet/collector.py:14`, `fleet/queries.py:14`, `fleet/scheduler.py:15`, `fleet/web.py:20`. `fleet/main.py:19` obtains instances from the loader. **KEEP** beside configuration parsing. |
| Authenticated HTTP | `_NoRedirect(HTTPRedirectHandler)`. `fleet/demand.py:18`. | Constructed only in the authenticated opener path at `fleet/demand.py:28`. **KEEP LOCAL**; this class prevents redirects of authenticated requests. |
| Static responses | `RevalidatedStaticFiles(StaticFiles)`. `fleet/web.py:32`. | Mounted by `fleet/web.py:59`; modifies file response cache headers at `fleet/web.py:36`. **KEEP LOCAL**; it has a different purpose from the HTTP redirect adapter. |

The production imports already reuse the ingestion types: `fleet/remote.py:10`, `fleet/collector.py:15`, `fleet/db.py:14`, `fleet/demand.py:12`, and `fleet/scoring.py:13`. Tests also import those definitions, rather than defining replacement domain classes: `tests/test_remote.py:10`, `tests/test_db.py:2`, `tests/test_collector_tick.py:9`, `tests/test_inventory.py:6`, `tests/test_demand.py:7`, and `tests/test_scoring.py:2`. The configuration test helper constructs the real `Config` at `tests/test_remote.py:21`.

### Named aliases

| Definition | Meaning at its use sites | Decision |
| --- | --- | --- |
| `Row = dict[str, object]`, `fleet/attribution.py:14` | Payout attribution vote rows at `fleet/attribution.py:66`. | KEEP LOCAL; see type-002. |
| `Row = dict[str, object]`, `fleet/card.py:14` | Snapshot input, status band, GPU block, load error, loaded-model chips, session totals, and assembled card at `fleet/card.py:24`, `fleet/card.py:42`, `fleet/card.py:63`, `fleet/card.py:74`, `fleet/card.py:90`, `fleet/card.py:108`, `fleet/card.py:116`. | KEEP LOCAL; one alias does not describe one record schema. |
| `Row = dict[str, object]`, `fleet/health.py:10` | Snapshot input, history rows, and health result at `fleet/health.py:45`, `fleet/health.py:49`, `fleet/health.py:124`. | KEEP LOCAL. |
| `Row = dict[str, object]`, `fleet/hourly.py:11` | Hour rows, panel output, and host-status input at `fleet/hourly.py:68`, `fleet/hourly.py:82`, `fleet/hourly.py:110`. | KEEP LOCAL. |
| `Row = dict[str, object]`, `fleet/queries.py:25` | Demand rows, stored snapshots, recent earnings, serving rows, and host status at `fleet/queries.py:28`, `fleet/queries.py:208`, `fleet/queries.py:241`, `fleet/queries.py:288`, `fleet/queries.py:374`. `fleet/web.py:68`, `fleet/web.py:85`, and `fleet/web.py:104` reuse it as `queries.Row`. | KEEP LOCAL; avoid making this broad alias the canonical schema for all these records. |
| `Row = dict[str, object]`, `fleet/routability.py:11` | Session timing, snapshot input, and routability panel at `fleet/routability.py:28`, `fleet/routability.py:126`. | KEEP LOCAL. |
| `Json = dict[str, object] \| list[object]`, `fleet/demand.py:15` | Return annotation of `_get_json` at `fleet/demand.py:26`. Callers inspect different external payloads at `fleet/demand.py:55`, `fleet/demand.py:64`, `fleet/demand.py:91`, `fleet/demand.py:110`. | KEEP LOCAL. Do not merge an external payload alias with internal database/display aliases. |

### Test classes

| Definition | Role and decision |
| --- | --- |
| `FakeResult`, `tests/conftest.py:9` | Replays database rows; constructed by `FakeConnection` at `tests/conftest.py:26`. KEEP in the existing test support module. |
| `FakeConnection`, `tests/conftest.py:20` | Records SQL; yielded by `FakePool` at `tests/conftest.py:44`. KEEP. |
| `FakePool`, `tests/conftest.py:35` | Supplies the shared `fake_pool` fixture at `tests/conftest.py:47`. KEEP. |
| `FakeOpener`, `tests/test_demand.py:38` | Local opener stub for the redirect test at `tests/test_demand.py:43`. KEEP LOCAL. |
| `Pinned`, `tests/check_earnings_shadow.py:22` | Yields the existing connection for a standalone SQL check at `tests/check_earnings_shadow.py:25`. KEEP LOCAL. |
| `PinnedPool`, `tests/check_watch_delivery.py:32` | Adds a transaction around each use of the pinned connection at `tests/check_watch_delivery.py:38`. KEEP LOCAL; it is not interchangeable with `Pinned`. |
| `Receiver(BaseHTTPRequestHandler)`, `tests/check_watch_delivery.py:12` | Receives HTTP test messages and is passed to `HTTPServer` at `tests/check_watch_delivery.py:42`. KEEP LOCAL. |
| Anonymous JavaScript class, `tests/dashboard-harness.js:133` | Stubs `DOMParser` inside the browser module harness at `tests/dashboard-harness.js:116`. KEEP in that harness. |

### Inline and implicit records

These are usage shapes, not additional declared classes. The ownership decisions prevent a superficial match of field names from becoming an unsafe merge.

| Concept and data flow | Consolidation assessment |
| --- | --- |
| Self-route observation: `latest_self_route` → `shared_status_data` → web worker → `build_status` → `routability_panel`. Sources: `fleet/routability.py:15`, `fleet/queries.py:371`, `fleet/web.py:72`, `fleet/web.py:77`, `fleet/web.py:106`, `fleet/queries.py:381`. | Same value and meaning throughout. Optional alias in `fleet/routability.py`; see type-001. |
| Stored daemon row: database query → demand, routability, card, and health builders. Sources: `fleet/queries.py:208`, `fleet/queries.py:377`, `fleet/queries.py:379`, `fleet/queries.py:381`, `fleet/queries.py:396`, `fleet/queries.py:399`. | A real shared record, but not interchangeable with `DaemonState`: storage adds ID/host/observation time and converts model tuples and slots. Sources: `fleet/db.py:51`, `fleet/db.py:189`, `fleet/db.py:196`, `fleet/db.py:197`. Do not add a duplicate 25-field class merely to rename `Row`. If a separate schema-typing task is approved, co-locate the stored-row contract with persistence and preserve these conversions. |
| Manager report: parser → daemon → JSONB → ranking/card/UI. Sources: `fleet/remote.py:153`, `fleet/types.py:65`, `fleet/db.py:198`, `fleet/queries.py:108`, `fleet/card.py:135`, `fleet/static/host.js:151`. | One report producer, with a two-key fallback at `fleet/remote.py:160`; nested external score data is inspected at `fleet/queries.py:111`. Keep validation and optional fields. A `ManagerReport` contract, if separately needed, belongs with the existing shared daemon types; no parallel parser model is justified here. |
| Host status: normal result and error result → hourly legend sharing and browser rendering. Sources: `fleet/queries.py:382`, `fleet/web.py:85`, `fleet/web.py:79`, `fleet/hourly.py:110`, `fleet/static/host.js:281`. | Error and success shapes intentionally differ: the error has null panels and the renderer selects an error card. Sources: `fleet/web.py:95`, `fleet/static/host.js:282`. Do not force missing error fields into a success-only model. Any future host-status contract should be owned beside `build_status`. |
| Capacity sample → stored demand row → manager-ranked display row. Sources: `fleet/types.py:11`, `fleet/db.py:147`, `fleet/queries.py:28`, `fleet/queries.py:144`, `fleet/static/ui.js:32`. | KEEP SEPARATE. The display includes manager eligibility and missing live measurements, unlike the parsed capacity record. Sources: `fleet/queries.py:166`, `fleet/queries.py:167`. |
| Payout → stored earnings → recent-earnings display or aggregate earnings profile. Sources: `fleet/types.py:70`, `fleet/db.py:210`, `fleet/queries.py:231`, `fleet/earnings_shadow.py:52`. | KEEP SEPARATE. Storage adds host/ingestion time and renames `rowid` to `payout_rowid`; the recent display selects only four fields, while the profile aggregates. Sources: `fleet/db.py:213`, `fleet/db.py:217`, `fleet/queries.py:232`, `fleet/earnings_shadow.py:60`. |
| Card status, resources, GPU, chips, KPIs; health result; routability session/models/switch cost. Sources: `fleet/card.py:122`, `fleet/health.py:45`, `fleet/routability.py:140`. | Keep beside their builders. Shared words such as `state`, `model`, and `started_at` do not make these the same record. The health states and card states differ at `fleet/health.py:12` and `fleet/card.py:46`. |
| Hour bucket and legend → cross-host legend → browser color entry. Sources: `fleet/hourly.py:77`, `fleet/hourly.py:105`, `fleet/hourly.py:115`, `fleet/static/hourly.js:75`. | Keep with hourly presentation. The browser adds a numeric color `slot`; this is not the provider backend `Slot` at `fleet/types.py:25`. |
| Watch probe, condition, saved alert, and outgoing alert payload. Sources: `fleet/watch.py:39`, `fleet/watch.py:47`, `fleet/watch.py:66`, `fleet/watch.py:92`. | Local to the watch flow; do not replace them with `DaemonState` or dashboard health. Conditions distinguish unknown (`None`), recovered (`False`), and a delay/detail tuple at `fleet/watch.py:49`, `fleet/watch.py:59`, `fleet/watch.py:69`, `fleet/watch.py:78`. |
| UI expansion/scroll state, focus state, and refresh gate. Sources: `fleet/static/ui.js:48`, `fleet/static/ui.js:86`, `fleet/static/ui.js:139`; consumers at `fleet/static/dashboard.js:65`, `fleet/static/dashboard.js:72`, `fleet/static/dashboard.js:113`. | Keep with the UI helpers. These are not API host records even though some contain a `host` key. |

### Naming, hierarchy, and generic types

- The four ingestion dataclasses and `Config` do not declare base classes. `DaemonState` composes `Slot` instead of extending it. The production adapters each extend one external base. No local inheritance chain needs consolidation. Sources: `fleet/types.py:11`, `fleet/types.py:25`, `fleet/types.py:34`, `fleet/types.py:56`, `fleet/types.py:70`, `fleet/config.py:43`, `fleet/demand.py:18`, `fleet/web.py:32`.
- No custom generic class, `Protocol`, `TypedDict`, enum, or `NamedTuple` declaration was found in the cataloged source. The declared union alias is the local `Json`; built-in collection annotations describe records and maps. Representative declarations: `fleet/demand.py:15`, `fleet/types.py:19`, `fleet/types.py:56`, `fleet/config.py:52`, `fleet/hourly.py:69`.
- Identical annotations can encode different meanings. `tuple[dict[str, float], float]` means prices plus fallback at `fleet/demand.py:87`, but EMA values plus update time at `fleet/db.py:230`. `dict[str, str]` means provider-to-host attribution at `fleet/attribution.py:88`, but model-to-letter mapping at `fleet/hourly.py:35`. **KEEP SEPARATE**; do not introduce one generic result alias for these.
- Naming differences at boundaries are deliberate: `Payout.rowid` becomes stored `payout_rowid` at `fleet/db.py:213`; manager `last_decision_target` becomes display `target_model` at `fleet/remote.py:168`; a routability function's `host` is supplied from `cfg.host_id` at `fleet/queries.py:376`, `fleet/queries.py:381`. No mass rename is justified by these examples.

## Critical Findings

None supported by this domain analysis. The ingestion records already use shared definitions and imports. Sources: `fleet/types.py:11`, `fleet/types.py:25`, `fleet/types.py:34`, `fleet/types.py:70`, `fleet/remote.py:10`, `fleet/db.py:14`.

## Medium Findings

None supported. The two candidates below repeat annotations, with no conflicting declared shape or demonstrated runtime failure. Sources: `fleet/queries.py:25`, `fleet/routability.py:11`, `fleet/routability.py:15`, `fleet/queries.py:369`, `fleet/web.py:104`.

## Low / Debatable Findings

### type-001 — One self-route result is annotated independently in three modules

**Severity:** LOW. **Confidence in the observed repetition:** CERTAIN. **Recommendation:** REVIEW; optional consolidation during the next relevant edit.

The exact annotation `tuple[float | None, dict[str, int]]` occurs five times: the return of `latest_self_route`, the panel argument, the nested return of `shared_status_data`, the `build_status` argument, and the web worker argument. Sources: `fleet/routability.py:15`, `fleet/routability.py:127`, `fleet/queries.py:369`, `fleet/queries.py:375`, `fleet/web.py:104`.

These are the same account-wide observation, not five coincidentally similar tuples. The producer supplies the observation time and counts; the callers pass that result through unchanged before the panel unpacks it. Sources: `fleet/routability.py:16`, `fleet/routability.py:25`, `fleet/queries.py:371`, `fleet/web.py:72`, `fleet/web.py:77`, `fleet/web.py:106`, `fleet/queries.py:381`, `fleet/routability.py:128`. Existing tests assert the empty/populated forms and shared object identity: `tests/test_routability.py:5`, `tests/test_routability.py:10`, `tests/test_web_main.py:71`.

**Smallest plan:** if these signatures change, define `SelfRouteSnapshot = tuple[float | None, dict[str, int]]` in `fleet/routability.py` beside `latest_self_route`. Replace only the five annotation occurrences and import the alias in `queries.py` and `web.py`. Keep tuple construction, unpacking, and the missing-probe value `(None, {})`. The affected sites are `fleet/routability.py:15`, `fleet/routability.py:20`, `fleet/routability.py:127`, `fleet/queries.py:369`, `fleet/queries.py:375`, and `fleet/web.py:104`.

**Risk and value:** low risk if limited to annotations; modest readability and one declaration to update. There is no current type disagreement to repair. Skip a standalone refactor, dataclass, generic wrapper, or new top-level type package. The current two-element representation and handoff already agree at `fleet/routability.py:25`, `fleet/queries.py:371`, and `fleet/routability.py:128`.

### type-002 — Six identical `Row` aliases do not justify a central record type

**Severity:** LOW. **Confidence in the observed repetition:** CERTAIN. **Recommendation:** KEEP SEPARATE.

Six modules declare `Row = dict[str, object]`: `fleet/attribution.py:14`, `fleet/card.py:14`, `fleet/health.py:10`, `fleet/hourly.py:11`, `fleet/queries.py:25`, and `fleet/routability.py:11`. The AST and direct line reads confirm identical alias expressions. Web code already reuses `queries.Row` at `fleet/web.py:68`, `fleet/web.py:85`, and `fleet/web.py:104`.

The aliases do not define duplicate field schemas. For example, one use contains vote identity fields, another health state, another hourly portions, and another session timing. Sources: `fleet/attribution.py:71`, `fleet/health.py:45`, `fleet/hourly.py:77`, `fleet/routability.py:49`. Even a single module uses `Row` for different inputs and outputs: `fleet/card.py:42`, `fleet/card.py:63`, `fleet/card.py:116`.

**Smallest plan:** leave the six one-line aliases where they are. Replacing declarations with imports would preserve the same broad `dict[str, object]` shape and would not establish required keys. If a later typing task addresses a specific shared record, give that record a domain name and one owner; do not apply a single replacement to every `Row`. The actual shared stored-daemon path is `fleet/queries.py:377`, `fleet/queries.py:381`, `fleet/queries.py:396`, and `fleet/queries.py:399`.

**Risk and value:** zero product changes recommended. A universal row schema would conflate unrelated records, while a universal alias only moves six lines. Keep the boundary between persisted snapshots and card output shown at `fleet/db.py:179` and `fleet/card.py:122`.

## Recommendations

1. **No standalone consolidation change is needed now.** Keep `Row` local. If the self-route signatures change, use the one-line alias plan in type-001; do not change its value representation. Sources: `fleet/queries.py:25`, `fleet/routability.py:15`, `fleet/routability.py:128`.
2. **Use the existing domain owners.** Keep ingestion records in `fleet/types.py`, configuration in `fleet/config.py`, and the local adapters beside their users. Sources: `fleet/types.py:1`, `fleet/config.py:43`, `fleet/demand.py:28`, `fleet/web.py:59`. Do not add a global `types/` directory or duplicate SQL/display fields into ingestion classes.
3. **If type-001 is applied later, reuse the existing checks.** The missing/populated probe checks, shared-data check, and account-wide handoff check cover the relevant behavior. Sources: `tests/test_routability.py:4`, `tests/test_routability.py:8`, `tests/test_queries.py:236`, `tests/test_web_main.py:52`. Suggested targeted command in an environment with dependencies: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_routability.py tests/test_queries.py tests/test_web_main.py`. This command was not run during the assessment.
4. **Preserve boundary behavior in any later typing work.** Keep inventory unknown distinct from known empty, retain input-shape checks, and keep authenticated redirect protection. Sources: `fleet/types.py:62`, `fleet/remote.py:125`, `fleet/demand.py:55`, `fleet/demand.py:110`, `fleet/demand.py:18`. Keep output escaping and keyboard-focus restoration when documenting browser shapes. Sources: `fleet/static/ui.js:8`, `fleet/static/dashboard.js:72`, `fleet/static/dashboard.js:73`.

## Out of Scope / Flagged for Review

- General weak-typing remediation is a different assessment. Broad dictionaries, unannotated watch/profile functions, and partial external JSON are cataloged here only to distinguish ownership and meaning. Sources: `fleet/queries.py:25`, `fleet/watch.py:47`, `fleet/earnings_shadow.py:52`, `fleet/queries.py:108`. No new schema hierarchy or full TypeScript migration is proposed.
- The external manager implementation and its full schema were not inspected. The in-repository parser passes nested score data onward, and the consumer checks its structure. Sources: `fleet/remote.py:172`, `fleet/queries.py:111`. No unsupported claim about remote schema compatibility is made.
- Do not consolidate `Pinned`, `PinnedPool`, or the shared fake pool based only on their `connection()` method. They respectively yield a real existing connection, open a transaction, and replay canned responses. Sources: `tests/check_earnings_shadow.py:23`, `tests/check_watch_delivery.py:38`, `tests/conftest.py:26`, `tests/conftest.py:43`.
- The runtime test files were read, not executed. This report establishes source-level type ownership and repetition; it does not establish a passing type checker, database migration, or production API check. Test behavior referenced for a possible later change is at `tests/test_routability.py:4`, `tests/test_queries.py:236`, and `tests/test_web_main.py:52`.

## Machine-Readable Findings

```json
{
  "findings": [
    {
      "id": "type-001",
      "file": "fleet/routability.py",
      "line": 15,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "recommendation": "REVIEW",
      "detail": "The same self-route observation tuple is repeated at fleet/routability.py:15, fleet/routability.py:127, fleet/queries.py:369, fleet/queries.py:375, and fleet/web.py:104; if these signatures next change, use one SelfRouteSnapshot alias in fleet/routability.py and preserve the current tuple representation.",
      "verified": false
    },
    {
      "id": "type-002",
      "file": "fleet/queries.py",
      "line": 25,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "recommendation": "KEEP SEPARATE",
      "detail": "Identical Row aliases at fleet/attribution.py:14, fleet/card.py:14, fleet/health.py:10, fleet/hourly.py:11, fleet/queries.py:25, and fleet/routability.py:11 cover different record shapes; retain the local aliases because a central dict[str, object] alias would add imports without specifying field schemas.",
      "verified": false
    }
  ]
}
```
