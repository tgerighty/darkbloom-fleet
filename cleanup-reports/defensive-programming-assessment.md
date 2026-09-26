ponytail: full intensity — climb the YAGNI ladder; prefer reuse, stdlib, and native features; use minimal diffs; preserve trust-boundary validation, security, and accessibility.

# Defensive Programming Assessment

## Executive Summary

- Scope: Agent 6 only, `darkbloom-fleet`, supplied revision `a3d3e98`. This is an analysis report. All machine-readable findings have `verified: false`.
- Total issues: **6**. Severity: **HIGH=0, MEDIUM=5, LOW=1**. The finding sites are `fleet/health.py:53`, `fleet/demand.py:59`, `fleet/demand.py:65`, `fleet/remote.py:180`, `fleet/earnings_shadow.py:59`, and `fleet/static/dashboard.js:98`.
- First priority: expire old daemon evidence before the health fallback returns `HEALTHY` (`fleet/health.py:53`, `fleet/health.py:64`).
- Second priority: distinguish a failed routing parse from a successful empty probe (`fleet/demand.py:41`, `fleet/demand.py:59`, `fleet/db.py:203`).
- Third priority: preserve unknown earnings evidence instead of publishing measured-looking zeros (`fleet/earnings_shadow.py:59`, `fleet/earnings_shadow.py:64`, `README.md:73`).
- Estimated review impact: about **205 lines of function context across six primary source files**, not 205 lines to delete. The relevant functions start at `fleet/health.py:49`, `fleet/demand.py:33`, `fleet/remote.py:177`, `fleet/scoring.py:16`, `fleet/earnings_shadow.py:52`, and `fleet/static/dashboard.js:90`.
- Keep source isolation and visible error responses. Collector failures log warnings, status failures return an explicit error, and failed browser polls mark saved data as stale (`fleet/collector.py:23`, `fleet/web.py:73`, `fleet/web.py:99`, `fleet/static/dashboard.js:35`).

### Pre-flight and method

The container uses Python 3.12. Runtime dependencies are FastAPI, Uvicorn, and psycopg; the frontend uses native JavaScript modules. Vitest is a development dependency, and pytest searches `tests/` (`Dockerfile:1`, `requirements.txt:1`, `requirements.txt:2`, `requirements.txt:3`, `package.json:3`, `package.json:4`, `pyproject.toml:1`, `fleet/static/dashboard.js:1`).

Local command probes found `rg`, Python, Node, npm, and pytest. They did not find ruff, pylint, mypy, pyright, vulture, radon, cloc, a local Vitest executable, or the FastAPI/psycopg runtime modules. No tools or dependencies were installed. These are session observations; the dependency declarations are at `requirements.txt:1` and `package.json:4`.

Research used `rg`, numbered source reads, Python `ast`, and caller/test searches. The Python AST inventory found 25 exception handlers: 13 `Exception`, eight `(TypeError, ValueError)`, and four `ValueError`. The handler inventory below cites all 25 sites. Embedded remote scripts, `finally`, timeout suppression, JavaScript catches, and default/null branches were read separately (`fleet/watch.py:27`, `fleet/earnings_shadow.py:74`, `fleet/main.py:26`, `fleet/scheduler.py:30`, `fleet/static/dashboard.js:74`, `fleet/static/host.js:295`).

Checks used synthetic data in memory. Python ran with `-B`. For modules with unavailable dependencies, the checks compiled the source AST while excluding unavailable imports, or selected the exact functions under test. The demand/scoring check imported the actual modules. Node imported the actual dashboard module with a small fake DOM and fake fetch. Thus the results below demonstrate function and control-flow behavior, not live PostgreSQL, SSH, HTTP, or browser behavior. Relevant test boundaries are already explicit in `tests/conftest.py:35`, `tests/test_remote.py:1`, `tests/test_collector_tick.py:1`, and `tests/dashboard-harness.js:116`.

## Critical Findings

None retained at HIGH severity. The retained findings concern incorrect monitoring results and handling of malformed data. Fleet scoring is observational; provider model control is outside this service (`README.md:19`, `README.md:78`).

## Medium Findings

### defensive-001 — Old successful reads can retain a healthy badge

**Classification: ERROR-HIDING; action: NEEDS-REFACTOR.**

