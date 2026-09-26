# History and dashboard render profile

Profile timestamp: 2026-09-26 23:36 UTC
Base: `c81307d2162f9d0d0d9818901214e2ef0f2b8821`
Scope: history queries and the dashboard fetch/render path. No production code changed.

## What I measured

The live app was not available for an authenticated profile. `GET /` and `GET /api/status` on `https://darkbloom.nxio.ai` both returned Cloudflare Access redirects (HTTP 302), at 102 ms and 117 ms. A request to `127.0.0.1:8080/api/status` returned HTTP 401 in 9 ms. These do not measure successful app or API responses. `DATABASE_URL` was not set in this worker environment, and `psql` was not installed, so I could not measure SQL execution or inspect a live query plan.

I measured the existing JavaScript HTML builders in Node v22.22.1. Each synthetic host had 6 demand models, 50 recent payouts, 6 routability models, and 24 hourly rows with 40 portions each. The benchmark called `mergeDemand`, `renderDemand`, and `renderHosts` with `hourlySection`, after 10 warm-up runs; each result is from 60 runs. It did not include `DOMParser` sanitization, DOM updates, browser layout, network time, API time, or database time.

| Hosts | Median builder time | p95 | Generated HTML characters |
|---:|---:|---:|---:|
| 1 | 1.856 ms | 3.379 ms | 37,650 |
| 5 | 8.884 ms | 31.552 ms | 188,410 |
| 20 | 34.648 ms | 73.811 ms | 756,348 |

This synthetic result grows close to linearly with host count. The larger p95 values show noise and allocation or garbage-collection cost in this short run. It does not show a client bottleneck for small fleets. The 20-host case is a test workload, not a measurement of the live fleet.

## Request and query path

`fleet/web.py:62-63` serves the page as a static `FileResponse`; the app does not render a server-side template. The browser loads `/static/dashboard.js`, fetches `/api/status`, validates the payload, then calls the client render path. The initial fetch runs at `fleet/static/dashboard.js:123`; later polls run every 60 seconds at line 124. Changing the serving-window selector re-renders the last response without another API request. Each render builds HTML strings, then parses and sanitizes them with `DOMParser` before replacing the host and demand nodes (`dashboard.js:55-80`).

The normal fresh-host status path runs 15 SQL statements across 13 pool checkouts per host. This count assumes no dead-session probe and the usual fresh-snapshot health path. The status handler awaits each host's `_status_row` work in a loop (`fleet/web.py:68-85`), so host query batches run one after another.

| Per-host work | SQL statements |
|---|---:|
| Latest daemon snapshot and demand | 2 |
| Routability: last served, switch-cost sessions, and two session-time queries | 4 |
| Earnings totals | 2 |
| Serving history: bounded windows and lifetime | 2 |
| Recent earnings, unattributed count, card totals, and hourly buckets | 4 |
| Fresh-host health history | 1 |
| **Total** | **15** |

Before per-host work, `/api/status` runs 4 or 5 shared statements: two for provider attribution, one or two for the latest self-route sample, and one for known hosts. Therefore the normal-path statement count is `15 × displayed_hosts + 4..5`. The shared host discovery includes up to 32 discovered hosts in addition to configured hosts. Checkout count is `13 × displayed_hosts + 3` on this path. Health can add a statement for candidate dead sessions; stale hosts take a different path.

## Ranked bottlenecks and smallest next steps

These are source-based risk rankings. I could not verify them with live timings or `EXPLAIN` because database access was unavailable.

1. **Account-wide payout attribution can grow with ledger history.** `fleet/attribution.py:24-52` builds votes from every payout with a provider hash and no exact identity. It crosses those payouts with daemon hosts and does prior/next snapshot lookups for each pair. It runs once on every status poll (`queries.shared_status_data`, `fleet/queries.py:387-392`). The existing snapshot index supports the lateral lookups, but the payout CTE has no time boundary. First run `EXPLAIN (ANALYZE, BUFFERS)` on an anonymized production-sized database. If it dominates, retain resolved attribution and recalculate only new or unresolved payout rows, while allowing later identity records to correct it.
2. **Per-host query batches are serial and chatty.** The normal path uses 15 statements and 13 pool checkouts per displayed host, then the route waits for each host before starting the next. With the existing four-connection pool, compare a bounded concurrent status fan-out with the serial route. Keep it only if API latency falls without increasing database load materially.
3. **Three per-host calculations revisit daemon history.** `routability.last_served` reads the host's history (`fleet/routability.py:52-64`), switch-cost aggregation groups host sessions (`:88-105`), and lifetime serving uses a full-history window query (`fleet/queries.py:349-366`). The `(host, observed_at DESC)` index exists (`fleet/db.py:59-60`), but work still grows with retained snapshots. After query-plan measurement, reuse one ordered host history for these calculations or persist a small aggregate if that history dominates.
4. **Client HTML generation scales with payload size, but the measured builder cost is small at 1 and 5 synthetic hosts.** Do not optimize it before measuring a real browser. If a browser profile identifies it, measure `safeNodes`/DOM replacement separately; this Node run excluded them.

No history optimization is implemented in this report. The next useful evidence is one authenticated `/api/status` trace plus per-query `EXPLAIN (ANALYZE, BUFFERS)` on a production-sized database copy.

## Follow-up: shared recent count

The live profile on 2026-09-27 found `unattributed_recent` took 13,401 ms on 444,262 earnings rows and ran once per host. The status path now computes it once per request. This reduces the common per-host path by one SQL statement and checkout: 14 statements over 12 checkouts. The live query rewrite uses the existing host/time index to limit recent candidates before payout deduplication. No post-change database timing is available.
