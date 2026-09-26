Ponytail full intensity: keep real unknowns at input boundaries; add only types and checks that protect an active path.

# Weak Typing Assessment

## Executive Summary

- Total actionable issues: **7**. Severity: **HIGH=1, MEDIUM=3, LOW=3**. These findings touch 13 production files. The six broad `Row` aliases alone occur in `fleet/queries.py:25`, `fleet/routability.py:11`, `fleet/attribution.py:14`, `fleet/hourly.py:11`, `fleet/health.py:10`, and `fleet/card.py:14`.
- Priorities: validate saved watchdog state before alert transitions (`fleet/watch.py:118-122`); validate the dashboard response before marking a poll successful (`fleet/static/dashboard.js:90-99`); give database and API rows types that match the fields their consumers use (`fleet/queries.py:25`, `fleet/web.py:65-68`).
- Estimated impact: 13 files contain the seven finding sites. The main work is at input and output boundaries; this assessment does not propose a TypeScript migration or a repository-wide type rewrite (`package.json:1-7`, `fleet/demand.py:33-42`).
- Method: read the production call paths, SQL schema, and relevant tests. The worktree has Python and plain JavaScript (`Dockerfile:1`, `package.json:1-7`); `pyproject.toml:1-3` has pytest settings only. Local `mypy`, `pyright`, and `ruff` modules are unavailable, so there is no checker result. No explicit `Any`, `cast()`, `# type: ignore`, or TypeScript suppression was found in the scanned production files.

## Critical Findings

### WT-001 — Watchdog JSON state is used without shape checks (HIGH; confidence HIGH)

`conditions(status)` and `transition(saved, observed, now)` have no type annotations (`fleet/watch.py:47`, `fleet/watch.py:66`). The SSH probe is parsed with `json.loads`, then passed to `conditions` (`fleet/watch.py:109-116`). A truthy non-object `pending` value reaches `pending.get()` (`fleet/watch.py:54-58`). The stored JSONB state is passed directly to `transition` (`fleet/db.py:17-20`, `fleet/watch.py:118-121`). `transition` assumes each saved item has numeric `since` and boolean `firing` (`fleet/watch.py:66-84`). A malformed saved item can raise before alert delivery; the loop catches the failure and waits for the next cycle (`fleet/watch.py:122-145`). I reproduced `AttributeError` for `pending: [1]` and `TypeError` for a saved item with `since: "bad"` and `firing: false`, using the functions at `fleet/watch.py:47-84`.

**Replacement:** define local `ProbeStatus` and `WatchRecord` `TypedDict`s. `ProbeStatus` needs `provider_running`, `provider_fresh`, `manager_running`, and `manager_fresh` as `bool`; `warm` as `list[str]`; `pending` as `{target: str, command_error?: str} | None`; and `reason` as `str` (`fleet/watch.py:52-58`). `WatchRecord` needs `since: float`, `firing: bool`, `detail: str`, and optional `ended: float` (`fleet/watch.py:73-101`). Treat `json.loads` and the JSONB row as `object` until a small validator accepts that shape; preserve the existing unknown-probe behavior (`fleet/watch.py:47-51`, `fleet/watch.py:109-121`). An annotation alone cannot protect either input.

## Medium Findings

### WT-002 — Browser treats unvalidated JSON as a good status (MEDIUM; confidence HIGH)

`loadStatus` returns `response.json()` without checking its shape (`fleet/static/dashboard.js:90-94`). `applyStatus` saves it and updates `lastGoodAt` before rendering (`fleet/static/dashboard.js:96-101`); `render` then assumes `s.hosts` is usable by `mergeDemand` and `renderHosts` (`fleet/static/dashboard.js:63-76`). A `null` response is already tested as an empty render (`tests/dashboard-poll.test.js:108-112`), but it is still saved as the latest successful poll by this path (`fleet/static/dashboard.js:96-101`, `fleet/static/dashboard.js:117-123`).

**Replacement:** keep JavaScript and use `Array.isArray(data?.hosts)` before `applyStatus`. Reject a wrong top-level shape as a poll failure, so the prior good status and its timestamp remain available (`fleet/static/dashboard.js:104-108`, `fleet/static/dashboard.js:117-123`). A JSDoc `Status` shape can document the accepted result after that check; it cannot replace the runtime guard (`fleet/static/dashboard.js:90-99`).

### WT-003 — One broad `Row` alias covers unrelated database and response shapes (MEDIUM; confidence HIGH)