- **Evidence and trigger:** A failed daemon read returns `None`, and the tick skips the snapshot insert. The status query then retrieves the previous row without an age limit. `host_health()` trusts its stored `fresh` flag and can reach `_healthy()` without checking its current age (`fleet/collector.py:23`, `fleet/collector.py:108`, `fleet/queries.py:208`, `fleet/health.py:53`, `fleet/health.py:64`).
- **Observed check:** A row with `fresh=True`, `observed_at=1000`, four served requests, and no recent thrash rows returned `HEALTHY` at `now=10000`. The card band returned `STALE` for the same row with a 90-second freshness threshold (`fleet/health.py:54`, `fleet/card.py:37`, `fleet/card.py:49`).
- **Consequence:** The failed read is logged, but the API health field and dashboard badge can still claim that the daemon is fresh. `daemon_fresh` also returns the stored flag unchanged (`fleet/health.py:65`, `fleet/queries.py:386`, `fleet/queries.py:399`, `fleet/static/host.js:247`).
- **Counter-evidence and limit:** The main card already checks observation age, and the separate watchdog can alert on unreachable hosts. This finding does not claim that every outage signal is hidden (`tests/test_card.py:109`, `fleet/watch.py:49`, `fleet/watch.py:114`).
- **Smallest repair:** Calculate current freshness from the saved flag and observation age when assembling status. Reuse the age rule already present in the card, and let the existing stale/down branch use that result. Keep the collector catch and warning; do not insert an invented successful snapshot (`fleet/queries.py:374`, `fleet/card.py:30`, `fleet/health.py:55`, `fleet/health.py:68`).
- **Regression check:** A formerly fresh row must become stale/down after successful reads stop, while a recent row remains healthy. The existing health tests cover stored `fresh=False` but the aged-row assertion is in the card tests (`tests/test_health.py:26`, `tests/test_health.py:32`, `tests/test_card.py:109`).

### defensive-002 — Rejected routing rows become a successful zero-provider probe

**Classification: ERROR-HIDING; action: NEEDS-REFACTOR.**

- **Evidence and trigger:** `_routable_count()` returns `None` for a malformed numeric count. `fetch_self_route()` silently filters that row. If every row is rejected, it returns `{}`; the collector stores that as a new successful probe, and persistence converts it to the explicit zero-provider marker (`fleet/demand.py:39`, `fleet/demand.py:41`, `fleet/demand.py:59`, `fleet/collector.py:98`, `fleet/db.py:203`).
- **Observed check:** A nonempty `data` list containing one model with a nonnumeric `routable_providers` value returned `{}`. Passing that result through the actual insert function with a fake connection produced `(observed_at, "", 0)` (`fleet/demand.py:59`, `fleet/db.py:203`).
- **Consequence:** A parse failure advances routing observation time and becomes indistinguishable from a successful observation of no routable providers. The latest-probe reader returns that time and an empty count map (`fleet/db.py:86`, `fleet/routability.py:18`, `fleet/routability.py:22`).
- **Counter-evidence and limit:** A genuinely empty list must still record zero. The code already rejects a bad outer shape, and the existing row test intentionally skips malformed entries while preserving valid entries. The defect is loss of the rejected-row information when the result is treated as an authoritative probe (`fleet/demand.py:56`, `tests/test_demand.py:22`, `tests/test_demand.py:49`).
- **Smallest repair:** Reject a nonempty listing whose rows cannot be parsed. Define how partial invalid listings affect a complete routing snapshot; use the existing collector warning/skip path rather than storing failure as zero. Keep supported optional-field defaults and authenticated-request protections (`fleet/collector.py:93`, `fleet/demand.py:37`, `fleet/demand.py:18`).
- **Regression check:** Compare a genuine empty list, an all-invalid list, and a mixed list. An invalid probe must not create the successful-empty marker (`fleet/db.py:203`, `tests/test_collector_tick.py:66`).

### defensive-003 — Feed container defaults bypass validation

**Classification: ERROR-HIDING; action: NEEDS-REFACTOR.**

- **Evidence and trigger:** A capacity object with neither `data` nor `models` becomes `[]` before the list check. A supplied pricing `prices` value is not checked as a list; a mapping or string is iterated, its elements are rejected, and the result becomes an empty explicit-price map (`fleet/demand.py:65`, `fleet/demand.py:66`, `fleet/demand.py:79`, `fleet/demand.py:94`, `fleet/demand.py:95`).
- **Observed check:** An object containing only an error field returned empty capacity data and zero fallback pricing. A pricing object with a positive fallback and `prices` set to a mapping returned no explicit prices; `resolve_prices()` then applied the fallback to a configured model (`fleet/demand.py:65`, `fleet/demand.py:93`, `fleet/demand.py:95`, `fleet/demand.py:100`).
- **Consequence:** Invalid capacity containers bypass the warning path and look like no samples. Invalid explicit-price containers can become fresh fallback-based scores. If no scores result, the tick leaves EMA state unchanged; it does not fabricate fresh EMA state in that case (`fleet/collector.py:50`, `fleet/collector.py:56`, `fleet/collector.py:135`, `fleet/collector.py:136`, `fleet/collector.py:149`).
- **Counter-evidence and limit:** List-form capacity, both named capacity envelopes, optional per-model pricing, and valid fallback prices are supported. The tests reject non-object pricing and non-list capacity, but also intentionally permit malformed individual price rows to be skipped. Do not remove these supported formats based on this report (`fleet/demand.py:62`, `fleet/demand.py:98`, `tests/test_demand.py:61`, `tests/test_demand.py:67`, `tests/test_demand.py:73`).
- **Smallest repair:** Remove the implicit empty-list default for an unrecognized capacity object. If `prices` is supplied, validate its container before iterating. Raise the existing parse error so the collector logs the failure. Keep legitimate fallback-only pricing; no schema package is needed (`fleet/demand.py:65`, `fleet/demand.py:94`, `fleet/collector.py:48`).
- **Regression check:** Add cases for an unrecognized capacity object and a supplied pricing mapping/string, alongside the valid empty-list and fallback cases (`tests/test_demand.py:55`, `tests/test_demand.py:81`).

