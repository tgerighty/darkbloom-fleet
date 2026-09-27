# Dashboard performance comparison

These in-process results use the same `FakePool` workload and benchmark method documented in [BEFORE.md](BEFORE.md) and [AFTER.md](AFTER.md). They include Python query processing and route work. They exclude PostgreSQL execution, pool waits, HTTP transport, and JSON encoding.

## In-process results

| Case | p50 before (ms) | p50 after (ms) | p95 before (ms) | p95 after (ms) |
|---|---:|---:|---:|---:|
| `/api/status`, 1 host | 257.8583 | 132.2791 | 546.7534 | 214.2004 |
| `/api/status`, 4 hosts | 1,082.0966 | 404.1755 | 2,052.6606 | 597.0270 |
| `serving_percentages` | 250.6780 | 82.2391 | 571.9818 | 147.6367 |
| `latest_demand_table` | 0.0127 | 0.0165 | 0.2523 | 0.0441 |
| `hourly_jobs` | 28.5309 | 5.5712 | 154.6998 | 28.9831 |
| `provider_hosts` | 4.7246 | 4.9576 | 15.7222 | 12.6809 |

The `/api/status` p50 fell by 48.7% for 1 host and 62.6% for 4 hosts. The serving-window p50 fell by 67.2%. The route made 20 pool calls for 1 host before and after, and 65 before versus 62 after for 4 hosts: one shared query replaces a per-host query.

## Live stage evidence

The pre-change live profile on image `c81307d` measured `unattributed_recent` at **13,401 ms** over 444,262 earnings rows. It ran once per host. The same profile recorded `shared_status_data` at 3,211 ms, host rows at 15,230 ms and 16,142 ms, and `/api/status` at about 33 seconds.

The change computes the unattributed count once per request and limits candidate payouts per ledger host before unique-payout selection. For 2 hosts, this removes one repeated 13.4-second stage and reduces the work in the remaining stage. Based on the pre-change profile, `/api/status` should improve by roughly half or better. This is an inference from the live before profile and the query change. No post-change live PostgreSQL timing was taken.