Six modules each define `Row = dict[str, object]` (`fleet/queries.py:25`, `fleet/routability.py:11`, `fleet/attribution.py:14`, `fleet/hourly.py:11`, `fleet/health.py:10`, `fleet/card.py:14`). The alias covers SQL rows from a `dict_row` pool (`fleet/db.py:138-139`, `fleet/queries.py:208-212`), calculations that require numeric fields (`fleet/queries.py:123-126`, `fleet/queries.py:296-306`), nested hourly panels (`fleet/hourly.py:104-117`), and the `/api/status` response (`fleet/queries.py:374-400`, `fleet/web.py:65-80`). `dict[str, object]` does not express the required keys or their field types at these internal handoffs (`fleet/queries.py:25`, `fleet/hourly.py:110-117`).

**Replacement:** type the few handoffs that use fixed shapes: a `DaemonSnapshot` `TypedDict` with `observed_at: float`, `current_model: str | None`, `inference_active: bool`, `fresh: bool`, `started_at: float`, and the other consumed SQL columns (`fleet/db.py:51-84`, `fleet/queries.py:374-400`); a `DemandSampleRow` with `model: str`, `observed_at: float`, and nullable score and metric fields (`fleet/queries.py:28-38`); and a local `HourlyPanel` with `legend` and `rows` for `share_legends` (`fleet/hourly.py:104-117`). Keep flexible response dictionaries where the fields are genuinely optional; do not create a universal replacement for `Row` (`fleet/web.py:85-100`).

### WT-004 — HTTP JSON return type claims more than the parser checks (MEDIUM; confidence HIGH)

`Json` permits only an object or array, but `_get_json` returns raw `json.load` output without a top-level check (`fleet/demand.py:15`, `fleet/demand.py:26-30`). The callers separately check for expected top-level shapes (`fleet/demand.py:54-68`, `fleet/demand.py:90-92`, `fleet/demand.py:108-112`). In the pricing path, `prices` is then iterated without a list check, and `fallback_output_price` is converted without a value check (`fleet/demand.py:90-95`). A valid JSON scalar or wrong `prices` type can therefore make the pricing feed fail at a later operation (`fleet/demand.py:90-95`, `fleet/collector.py:53-58`).

**Replacement:** annotate `_get_json` as returning `object`; keep the existing shape checks, and check `prices` is a list before iteration (`fleet/demand.py:26-30`, `fleet/demand.py:90-95`). Parse the fallback as a numeric value at the same boundary. `object` is correct until the response is validated; replacing it with `Any` would remove useful checks (`fleet/demand.py:33-42`, `fleet/demand.py:77-84`).

## Low / Debatable Findings

### WT-005 — Normalized manager report loses its known shape (LOW; confidence MEDIUM)

`_manager_report` builds known fields but returns `dict[str, object]`, and `DaemonState.manager` uses the same broad type (`fleet/remote.py:153-174`, `fleet/types.py:65`). The value is stored as JSONB, read from a daemon snapshot, and displayed through the card (`fleet/db.py:187-198`, `fleet/queries.py:108-116`, `fleet/card.py:133-135`). The nested `score_snapshot` and `earnings_shadow` values come from the remote file without field validation (`fleet/remote.py:172-173`), while the ranking consumer checks the snapshot container before use (`fleet/queries.py:108-116`).

**Replacement:** if static checking is adopted, use a `ManagerReport` `TypedDict` for the normalized fields: `running: bool`, `mode: Literal["LIVE", "OFF"]`, optional `fresh: bool`, `as_of: float | None`, model and reason strings, and `streak: int` (`fleet/remote.py:153-174`). Keep the two nested remote values as `object` until their consumers validate them (`fleet/remote.py:172-173`, `fleet/queries.py:108-116`).

### WT-006 — Earnings profile publication has no annotated contract (LOW; confidence MEDIUM)

`build_profile`, `publish`, `tick`, and `run_forever` lack parameter and return hints (`fleet/earnings_shadow.py:52`, `fleet/earnings_shadow.py:71`, `fleet/earnings_shadow.py:88`, `fleet/earnings_shadow.py:94`). `build_profile` produces a fixed profile shape, and `publish` serializes that shape to a file through SSH (`fleet/earnings_shadow.py:57-85`). The caller accesses `profile['models']` without an annotated model map (`fleet/earnings_shadow.py:88-91`).