### defensive-005 — Missing attributed earnings become measured-looking zeros

**Classification: ERROR-HIDING; action: NEEDS-REFACTOR.**

- **Evidence and trigger:** The payout query includes only unambiguous identity joins. For each exposure row, `build_profile()` substitutes `{}` when there is no matching payout aggregate, then writes zero requests and zero revenue under the fixed `verified_provider_identity` attribution label. There is no evidence-availability check in this function (`fleet/earnings_shadow.py:38`, `fleet/earnings_shadow.py:47`, `fleet/earnings_shadow.py:59`, `fleet/earnings_shadow.py:64`, `fleet/earnings_shadow.py:68`).
- **Observed check:** One exposure row and no payout rows produced `paid_requests=0`, `inference_usd=0.0`, and `attribution="verified_provider_identity"`. The same absence of joined rows can occur when host identities are unavailable, not just when observed paid work is zero (`fleet/earnings_shadow.py:56`, `fleet/earnings_shadow.py:59`, `fleet/collector.py:74`, `fleet/collector.py:83`).
- **Consequence:** Unknown identity or payout evidence can be published as zero earnings. This conflicts with the documented requirement that missing evidence must not be interpreted as measured zero (`README.md:73`, `fleet/earnings_shadow.py:64`, `fleet/earnings_shadow.py:89`).
- **Counter-evidence and limit:** Zero earnings can be valid when evidence is complete. The current SQL check verifies attribution and reward exclusion with known identities; it does not establish evidence completeness when no identity joins exist. The documented consumer uses this profile in shadow mode, so no live model-control failure is asserted (`tests/check_earnings_shadow.py:12`, `tests/check_earnings_shadow.py:26`, `README.md:78`).
- **Smallest repair:** At minimum, withhold a host profile when no verified host identity exists, and log a safe diagnostic. Preserve unknown values or omit model earnings when completeness is not established. Reuse the existing identity query; do not add an evidence framework. Check the external consumer's accepted shape before changing zero values to null (`fleet/earnings_shadow.py:38`, `fleet/earnings_shadow.py:52`, `fleet/earnings_shadow.py:88`, `README.md:78`).
- **Regression check:** Distinguish unavailable identities from a known identity with a successfully observed zero-payout window. Retain base-reward exclusion and conflict handling (`fleet/earnings_shadow.py:40`, `fleet/earnings_shadow.py:43`, `tests/check_earnings_shadow.py:12`).

### defensive-006 — Malformed successful responses replace the dashboard's good data

**Classification: ERROR-HIDING; action: NEEDS-REFACTOR.**

- **Evidence and trigger:** `loadStatus()` checks HTTP status but not the JSON envelope. `applyStatus()` replaces `lastStatus`, advances `lastGoodAt`, and clears `pollError` before rendering. Missing hosts are then treated as empty by the render helpers (`fleet/static/dashboard.js:90`, `fleet/static/dashboard.js:98`, `fleet/static/ui.js:15`, `fleet/static/host.js:292`).
- **Observed check:** After a good response, HTTP 200 `{}` erased host HTML, removed the stale flag, and displayed `0 hosts · refreshed`. HTTP 200 `null` replaced the cache without rendering; a later network error could not use the lost cache to mark the still-visible host HTML as stale (`fleet/static/dashboard.js:33`, `fleet/static/dashboard.js:71`, `fleet/static/dashboard.js:98`, `fleet/static/dashboard.js:107`, `fleet/static/dashboard.js:123`).
- **Consequence:** A malformed successful response can hide the previous valid view or leave visible data without its age warning. The existing tests explicitly accept a null payload and the empty-object zero-host result (`tests/dashboard-poll.test.js:108`, `tests/dashboard-poll.test.js:190`).
- **Counter-evidence and limit:** Ordinary HTTP/network failures already retain good data and show an escaped error. The backend normally produces a `hosts` array on both its success and handled-failure paths. This finding applies to a malformed response, not every successful poll (`tests/dashboard-poll.test.js:83`, `fleet/web.py:75`, `fleet/web.py:80`).
- **Smallest repair:** Before updating the cache, require a non-null object with an array-valued `hosts`. Reject a malformed envelope through the existing poll-error path. Preserve the refresh ordering, error escaping, sanitization, and focus restoration (`fleet/static/dashboard.js:96`, `fleet/static/dashboard.js:104`, `fleet/static/dashboard.js:44`, `fleet/static/dashboard.js:73`).
- **Regression check:** Good response followed by `{}`, `null`, or a wrong-type `hosts` must retain good data and display the existing stale warning. Keep the late-response and abort controls (`tests/dashboard-poll.test.js:83`, `tests/dashboard-poll.test.js:127`, `tests/dashboard-poll.test.js:156`).

