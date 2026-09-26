Ponytail full intensity: use the YAGNI ladder; prefer existing code, standard library, and the smallest useful change. Preserve trust-boundary validation, security, and accessibility.

# LOC Limits Assessment

## Executive Summary

- The scan measured nonblank, noncomment source lines in Python and JavaScript, and checked the dashboard HTML by physical line count. Python measurements used `tokenize` and `ast`; JavaScript measurements used the installed Acorn tokenizer and parser. Function counts include the definition and body. Test suite callbacks include their nested test cases. The repository uses Python and JavaScript: `pyproject.toml:1`, `package.json:3`, `fleet/static/dashboard.html:151`.
- Total size signals: **3**. Severity: **HIGH=0, MEDIUM=1, LOW=2**. These are one production file, one test file, and one individual test callback: `fleet/queries.py:400`, `tests/dashboard-view.test.js:350`, `tests/dashboard-host-edges.test.js:53`.
- Priorities: (1) split serving history from dashboard queries only when that logic next needs work (`fleet/queries.py:248`); (2) make the broad host card test more focused when it next changes (`tests/dashboard-host-edges.test.js:53`); (3) keep the larger view test grouped by behavior unless a real maintenance problem appears (`tests/dashboard-view.test.js:44`, `tests/dashboard-view.test.js:321`).
- Scope of possible work: three existing files. No LOC reduction is assumed. Moving the serving section would relocate 107 code lines; a size limit alone does not justify that churn: `fleet/queries.py:248`, `fleet/queries.py:364`, `tests/dashboard-view.test.js:350`, `tests/dashboard-host-edges.test.js:53`.

### Files over 300 code LOC

| File | Code LOC / physical LOC | Concerns | Recommendation |
| --- | ---: | ---: | --- |
| `fleet/queries.py:400` | 345 / 400 | 4: demand, earnings, serving history, status assembly (`fleet/queries.py:28`, `fleet/queries.py:215`, `fleet/queries.py:248`, `fleet/queries.py:374`) | **SPLIT**, conditional on work in serving history. |
| `tests/dashboard-view.test.js:350` | 318 / 350 | 5 test groups (`tests/dashboard-view.test.js:44`, `tests/dashboard-view.test.js:73`, `tests/dashboard-view.test.js:181`, `tests/dashboard-view.test.js:221`, `tests/dashboard-view.test.js:321`) | **EXEMPT** as a test file; split only by behavior if navigation becomes difficult. |

### Functions and callbacks over 50 code LOC

| Function or callback | Code LOC | Recommendation |
| --- | ---: | --- |
| `describe("host card edges")`, `tests/dashboard-host-edges.test.js:40` | 214 | **EXEMPT**: suite container includes child tests. |
| `describe("dashboard poll and redraw")`, `tests/dashboard-poll.test.js:17` | 205 | **EXEMPT**: suite container includes child tests. |
| `describe("no placeholder chrome")`, `tests/dashboard-view.test.js:73` | 101 | **EXEMPT**: suite container includes child tests. |
| `describe("proposed-action indicator")`, `tests/dashboard-view.test.js:221` | 89 | **EXEMPT**: suite container includes child tests. |
| `describe("focus and restore edges")`, `tests/dashboard-refresh.test.js:135` | 67 | **EXEMPT**: suite container includes child tests. |
| `describe("hourly job rendering")`, `tests/hourly.test.js:5` | 61 | **EXEMPT**: suite container includes child tests. |
| `it("shows LIVE KEEP, ages, empty chips, idle-last serving, inactive slots, and measured switch cost")`, `tests/dashboard-host-edges.test.js:53` | 58 | **DECOMPOSE** into focused cases in the same file when touched. |

The six `describe` counts include the nested `it` callbacks, so they do not measure one unit of application logic: `tests/dashboard-host-edges.test.js:40`, `tests/dashboard-poll.test.js:17`, `tests/dashboard-view.test.js:73`, `tests/dashboard-view.test.js:221`, `tests/dashboard-refresh.test.js:135`, `tests/hourly.test.js:5`.

## Critical Findings

None. The production code above the file limit is split into short named functions, including the serving reduction and status assembly: `fleet/queries.py:279`, `fleet/queries.py:288`, `fleet/queries.py:347`, `fleet/queries.py:374`.

## Medium Findings

### loc-001 — Dashboard query module crosses the file limit

`fleet/queries.py` has **345 code LOC** and **400 physical LOC**. It combines live demand ranking (`fleet/queries.py:28`, `fleet/queries.py:177`), payout reads (`fleet/queries.py:215`, `fleet/queries.py:241`), serving window SQL and reduction (`fleet/queries.py:248`, `fleet/queries.py:347`), and API status assembly (`fleet/queries.py:374`). This is a maintenance boundary, not an observed defect. **SPLIT** the serving section only when a serving change gives the move a concrete benefit. The serving block has 107 code LOC and a clear public entry point at `fleet/queries.py:347`; no new dependency is needed (`fleet/queries.py:8`).