**Replacement:** when this file is edited for type checking, add `Config`, `ConnectionPool`, `asyncio.Event`, and `None` annotations to its four public path functions. Use a local `EarningsProfile` `TypedDict` with `schema: Literal[1]`, host and time fields, and `models: dict[str, EarningsModel]`; the model fields are the float, optional float, and int values assembled at `fleet/earnings_shadow.py:60-68`. Keep the existing `json.dumps(..., allow_nan=False)` boundary check (`fleet/earnings_shadow.py:71-73`).

### WT-007 — Shared config kwargs are broader than `Config` (LOW; confidence LOW)

`_host_config` accepts `shared: dict[str, object]` and unpacks it into the typed `Config` constructor (`fleet/config.py:42-62`, `fleet/config.py:92-106`). The map is built locally with fixed keys and types (`fleet/config.py:109-123`), so the broad parameter loses information that is already available at its one caller (`fleet/config.py:126-127`).

**Replacement:** if the project adds a Python type checker, give `shared` a local `TypedDict` with exactly the keys at `fleet/config.py:111-123`; avoid a new configuration framework. This is low priority because the map is created and consumed in one module (`fleet/config.py:92-127`).

## Weak-Type Inventory

- **Unannotated production functions:** `conditions`, `transition`, `timestamp`, `payload`, `save`, `tick`, and `run_forever` (`fleet/watch.py:47`, `fleet/watch.py:66`, `fleet/watch.py:88`, `fleet/watch.py:92`, `fleet/watch.py:104`, `fleet/watch.py:109`, `fleet/watch.py:136`). Type the first two with the validated `ProbeStatus`, `WatchRecord`, and `Condition = tuple[int, str] | Literal[False] | None` shapes above; use `float -> str` for `timestamp`, `str`/watch records/`float` for `payload`, `Config`/pool/connection types for the I/O functions, and `None` returns for side-effect functions (`fleet/watch.py:47-147`). The four unannotated earnings functions and their profile contract are covered by WT-006 (`fleet/earnings_shadow.py:52`, `fleet/earnings_shadow.py:71`, `fleet/earnings_shadow.py:88`, `fleet/earnings_shadow.py:94`). The only unannotated override is marked REVIEW below (`fleet/web.py:36-39`).
- **Raw values that must stay broad until checked:** API rows (`fleet/demand.py:33`, `fleet/demand.py:77`, `fleet/scoring.py:31`); remote inventory and scalar parser inputs (`fleet/remote.py:116`, `fleet/remote.py:177`, `fleet/remote.py:253`); and snapshot numeric parser inputs (`fleet/queries.py:41`, `fleet/queries.py:55`, `fleet/queries.py:119`, `fleet/queries.py:149`). Their callers or bodies perform shape/value checks (`fleet/demand.py:33-42`, `fleet/scoring.py:37-46`, `fleet/remote.py:116-144`, `fleet/queries.py:41-58`, `fleet/queries.py:119-120`). Replacement type: `object` at entry, then the parsed `str`, `int`, `float`, or `None` result already shown in those signatures (`fleet/demand.py:33`, `fleet/remote.py:116`, `fleet/queries.py:41`).
- **Raw dictionaries that must stay broad until field validation:** widget, daemon sections, slots, and capacity (`fleet/remote.py:184`, `fleet/remote.py:197`, `fleet/remote.py:208`, `fleet/remote.py:217`, `fleet/remote.py:222`, `fleet/remote.py:239`, `fleet/remote.py:248`, `fleet/remote.py:257`), capacity metrics (`fleet/scoring.py:16`), and remote manager score inputs (`fleet/queries.py:79`, `fleet/queries.py:108`, `fleet/queries.py:131`, `fleet/queries.py:147`). Replacement type: keep `dict[str, object]` for the unvalidated map, then return the existing typed scalar, tuple, `Slot`, or demand row after parsing (`fleet/remote.py:197-259`, `fleet/scoring.py:16-28`, `fleet/queries.py:144-174`). The normalized manager result and `DaemonState.manager` are WT-005 (`fleet/remote.py:153`, `fleet/types.py:65`); the internal shared config map is WT-007 (`fleet/config.py:92`).
- **Broad row aliases:** all six locations and their targeted replacement shapes are WT-003 (`fleet/queries.py:25`, `fleet/routability.py:11`, `fleet/attribution.py:14`, `fleet/hourly.py:11`, `fleet/health.py:10`, `fleet/card.py:14`). The raw HTTP JSON alias is WT-004 (`fleet/demand.py:15`).

## Recommendations

