# DB pool and dashboard query review

Base: `c81307d2162f9d0d0d9818901214e2ef0f2b8821`.

This is a source review. The test pool records SQL and returns canned rows; it does not connect to PostgreSQL. No live query timings, pool wait data, or `EXPLAIN` plans were collected. The counts below come from the request call path, not a production measurement.

## Pool and checkouts

`fleet.db.get_pool` sets `min_size=1` and `max_size=4`. `fleet.main` creates one pool and shares it with the web app and all configured host loops. Each query helper checks out a connection with `with pool.connection()` and releases it on exit. Status rows run in worker threads, one host at a time within each request. Requests can still overlap each other and the scheduler, watchdog, and optional earnings publisher. This can queue work when four checkouts are active. No pool wait instrumentation or explicit checkout timeout is configured.

The watchdog performs SSH before its DB checkout and sends alerts after it releases the checkout. The earnings publisher also performs its DB work before SSH publishing. These paths do not hold a DB connection across network I/O.

## Query counts

There is one dashboard API route, `/api/status`. It includes the serving-history panels; there is no separate history route.

For a populated self-route table, shared status and host discovery use 6 SQL statements over 4 checkouts per request: 2 attribution statements, 2 self-route statements, 1 recent unattributed count, and 1 host-discovery statement. An empty self-route table removes its second statement.

A fresh host with `started_at` set, no qualifying dead-session check, and the normal thrash check uses 14 SQL statements over 12 checkouts. This includes 2 session-timing statements in one checkout. Without `started_at`, it uses 12 statements over 11 checkouts. A stale host first runs its stale query, then can run dead-session and thrash checks unless it is already down. An absent daemon skips health-history queries.

Therefore the common populated case is `6 + 14 × displayed_hosts` SQL statements and `4 + 12 × displayed_hosts` checkouts. Discovered hosts can add up to 32 rows. The count is variable for empty self-route data and health branches.

Each host's serving panel runs 2 statements in one checkout: a bounded snapshot query for 1h/7h/24h/30d and its left-boundary row, then a separate lifetime `LEAD` aggregate. Python derives the four bounded windows from one result. The tests assert these two statements and confirm that two host rows reuse request-wide attribution while each host runs its own history queries.

## Findings

1. **Resolved: repeated account-wide query per host.** `shared_status_data` computes `unattributed_recent` once and passes the count to every host row. The query reads recent rows per ledger host through `earnings_host_time`, then applies the existing account-wide unique-payout selection.

2. **Several history queries grow with retained rows.** `last_served` applies `LAG` to all snapshots for one host. `_switch_cost_sessions` groups all snapshots for that host. Lifetime serving scans all snapshots for that host with `LEAD`. The existing `(host, observed_at DESC)` index supports latest and bounded time lookups, but does not prove these full-history queries avoid a sort or heap scan.

3. **Attribution can grow with both ledger rows and hosts.** `_VOTES_SQL` recomputes historical payout votes once per status request. It builds a payout set, crosses it with distinct daemon hosts, and makes two lateral snapshot lookups per payout/host pair. The daemon host/time index supports those lookups. The test fake cannot show the real row counts or plan cost.

4. **Four connections are a possible queue limit, not a proven bottleneck.** One `/api/status` request builds host rows sequentially. Concurrent requests and per-host background loops can still overlap on the shared four-connection pool. No checked-out, queued, or wait-duration evidence was found. The dashboard read path has no explicit row or advisory locks. Unique-key upserts can contend during concurrent writes, but no observed lock wait is available.

## Changes to consider after measurement

- The repeated `unattributed_recent` query is removed by computing it once per request.
- Capture `EXPLAIN (ANALYZE, BUFFERS)` for `_VOTES_SQL`, `_UNATTRIBUTED_SQL`, both serving queries, `last_served`, and `_switch_cost_sessions` on a representative non-production database. Keep actual row counts and pool wait time with the result.
- If plans show sorting or heap reads dominate `last_served` and `_switch_cost_sessions`, test a covering index on `daemon_snapshots (host, started_at, observed_at) INCLUDE (requests_served, current_model)`. Keep it only if the plans and latency improve enough to justify write and storage cost.
- If plans show the session-timing search filters many zero-valued probes, test a partial `self_route_samples (observed_at)` index with `WHERE routable_providers > 0`.
- Do not raise `max_size` until checkout waits show saturation. The current four-connection limit alone is not evidence that the pool is too small.

## Evidence

- Pool and indexes: `fleet/db.py:31-32`, `fleet/db.py:59-60`, `fleet/db.py:92-106`, `fleet/db.py:135-136`.
- Shared request path and sequential host rows: `fleet/web.py:67-85`.
- Status query calls: `fleet/queries.py:394-420`.
- History queries: `fleet/queries.py:250-275`, `fleet/queries.py:349-366`.
- Repeated account-wide query: `fleet/attribution.py:104-120`.
- Pool fake limitation: `tests/conftest.py:1-3`, `tests/conftest.py:20-44`.
- History statement count: `tests/test_queries.py:104-119`.
- Shared data and multi-host history: `tests/test_queries.py:244-283`.
- Sequential host rows: `tests/test_web_main.py::test_status_builds_host_rows_one_at_a_time`.