The move has test and API risk: tests import private serving reducers from `fleet.queries` (`tests/test_queries.py:4`) and read its serving constants (`tests/test_queries.py:91`, `tests/test_queries.py:117`). `build_status` also calls `serving_percentages` (`fleet/queries.py:392`). Preserve those contracts or update the callers in the same change. Keep freshness and outage checks intact (`fleet/queries.py:296`, `fleet/queries.py:302`).

## Low / Debatable Findings

### loc-002 — View test file crosses the file limit

`tests/dashboard-view.test.js` has **318 code LOC** and **350 physical LOC**. Its cases are already grouped around bands, removed UI, malformed hosts, proposed actions, and demand merge (`tests/dashboard-view.test.js:44`, `tests/dashboard-view.test.js:73`, `tests/dashboard-view.test.js:181`, `tests/dashboard-view.test.js:221`, `tests/dashboard-view.test.js:321`). **EXEMPT** it from a size-only split. A future test move should keep escaping checks (`tests/dashboard-view.test.js:133`, `tests/dashboard-view.test.js:210`, `tests/dashboard-view.test.js:279`) and accessibility checks (`tests/dashboard-view.test.js:243`, `tests/dashboard-view.test.js:305`).

### loc-003 — One host card test checks many independent outputs

The `it` callback at `tests/dashboard-host-edges.test.js:53` spans **58 code LOC**. One rendered card is checked for mode, ages, GPU data, serving, slots, trust, and payouts (`tests/dashboard-host-edges.test.js:81`, `tests/dashboard-host-edges.test.js:89`, `tests/dashboard-host-edges.test.js:94`, `tests/dashboard-host-edges.test.js:101`, `tests/dashboard-host-edges.test.js:109`). **DECOMPOSE** it into a few focused cases in the same file when editing those checks. Reuse the existing host fixture (`tests/dashboard-host-edges.test.js:7`) without adding a helper or module.

## Recommendations

1. Keep current production behavior now. On the next serving change, put `SERVING_WINDOWS`, serving SQL, reducers, and `serving_percentages` in a focused `fleet/serving.py`; keep demand, earnings, and status assembly in `fleet/queries.py` (`fleet/queries.py:21`, `fleet/queries.py:248`, `fleet/queries.py:347`, `fleet/queries.py:374`). Preserve `queries.serving_percentages` for its current caller and update direct test imports as needed (`fleet/queries.py:392`, `tests/test_queries.py:4`).
2. If the broad host card test fails or changes, divide its existing assertions by rendered section within `tests/dashboard-host-edges.test.js` (`tests/dashboard-host-edges.test.js:53`, `tests/dashboard-host-edges.test.js:81`, `tests/dashboard-host-edges.test.js:101`).
3. Keep test suite containers and the view test file as they are while their behavior groups remain clear (`tests/dashboard-view.test.js:44`, `tests/dashboard-view.test.js:321`, `tests/hourly.test.js:5`).

## Out of Scope / Flagged for Review

- `tests/test_queries.py` has 292 code LOC despite 368 physical lines, so blank and comment lines keep it below the stated limit (`tests/test_queries.py:368`). `fleet/static/host.js` has 273 code LOC and 299 physical lines (`fleet/static/host.js:299`). Neither needs a size-only split.
- `fleet/db.py` has a long embedded schema string beginning at `fleet/db.py:16`, but its file is below the 300 code LOC limit (`fleet/db.py:261`). A schema redesign is outside this assessment.
- The dashboard HTML is 153 physical lines and loads its JavaScript as a separate module (`fleet/static/dashboard.html:151`, `fleet/static/dashboard.html:153`). No HTML size violation was found.

## Machine-Readable Findings

```json
{"findings": [
  {"id": "loc-001", "file": "fleet/queries.py", "line": 248, "severity": "MEDIUM", "confidence": "LIKELY", "recommendation": "SPLIT", "detail": "345 code LOC cover four dashboard read concerns; move the 107-code-LOC serving section to a focused module when serving logic next changes.", "verified": false},
  {"id": "loc-002", "file": "tests/dashboard-view.test.js", "line": 44, "severity": "LOW", "confidence": "CERTAIN", "recommendation": "EXEMPT", "detail": "The test file has 318 code LOC but already groups related behavior; do not split solely to meet the file limit.", "verified": false},
  {"id": "loc-003", "file": "tests/dashboard-host-edges.test.js", "line": 53, "severity": "LOW", "confidence": "LIKELY", "recommendation": "DECOMPOSE", "detail": "A 58-code-LOC test callback checks several rendered sections; split it into focused cases in the same file when touched.", "verified": false}
]}
```