## Low / Debatable Findings

### defensive-004 — Numeric guards miss overflow and can discard unrelated data

**Classification: NEEDS-REFACTOR; severity LOW because the demonstrated inputs are abnormal.**

- **Evidence:** Optional number converters catch `TypeError` and `ValueError`, but not `OverflowError`. The same exception list appears in capacity-count and per-row feed parsing (`fleet/remote.py:180`, `fleet/remote.py:203`, `fleet/scoring.py:24`, `fleet/scoring.py:45`, `fleet/demand.py:41`, `fleet/demand.py:83`).
- **Observed check:** A widget `cpuUsage` integer of `10**400` caused `float()` to raise. A manager streak parsed from the valid JSON numeric literal `1e400` caused `int()` to raise. Each escaped the optional parser and failed the entire `fetch_daemon_state()` call. Capacity counts and optional throughput values had the same overflow behavior (`fleet/remote.py:90`, `fleet/remote.py:101`, `fleet/remote.py:179`, `fleet/remote.py:202`, `fleet/scoring.py:43`, `fleet/scoring.py:54`).
- **Consequence and limit:** The collector then logs and skips that daemon observation or capacity feed. The background loop survives. Existing tests cover invalid strings and nonfinite floats, so this is a missing numeric error case, not grounds to delete the boundary guards (`fleet/collector.py:23`, `fleet/collector.py:50`, `tests/test_remote.py:182`, `tests/test_scoring.py:53`).
- **Smallest repair:** Add `OverflowError` to the relevant conversion catches, preserving their existing None/skip behavior and finite-number checks. Retain the outer logging catches. Reuse the current helpers; no generic parsing layer is needed (`fleet/remote.py:197`, `fleet/scoring.py:16`, `fleet/demand.py:77`).
- **Regression check:** A malformed optional value must not discard a valid daemon state or valid neighboring feed rows. Verify the huge-integer and exponent cases as well as existing ordinary malformed-value cases (`tests/test_remote.py:125`, `tests/test_remote.py:198`, `tests/test_scoring.py:19`).

## Recommendations

1. Fix current-freshness handling and failed-routing sample semantics first. Reuse the existing stale/down result and warning/skip paths. Do not remove I/O catches (`fleet/health.py:55`, `fleet/health.py:68`, `fleet/collector.py:93`, `fleet/card.py:30`).
2. Prevent unknown earnings evidence from being labeled as measured zero. Confirm the existing external profile consumer's contract before a null/omission change (`fleet/earnings_shadow.py:59`, `README.md:73`, `README.md:78`).
3. Add small native container checks at the feed and browser boundaries. Keep supported alternate formats, legitimate empty results, and the existing error UI (`fleet/demand.py:62`, `fleet/demand.py:87`, `fleet/static/dashboard.js:90`, `fleet/static/dashboard.js:104`).
4. Extend existing numeric exception tuples for overflow. Leave the internal card timestamp fallback outside the repair scope unless its supported input contract changes. These need local edits, not a shared error framework (`fleet/remote.py:180`, `fleet/scoring.py:24`, `fleet/card.py:38`).
5. Preserve credential-safe diagnostics, authenticated redirect refusal, inventory bounds, markup escaping/sanitization, and keyboard-focus handling during any later repair (`fleet/collector.py:83`, `fleet/demand.py:18`, `fleet/remote.py:120`, `fleet/remote.py:136`, `fleet/static/ui.js:8`, `fleet/static/dashboard.js:44`, `fleet/static/ui.js:130`, `fleet/static/host.js:231`).

### Exception and suppression inventory

The following is a KEEP/REVIEW inventory, not additional findings. Each Python exception-handler site and each JavaScript catch is included. Findings above take precedence where named.

