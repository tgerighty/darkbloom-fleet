# `/api/status` bottlenecks

Base: `c81307d2162f9d0d0d9818901214e2ef0f2b8821` (after #29). This is a read-only code-path profile. No production code changed.

## Timing evidence

- Eight GETs to `https://darkbloom.nxio.ai/api/status` returned HTTP 302 to Cloudflare Access. Total time was 77–270 ms. These requests did not reach FastAPI.
- One GET to `http://127.0.0.1:8080/api/status` returned HTTP 401 in 5.3 ms. It did not reach the route.
- This shell has no `DATABASE_URL` and no local Fleet database. I could not measure route stages, database query time, pool wait, JSON size, or serialization time. Do not use the redirect times as the app baseline.

## Ranked findings

| Rank | Finding | Evidence | Smallest next step |
|---|---|---|---|
| 1 | **Full-history payout attribution has the highest static scaling risk; runtime cost is unknown.** `_VOTES_SQL` reads payout identities with no time bound, crosses each payout with each daemon host, then seeks the previous and next snapshot with two lateral queries. This runs once per request; it is not a host-row N+1. | `fleet/attribution.py:24-43,88-93`; shared call path: `fleet/queries.py:387-391`, `fleet/web.py:73`. This shared call existed before #29. | Run `EXPLAIN (ANALYZE, BUFFERS)` on a read-only database snapshot. Keep the full-history semantics unless evidence supports a safe incremental attribution store. |
| 2 | **`unattributed_recent` repeats the same account-wide query for every host row.** Each call selects the same latest 50 unique payouts and compares them with the same attribution map. | `fleet/queries.py:394-419`; `fleet/attribution.py:104-120`; host rows run in `fleet/web.py:80-84`. | Compute this value once with the other shared status data and pass the integer to each row. |
| 3 | **Every host row reads lifetime serving history.** `serving_percentages` runs one 30-day query and a separate lifetime `LEAD` query. The lifetime query reads all snapshots for that host on every status poll. | `fleet/queries.py:260-281,349-366`; called once per row at `fleet/queries.py:412`. | Measure the lifetime query on a snapshot first. Preserve the current lifetime result unless the query plan shows a need for an incremental aggregate. |
| 4 | **Host rows run sequentially after #29.** The handler awaits one `to_thread` build before it starts the next. This makes row-build latency additive. #29 removed the prior `asyncio.gather` across all displayed hosts, so there is no current host-level gather fan-out. A common fresh-host path with a started daemon issues about 15 SQL statements across 13 pool checkouts; stale-host health checks can add more. This count comes from the call graph, not a live trace. | `fleet/web.py:80-84`; #29 changed this block from `asyncio.gather` to a sequential list; `fleet/queries.py:394-419`; `fleet/routability.py:120-152`; `fleet/health.py:51-63,115-124`; `tests/test_web_main.py:213-232`. | First remove repeated shared queries. Add bounded host concurrency only if a stage profile shows row builds dominate and pool-wait data leaves capacity. The pool max is four (`fleet/db.py:135-136`); background tasks also use this pool (`fleet/web.py:43-50`). |
| 5 | **JSON serialization remains unmeasured.** `response_model=None` avoids response-model validation, but FastAPI must still encode the returned host dictionaries as JSON. The response includes per-host panels and manager snapshot data. | `fleet/web.py:67-86`; `fleet/queries.py:402-419`. | Measure encoded response bytes and encode time after access to an authenticated response. Do not change response shape based on redirect data. |

## Query-path summary

The route computes shared attribution and self-route data once, then discovers unconfigured host IDs once (`fleet/web.py:69-80`). It then calls `_status_row` in order for each configured or discovered host. In the common started-daemon path, the static estimate is about `4–5 + 15 × host_count` SQL statements per request. The shared count is four when no self-route rows exist and five when the latest probe has rows. Health checks can add statements on stale or dead-session branches. This estimate excludes retries and concurrent requests.

There is no current `asyncio.gather` across host rows. A new unbounded gather would let all rows contend for a four-connection pool that background tasks also use. No pool-saturation evidence is available, so do not raise the pool size or add gather yet.

I did not add `scripts/profile_status.py`: this worktree has no authenticated app or database path to profile. Add a read-only profiler when a safe database snapshot or authenticated status route is available.

## Follow-up: live stage profile and changes

The live profile for image `c81307d` on 2026-09-27 measured 444,262 earnings rows, 41,630 snapshots, 1,944 identities, and two daemon hosts. `unattributed_recent` took 13,401 ms and ran once per host. `shared_status_data` took 3,211 ms. The two host rows took 15,230 ms and 16,142 ms; `/api/status` took about 33 seconds. These timings identify the repeated recent-count query as the largest measured stage.

The follow-up change computes this count once with shared status data and passes it to each row. It also reads the newest `limit` rows per ledger host through the existing `(host, created_at DESC)` index before applying the same payout-rowid and hash/host dedupe rules. The post-change SQL time was not measured against a live database.