1. Add runtime shape checks at the two active JSON boundaries: watchdog state first, dashboard status second (`fleet/watch.py:109-122`, `fleet/static/dashboard.js:90-99`).
2. When a checker is available, type the fixed SQL rows and the hourly panel where broad `Row` currently hides required fields (`fleet/queries.py:25-38`, `fleet/hourly.py:104-117`).
3. Correct `_get_json` to return `object`, and narrow pricing fields at the parser (`fleet/demand.py:15-30`, `fleet/demand.py:90-95`).
4. Add manager, profile, and config `TypedDict`s only with work that uses those contracts (`fleet/remote.py:153-174`, `fleet/earnings_shadow.py:52-85`, `fleet/config.py:92-123`).

## Out of Scope / Flagged for Review

- **KEEP — legitimately unknown inputs.** `object` is suitable for raw API rows and value parsers that validate before use (`fleet/demand.py:33-42`, `fleet/demand.py:77-84`, `fleet/scoring.py:16-55`, `fleet/remote.py:116-144`, `fleet/remote.py:177-181`, `fleet/remote.py:253-259`, `fleet/queries.py:41-58`, `fleet/queries.py:119-120`). Raw remote dictionaries remain broad while fields are checked (`fleet/remote.py:184-250`, `fleet/queries.py:79-116`, `fleet/queries.py:130-155`). No recommendation here replaces `object` with `Any`.
- **REVIEW — framework override.** `RevalidatedStaticFiles.file_response` has untyped `*args` and `**kwargs`, but it forwards them unchanged to the parent method (`fleet/web.py:32-39`). Check the installed Starlette signature before annotating this override; a guessed signature risks conflict with the library (`requirements.txt:1`, `fleet/web.py:36-39`).
- **KEEP — test helpers and plain JavaScript.** Tests intentionally use shape-flexible fakes and partial payloads (`tests/conftest.py:9-44`, `tests/test_web_main.py:46-49`, `tests/dashboard-poll.test.js:72-80`). The browser code is plain JavaScript, and the package lists Vitest tools, not TypeScript or `@types/*` (`package.json:1-7`, `fleet/static/dashboard.js:1-5`). No `@types/*` installation is indicated by this assessment.
- **External contracts need confirmation.** The manager file fields and public API pricing fields are inferred from local parsing and tests, not a checked SDK or upstream schema (`fleet/remote.py:153-174`, `tests/test_remote.py:83-101`, `fleet/demand.py:87-95`, `tests/test_demand.py:73-80`). Confirm those fields against the producer before making stricter wire types.

## Machine-Readable Findings

```json
{"findings":[
  {"id":"weak-typing-001","file":"fleet/watch.py","line":118,"severity":"HIGH","confidence":"HIGH","recommendation":"VALIDATE_AND_TYPE","detail":"Validate probe and saved JSONB state before alert transition; type ProbeStatus and WatchRecord.","verified":false},
  {"id":"weak-typing-002","file":"fleet/static/dashboard.js","line":93,"severity":"MEDIUM","confidence":"HIGH","recommendation":"VALIDATE","detail":"Check response hosts shape before saving it as the latest good poll.","verified":false},
  {"id":"weak-typing-003","file":"fleet/queries.py","line":25,"severity":"MEDIUM","confidence":"HIGH","recommendation":"STRENGTHEN","detail":"Replace broad Row aliases at fixed SQL and dashboard handoffs with small shape-specific types.","verified":false},
  {"id":"weak-typing-004","file":"fleet/demand.py","line":15,"severity":"MEDIUM","confidence":"HIGH","recommendation":"CORRECT_AND_VALIDATE","detail":"Return object from raw JSON load and validate pricing fields before use.","verified":false},
  {"id":"weak-typing-005","file":"fleet/types.py","line":65,"severity":"LOW","confidence":"MEDIUM","recommendation":"STRENGTHEN_WHEN_CHECKED","detail":"Type normalized manager fields while keeping raw nested values as object.","verified":false},
  {"id":"weak-typing-006","file":"fleet/earnings_shadow.py","line":52,"severity":"LOW","confidence":"MEDIUM","recommendation":"STRENGTHEN_WHEN_CHECKED","detail":"Annotate the earnings publication path and its fixed profile shape.","verified":false},
  {"id":"weak-typing-007","file":"fleet/config.py","line":92,"severity":"LOW","confidence":"LOW","recommendation":"REVIEW","detail":"Type the locally built shared config kwargs if a checker is added.","verified":false}
]}
```