| Sites | Classification | Purpose and removal risk |
|---|---|---|
| `fleet/collector.py:23`, `fleet/collector.py:32` | LEGITIMATE | Log failed daemon/inventory I/O and return unknown. Removing catches can stop the remainder of a tick. Preserve unknown versus verified empty inventory; fix freshness downstream under defensive-001. |
| `fleet/collector.py:50`, `fleet/collector.py:56` | LEGITIMATE | Log independent feed failures. No-score ticks preserve EMA age (`fleet/collector.py:136`). Fix malformed success values under defensive-003. |
| `fleet/collector.py:67`, `fleet/collector.py:95` | LEGITIMATE | Log and skip failed ledger/probe reads. Removing these catches would lose independent ingestion work. |
| `fleet/collector.py:83` | LEGITIMATE | Identity refresh is optional; warning deliberately excludes authenticated response details. Do not add raw response logging. |
| `fleet/scheduler.py:27`, `fleet/watch.py:144`, `fleet/earnings_shadow.py:100` | LEGITIMATE | Log tick failure and continue periodic work. These are service-loop boundaries, not silent successful returns. |
| `fleet/scheduler.py:30`, `fleet/watch.py:146`, `fleet/earnings_shadow.py:102` | LEGITIMATE | Suppress only the expected timer expiration while waiting for stop. Removing suppression would terminate normal polling. |
| `fleet/web.py:73`, `fleet/web.py:107` | LEGITIMATE | Log failures and return explicit host errors (`fleet/web.py:99`). Preserve per-host isolation. |
| `fleet/watch.py:114` | LEGITIMATE | Failed SSH/JSON/condition reads become unknown with a warning. Existing manager/switch alerts remain unresolved (`fleet/watch.py:49`, `fleet/watch.py:69`). |
| `fleet/watch.py:30`, `fleet/watch.py:33` | LEGITIMATE | Embedded probe converts unreadable/invalid state documents to empty objects; their timestamps then become stale (`fleet/watch.py:40`, `fleet/watch.py:42`). Keep boundary handling. |
| `fleet/remote.py:131` | LEGITIMATE | Inventory parse failure becomes unknown, then raises for the collector to log (`fleet/remote.py:110`). Do not turn it into an empty inventory. |
| `fleet/remote.py:157`, `fleet/remote.py:192` | LEGITIMATE isolation; diagnostic limit below | Missing/malformed optional manager/widget data must not fail the daemon read. The manager result still uses its independent process observation (`fleet/remote.py:154`, `fleet/remote.py:160`). |
| `fleet/remote.py:180`, `fleet/remote.py:203` | NEEDS-REFACTOR | Keep optional numeric guards; add the missing overflow case under defensive-004. |
| `fleet/demand.py:41`, `fleet/demand.py:83` | NEEDS-REFACTOR | Keep per-row boundary parsing. Preserve failure information at the containing feed boundary under defensive-002/003 and handle overflow under defensive-004. |
| `fleet/scoring.py:24`, `fleet/scoring.py:45` | LEGITIMATE, with defensive-004 | Skip invalid counts and omit invalid optional throughput. Removing guards lets one bad field discard valid feed data. |
| `fleet/config.py:34` | LEGITIMATE | Converts invalid numeric settings to a named configuration error, then rejects nonfinite/out-of-range values (`fleet/config.py:36`). |
| `fleet/card.py:38` | ERROR-HIDING / REVIEW | Invalid observation time is treated as fresh; see the internal timestamp contract note below. No normal DB path was established. |
| `fleet/card.py:84` | LEGITIMATE conservative fallback | Bad load-error age becomes non-recent, while the model and error message remain visible (`fleet/card.py:86`, `fleet/static/host.js:59`). Redundant for normal typed DB values, but not a supported deletion finding. |
| `fleet/main.py:26`, `fleet/earnings_shadow.py:78`, `fleet/earnings_shadow.py:82` | LEGITIMATE `finally` | Close the pool on exit and remove the temporary profile file after atomic replacement. Neither suppresses the primary failure. |
| `fleet/static/dashboard.js:74` | LEGITIMATE | Displays an escaped render error; it does not claim a successful render. Keep focus restoration within the protected render path (`fleet/static/dashboard.js:73`). |
| `fleet/static/dashboard.js:120` | LEGITIMATE, with defensive-006 | Network/HTTP errors keep good data and expose its age. Fix validation before the good-data cache update. |
| `fleet/static/host.js:295` | LEGITIMATE | One failed host render becomes a visible escaped error card, preserving other cards (`fleet/static/host.js:255`). |

### Other default/null patterns reviewed

These grouped sites account for the remaining meaningful fallback patterns. Ordinary dictionary lookups are grouped by function purpose; a `.get()` by itself is not a defect.

