# Dashboard performance baseline before changes

Captured at **2026-09-27 00:38:42 BST** on base commit `c81307d2162f9d0d0d9818901214e2ef0f2b8821`.

## Method

The benchmark calls the `/api/status` route handler in the FastAPI app. It uses the existing `tests.conftest.FakePool` with fixed synthetic rows. It measures 30 samples after 5 warm-up samples. It uses `perf_counter_ns` and reports milliseconds. The p95 uses the nearest-rank method.

The API has no separate history route. The serving history windows appear in `/api/status`.

The test pool does not run SQL. The times include Python query processing and route work. They exclude PostgreSQL execution, pool waits, HTTP transport, and JSON encoding. Use these figures only as an in-process baseline for the same synthetic workload. They are not live API latency.

The workload used 1 and 4 configured hosts, with no discovered hosts. Each host had 43,201 daemon snapshot rows for 30 days, 16 demand models, and 960 hourly groups. The shared attribution query returned 1,024 vote rows.

The benchmark ran on CPython 3.12.14, Linux aarch64, with 4 reported CPUs. The file `/tmp/rig-dbf-perf-20260927/reports/w1-before.json` has every sample and the full environment record.

## Results

| Case | Fixture input | p50 (ms) | p95 (ms) | Mean (ms) |
|---|---:|---:|---:|---:|
| `/api/status`, 1 host | 43,201 history rows | 257.8583 | 546.7534 | 291.2870 |
| `/api/status`, 4 hosts | 43,201 rows per host | 1,082.0966 | 2,052.6606 | 1,137.2673 |
| `serving_percentages` | 43,201 history rows | 250.6780 | 571.9818 | 292.2276 |
| `latest_demand_table` | 64 models | 0.0127 | 0.2523 | 0.0833 |
| `hourly_jobs` | 960 grouped rows | 28.5309 | 154.6998 | 45.4809 |
| `provider_hosts` | 1,024 votes | 4.7246 | 15.7222 | 6.6659 |

The 30-day serving calculation was the slowest isolated Python query path. Its median was 250.6780 ms. The 4-host status handler had a median of 1,082.0966 ms. These measurements show local Python work only. They do not show PostgreSQL query cost.

## Reproduce

The system Python did not have the app dependencies. I used an isolated temporary environment:

```sh
uv venv --python python3 /tmp/rig-dbf-perf-20260927-venv
uv pip install --python /tmp/rig-dbf-perf-20260927-venv/bin/python -r requirements.txt pytest
PYTHONDONTWRITEBYTECODE=1 /tmp/rig-dbf-perf-20260927-venv/bin/python scripts/bench_dashboard_perf.py --iterations 30 --warmups 5 --json-out /tmp/rig-dbf-perf-20260927/reports/w1-before.json
```

The JSON report records the command, base SHA, local timestamp, workload, and raw samples.
