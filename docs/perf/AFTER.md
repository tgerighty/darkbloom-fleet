# Dashboard performance after changes

Captured at **2026-09-27 01:00:23 BST** on dashboard commit `ec672f784e8b4087a8b50bceb478799b90a14fd2`.

## Method

The benchmark calls the `/api/status` route handler in the FastAPI app. It uses `tests.conftest.FakePool` with fixed synthetic rows. It measures 30 samples after 5 warm-up samples. It uses `perf_counter_ns` and reports milliseconds. The p95 uses the nearest-rank method.

The test pool does not run SQL. The times include Python query processing and route work. They exclude PostgreSQL execution, pool waits, HTTP transport, and JSON encoding. These are in-process results for the same synthetic workload as [BEFORE.md](BEFORE.md), not live API latency.

The workload used 1 and 4 configured hosts, with no discovered hosts. Each host had 43,201 daemon snapshot rows for 30 days, 16 demand models, and 960 hourly groups. The shared attribution query returned 1,024 vote rows. The run used CPython 3.12.14 on Linux aarch64 with 4 reported CPUs.

The fixture now follows the changed route: 6 shared query calls and 14 calls per host. The prior route used 5 shared calls and 15 per host. The full JSON report, including raw samples and environment details, is `/tmp/rig-dbf-perf-20260927/reports/w6-after.json`.

## Results

| Case | Fixture input | Pool calls | p50 (ms) | p95 (ms) | Mean (ms) |
|---|---:|---:|---:|---:|---:|
| `/api/status`, 1 host | 43,201 history rows | 20 | 132.2791 | 214.2004 | 136.7545 |
| `/api/status`, 4 hosts | 43,201 rows per host | 62 | 404.1755 | 597.0270 | 438.0708 |
| `serving_percentages` | 43,201 history rows | — | 82.2391 | 147.6367 | 90.3144 |
| `latest_demand_table` | 64 models | — | 0.0165 | 0.0441 | 0.0196 |
| `hourly_jobs` | 960 grouped rows | — | 5.5712 | 28.9831 | 8.7732 |
| `provider_hosts` | 1,024 votes | — | 4.9576 | 12.6809 | 6.3756 |

These measurements show local Python work only. They do not measure PostgreSQL query cost.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/rig-dbf-perf-20260927-venv/bin/python scripts/bench_dashboard_perf.py --iterations 30 --warmups 5 --json-out /tmp/rig-dbf-perf-20260927/reports/w6-after.json
```