| Sites | Classification and decision |
|---|---|
| `fleet/remote.py:24`, `fleet/remote.py:25`, `fleet/remote.py:28`, `fleet/remote.py:149` | LEGITIMATE optional-source isolation and document padding. Do not remove shell fallbacks and make missing widget/manager data fatal to the daemon read. See the diagnostic limit below. |
| `fleet/remote.py:57`, `fleet/remote.py:72`, `fleet/remote.py:81`, `fleet/remote.py:82`, `fleet/remote.py:86` | LEGITIMATE selection of SSH failure detail and defaults for absent external daemon counters/timestamps. Required numeric conversion failures reach the collector warning; optional conversion gaps are defensive-004. |
| `fleet/remote.py:94`, `fleet/remote.py:218`, `fleet/remote.py:224`, `fleet/remote.py:242`, `fleet/remote.py:249`, `fleet/remote.py:254`, `fleet/remote.py:258`, `fleet/remote.py:268` | LEGITIMATE optional widget GPU fallback, nullable fields, malformed-section guards, and nullable ledger-field normalization. Keep input handling; no live producer-contract change was established. |
| `fleet/collector.py:41`, `fleet/collector.py:74`, `fleet/collector.py:91`, `fleet/collector.py:108`, `fleet/collector.py:128`, `fleet/collector.py:136`, `fleet/collector.py:146` | LEGITIMATE gating and empty-work handling. Unknown inventory retains the configured allow-list; known empty inventory skips scoring (`tests/test_inventory.py:51`, `tests/test_inventory.py:97`). |
| `fleet/config.py:33`, `fleet/config.py:67`, `fleet/config.py:73`, `fleet/config.py:77`, `fleet/config.py:95`, `fleet/config.py:98`, `fleet/config.py:126` | LEGITIMATE configured defaults and optional settings. Duplicate identities and missing required configuration fail explicitly (`fleet/config.py:88`, `fleet/config.py:129`). Empty mounted-secret behavior is flagged below, not changed here. |
| `fleet/demand.py:27`, `fleet/demand.py:35`, `fleet/demand.py:38`, `fleet/demand.py:82`, `fleet/demand.py:100`, `fleet/demand.py:105`, `fleet/demand.py:110`, `fleet/demand.py:118`, `fleet/demand.py:121` | LEGITIMATE optional headers, row validation, fallback price, and identity filters in principle. Keep them; defensive-002/003 address where rejection is mistaken for a complete successful feed. |
| `fleet/scoring.py:19`, `fleet/scoring.py:37`, `fleet/scoring.py:39`, `fleet/scoring.py:43`, `fleet/scoring.py:49`, `fleet/scoring.py:66` | LEGITIMATE external-row checks, supported field aliases, divide-by-zero guard, and unit default weight. Retain these when adding overflow handling. |
| `fleet/queries.py:38`, `fleet/queries.py:42`, `fleet/queries.py:56`, `fleet/queries.py:69`, `fleet/queries.py:74`, `fleet/queries.py:86`, `fleet/queries.py:109`, `fleet/queries.py:133`, `fleet/queries.py:152`, `fleet/queries.py:186`, `fleet/queries.py:203` | LEGITIMATE optional manager/demand fields, freshness filtering, sorting defaults, and display-only ranking. Eligibility remains separate from display fallback (`fleet/queries.py:177`). |
| `fleet/queries.py:281`, `fleet/queries.py:302`, `fleet/queries.py:306`, `fleet/queries.py:317`, `fleet/queries.py:332`, `fleet/queries.py:335`, `fleet/queries.py:341` | LEGITIMATE empty-window/aggregate guards and accumulation defaults. The `fresh=True` fallback in the pure serving helper is unnecessary for its current SQL rows, but that query explicitly selects `fresh`; no reachable missing-field failure was established (`fleet/queries.py:248`, `fleet/db.py:58`). |
| `fleet/db.py:152`, `fleet/db.py:156`, `fleet/db.py:196`, `fleet/db.py:198`, `fleet/db.py:203`, `fleet/db.py:211`, `fleet/db.py:227`, `fleet/db.py:234`, `fleet/db.py:254` | LEGITIMATE nullable fields, empty batch guards, initial cursor/EMA values, and successful-empty probe marker. Keep persistence semantics; fix invalid input before that marker under defensive-002. |
| `fleet/card.py:25`, `fleet/card.py:46`, `fleet/card.py:69`, `fleet/card.py:79`, `fleet/card.py:93`, `fleet/card.py:119`, `fleet/card.py:130` | LEGITIMATE absent-host, nullable metric, and absent-error handling. The success-on-invalid-time exception is flagged below; no normal DB path was established. |
| `fleet/health.py:50`, `fleet/health.py:64`, `fleet/health.py:70`, `fleet/health.py:81`, `fleet/health.py:95`, `fleet/health.py:131`, `fleet/health.py:146`, `fleet/health.py:157` | LEGITIMATE missing-host, optional field, and state-transition guards in principle. Some empty-row fallbacks exceed the SQL aggregate contract; no independent runtime defect was retained. Current freshness is defensive-001. |
| `fleet/routability.py:19`, `fleet/routability.py:46`, `fleet/routability.py:82`, `fleet/routability.py:108`, `fleet/routability.py:113`, `fleet/routability.py:130`, `fleet/routability.py:147`, `fleet/routability.py:150` | LEGITIMATE absent history, ambiguous alias, insufficient sample, and unknown inventory handling. The UI exposes probe time, limiting claims that an old routing view is silently current (`fleet/static/host.js:201`). |
| `fleet/attribution.py:60`, `fleet/attribution.py:72`, `fleet/attribution.py:76`, `fleet/attribution.py:80`, `fleet/attribution.py:83`, `fleet/attribution.py:96`, `fleet/attribution.py:99` | LEGITIMATE accumulation defaults and ambiguity rejection. Keep conflicting provider identities unassigned. |
| `fleet/hourly.py:47`, `fleet/hourly.py:54`, `fleet/hourly.py:63`, `fleet/hourly.py:73`, `fleet/hourly.py:94`, `fleet/hourly.py:112` | LEGITIMATE bounded label overflow, zero elapsed time, empty bucket, and failed-host-panel guards. No catch removal recommended. |
| `fleet/watch.py:49`, `fleet/watch.py:54`, `fleet/watch.py:69`, `fleet/watch.py:74`, `fleet/watch.py:80`, `fleet/watch.py:99`, `fleet/watch.py:120`, `fleet/watch.py:130`, `fleet/watch.py:138` | LEGITIMATE unknown-state preservation, grace periods, recovery delivery retention, and optional notification gate. Preserve existing alerts through failed reads. |
| `fleet/earnings_shadow.py:63`, `fleet/earnings_shadow.py:73`, `fleet/earnings_shadow.py:95` | LEGITIMATE nullable pressure, nonfinite JSON rejection, and optional publisher gate. Earnings zero defaults are defensive-005. |
| `fleet/web.py:87`, `fleet/web.py:108` | UNNECESSARY for a valid `Config`, whose fields are required (`fleet/config.py:47`, `fleet/config.py:49`), but harmless within error reporting. Keep unless changing that path for a concrete reason; no separate issue. |
| `fleet/static/ui.js:9`, `fleet/static/ui.js:15`, `fleet/static/ui.js:17`, `fleet/static/ui.js:19`, `fleet/static/ui.js:33`, `fleet/static/ui.js:64`, `fleet/static/ui.js:78`, `fleet/static/ui.js:83`, `fleet/static/ui.js:87`, `fleet/static/ui.js:101`, `fleet/static/ui.js:109`, `fleet/static/ui.js:113`, `fleet/static/ui.js:121`, `fleet/static/ui.js:131` | LEGITIMATE optional display/focus targets and best-effort focus restoration. Deep optional chaining is confined to DOM/optional data handling; no typed non-null contract justifies bulk deletion. Missing top-level status data is defensive-006. |
| `fleet/static/host.js:25`, `fleet/static/host.js:32`, `fleet/static/host.js:41`, `fleet/static/host.js:46`, `fleet/static/host.js:50`, `fleet/static/host.js:60`, `fleet/static/host.js:70`, `fleet/static/host.js:83`, `fleet/static/host.js:92`, `fleet/static/host.js:122`, `fleet/static/host.js:134`, `fleet/static/host.js:148`, `fleet/static/host.js:152`, `fleet/static/host.js:172`, `fleet/static/host.js:182`, `fleet/static/host.js:190`, `fleet/static/host.js:223`, `fleet/static/host.js:238`, `fleet/static/host.js:247`, `fleet/static/host.js:256`, `fleet/static/host.js:266`, `fleet/static/host.js:276` | LEGITIMATE absent-data display guards in principle. The default HEALTHY badge for an omitted health block is a contract concern, not an additional reachable backend finding: normal status always supplies health, and error rows render an error card (`fleet/queries.py:399`, `fleet/static/host.js:282`). Preserve unknown inventory display and accessible controls. |
| `fleet/static/hourly.js:53`, `fleet/static/hourly.js:56`, `fleet/static/hourly.js:59`, `fleet/static/hourly.js:74`, `fleet/static/dashboard.js:17`, `fleet/static/dashboard.js:33`, `fleet/static/dashboard.js:82`, `fleet/static/dashboard.js:105` | LEGITIMATE absent panel/control, unknown legend entry, and obsolete/aborted poll handling. Validate the envelope under defensive-006 before these presentation defaults run. |

## Out of Scope / Flagged for Review

- **Internal timestamp contract, excluded from findings:** A direct helper check with a malformed observation time returned `EARNING`; the catch treats conversion failure as non-stale, and a test requires that result. Normal DB rows require a numeric observation time. No production path to the malformed value was established, so no removal is recommended (`fleet/card.py:34`, `fleet/card.py:38`, `fleet/card.py:52`, `tests/test_card.py:119`, `fleet/db.py:54`, `fleet/queries.py:208`).
- **Optional-source diagnostics:** `_STATE_COMMAND` suppresses widget/manager command failures, and `_run_ssh()` returns stdout without surfacing stderr when the compound command succeeds. Optional parsers then turn malformed data into absence. Keep isolation, but consider a safe diagnostic if operators need to distinguish an absent component from a broken one. No additional severity is assigned without that requirement (`fleet/remote.py:24`, `fleet/remote.py:25`, `fleet/remote.py:55`, `fleet/remote.py:59`, `fleet/remote.py:157`, `fleet/remote.py:192`).
- **Empty secret file:** `_secret_file()` returns `None` for an explicitly selected empty file. An API key absence then skips authenticated ingestion. Whether this must be a startup error depends on deployment policy; no file contents or live credentials were read (`fleet/config.py:73`, `fleet/config.py:114`, `fleet/collector.py:74`, `fleet/collector.py:91`).
- **External earnings consumer:** This worktree contains the publisher and documents the manager consumer, but not that consumer implementation. Null/omission compatibility and live-control effects were not asserted (`fleet/earnings_shadow.py:71`, `README.md:78`).
- **Database and network checks:** No PostgreSQL, SSH, authenticated HTTP, remote publishing, or alert delivery was run. In particular, the `check_*.py` scripts that open configured databases were read but not executed (`tests/check_earnings_shadow.py:6`, `fleet/remote.py:55`, `fleet/watch.py:127`).
- **Full test suite:** Not run because application dependencies were unavailable locally. No dependency installation or test-generated files were permitted for this report-only task. The synthetic checks do not validate PostgreSQL SQL semantics or real browser focus behavior (`requirements.txt:1`, `tests/conftest.py:35`, `tests/dashboard-harness.js:116`).
- **Security/accessibility:** This is not a separate security or accessibility audit. Existing boundary protections and focus/accessibility behavior are KEEP constraints, not cleanup candidates (`fleet/demand.py:18`, `fleet/config.py:70`, `fleet/static/dashboard.js:44`, `fleet/static/ui.js:130`, `fleet/static/dashboard.html:131`, `fleet/static/host.js:231`).
- **Verification status:** In-memory reproduction and citation checks support the analysis claims. They are not the separate independent verification stage. All JSON entries remain `verified: false`; the internal timestamp concern was excluded from findings because normal DB reachability was not established (`fleet/db.py:54`, `tests/test_card.py:119`).

## Machine-Readable Findings

```json
{
  "findings": [
    {
      "id": "defensive-001",
      "file": "fleet/health.py",
      "line": 53,
      "severity": "MEDIUM",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "ERROR-HIDING",
      "detail": "After daemon reads fail, host_health can return HEALTHY from an old row whose stored fresh flag remains true; calculate current observation freshness before this success fallback.",
      "evidence": [
        "fleet/collector.py:108",
        "fleet/queries.py:208",
        "fleet/health.py:53",
        "fleet/health.py:64",
        "fleet/card.py:37"
      ],
      "verified": false
    },
    {
      "id": "defensive-002",
      "file": "fleet/demand.py",
      "line": 59,
      "severity": "MEDIUM",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "ERROR-HIDING",
      "detail": "An all-invalid nonempty self-route listing becomes an empty count map and is stored as a new successful zero-provider probe; preserve parse failure and use the collector warning/skip path.",
      "evidence": [
        "fleet/demand.py:41",
        "fleet/demand.py:59",
        "fleet/collector.py:98",
        "fleet/db.py:203"
      ],
      "verified": false
    },
    {
      "id": "defensive-003",
      "file": "fleet/demand.py",
      "line": 65,
      "severity": "MEDIUM",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "ERROR-HIDING",
      "detail": "An unrecognized capacity object defaults to an empty list, and a supplied non-list prices container can yield fallback pricing; validate these containers before applying legitimate empty/default semantics.",
      "evidence": [
        "fleet/demand.py:65",
        "fleet/demand.py:79",
        "fleet/demand.py:94",
        "fleet/demand.py:100",
        "fleet/collector.py:50"
      ],
      "verified": false
    },
    {
      "id": "defensive-004",
      "file": "fleet/remote.py",
      "line": 180,
      "severity": "LOW",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "NEEDS-REFACTOR",
      "detail": "Numeric conversion guards omit OverflowError, so an oversized optional float or nonfinite integer can fail the entire daemon read or capacity feed; extend the existing local conversion catches.",
      "evidence": [
        "fleet/remote.py:180",
        "fleet/remote.py:203",
        "fleet/scoring.py:24",
        "fleet/scoring.py:45",
        "fleet/demand.py:41",
        "fleet/demand.py:83"
      ],
      "verified": false
    },
    {
      "id": "defensive-005",
      "file": "fleet/earnings_shadow.py",
      "line": 59,
      "severity": "MEDIUM",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "ERROR-HIDING",
      "detail": "Exposure without joined payout evidence becomes zero paid requests and revenue under a verified_provider_identity label; distinguish missing identity/evidence from measured zero before publishing.",
      "evidence": [
        "fleet/earnings_shadow.py:38",
        "fleet/earnings_shadow.py:47",
        "fleet/earnings_shadow.py:59",
        "fleet/earnings_shadow.py:64",
        "fleet/earnings_shadow.py:68",
        "README.md:73"
      ],
      "verified": false
    },
    {
      "id": "defensive-006",
      "file": "fleet/static/dashboard.js",
      "line": 98,
      "severity": "MEDIUM",
      "confidence": "CERTAIN",
      "recommendation": "NEEDS-REFACTOR",
      "classification": "ERROR-HIDING",
      "detail": "A malformed HTTP 200 JSON envelope replaces lastStatus and resets freshness before validation; require a non-null object with a hosts array and route invalid responses through the existing poll-error handling.",
      "evidence": [
        "fleet/static/dashboard.js:90",
        "fleet/static/dashboard.js:98",
        "fleet/static/dashboard.js:107",
        "fleet/static/dashboard.js:123",
        "tests/dashboard-poll.test.js:190"
      ],
      "verified": false
    }
  ]
}
```
