#!/usr/bin/env python3
"""Time dashboard handlers and hot Python query paths with the test FakePool."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import shlex
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import FakePool  # noqa: E402
from fleet import attribution, hourly, queries, web  # noqa: E402

DAY = 86_400
HISTORY_ROWS = 30 * 24 * 60 + 1
HISTORY_MODELS = ("model-a", "model-b", "model-c", "model-d")
VOTE_ROWS = 1_024
HOURLY_ROWS = 24 * 40


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def _history(now: float) -> list[dict[str, object]]:
    return [
        {"observed_at": now - (HISTORY_ROWS - 1 - i) * 60,
         "current_model": HISTORY_MODELS[(i // 10) % len(HISTORY_MODELS)],
         "inference_active": i % 5 != 0, "fresh": True}
        for i in range(HISTORY_ROWS)
    ]


def _hourly_rows(now: float) -> list[dict[str, object]]:
    newest = int(now // 3_600) * 3_600
    return [
        {"hour": hour, "portion": portion,
         "model": HISTORY_MODELS[(hour_index + portion) % len(HISTORY_MODELS)], "n": 1 + portion % 4}
        for hour_index, hour in enumerate(range(newest, newest - 24 * 3_600, -3_600))
        for portion in range(40)
    ]


def _demand_rows(now: float, count: int) -> list[dict[str, object]]:
    return [
        {"model": f"model-{i:02d}", "active_requests": i % 4, "warm_providers": 1 + i % 3,
         "pressure": 0.25 + i / (count * 4), "output_usd_per_million": 0.1,
         "score": 0.5, "ema_score": count - i, "observed_at": now - 60,
         "observed_prefill_tps": 20.0, "observed_decode_tps": 10.0, "aggregate_tps": 30.0}
        for i in range(count)
    ]


def _fixtures(now: float, host_count: int, history: list[dict[str, object]],
              hourly_rows: list[dict[str, object]]) -> tuple[tuple[object, ...], list[str]]:
    host_ids = [f"host-{i + 1}" for i in range(host_count)]
    votes = [
        {"payout_rowid": i + 1, "provider_hash": f"hash-{i:04d}",
         "host": host_ids[i % host_count]}
        for i in range(VOTE_ROWS)
    ]
    identities = [{"provider_hash": f"exact-{i}", "host": host} for i, host in enumerate(host_ids)]
    latest_route = [{"model": model, "routable_providers": 5} for model in HISTORY_MODELS]
    daemon_rows = []
    for host in host_ids:
        demand_models = [row["model"] for row in _demand_rows(now, 16)]
        manager_models = {
            model: {"eligible": True, "score": 1.0 - i / 100,
                    "now_pressure": 0.6, "average_pressure": 0.5,
                    "blended_usd_per_million": 0.1, "weight": 1.0}
            for i, model in enumerate(demand_models)
        }
        daemon_rows.append({
            "current_model": "model-a", "warm_models": list(HISTORY_MODELS),
            "advertised_models": list(HISTORY_MODELS), "installed_models": list(HISTORY_MODELS),
            "inference_active": False, "fresh": True, "observed_at": now - 1,
            "started_at": now - 3_600, "requests_served": 100, "trust_level": "self_signed",
            "manager": {"score_snapshot": {"observed_at": now - 1, "models": manager_models}},
            "slots": [],
        })
    self_route_rows = latest_route
    known_hosts = [{"host": host, "daemon": True} for host in host_ids]
    unattributed_rows = [{"provider_hash": None}, {"provider_hash": "unknown"}]
    shared = (votes, identities, [{"t": now - 5}], self_route_rows, unattributed_rows, known_hosts)

    per_host: list[object] = []
    demand_rows = _demand_rows(now, 16)
    lifetime_rows = [{"since": now - 90 * DAY, "model": model, "seconds": 1_000_000.0}
                     for model in HISTORY_MODELS]
    recent_rows = [{"created_at": now - i, "model": HISTORY_MODELS[i % 4],
                    "completion_tokens": 200 + i, "micro_usd": 100 + i}
                   for i in range(50)]
    served_rows = [{"model": model, "t": now - i * 60} for i, model in enumerate(HISTORY_MODELS)]
    health_rows = [{"observed_at": now - (59 - i) * 60, "warm_models": list(HISTORY_MODELS),
                    "inference_active": False, "requests_served": 100} for i in range(60)]
    for daemon in daemon_rows:
        per_host.extend([
            [daemon], demand_rows, served_rows, [{"median": 42.0, "n": 5}],
            [{"t": now - 300}], [{"t": now - 120}],
            [{"total": 2_500_000}], [{"total": 500_000}], history, lifetime_rows,
            recent_rows, [{"tokens": 4_000, "requests": 50}],
            hourly_rows, health_rows,
        ])
    return (*shared, *per_host), host_ids


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def _summary(samples: list[float]) -> dict[str, object]:
    return {
        "iterations": len(samples),
        "p50_ms": round(statistics.median(samples), 4),
        "p95_ms": round(_percentile(samples, 95), 4),
        "mean_ms": round(statistics.mean(samples), 4),
        "samples_ms": [round(sample, 4) for sample in samples],
    }


async def _status_samples(host_count: int, now: float, history: list[dict[str, object]],
                          hourly_rows: list[dict[str, object]], warmups: int,
                          iterations: int) -> tuple[list[float], int]:
    responses, host_ids = _fixtures(now, host_count, history, hourly_rows)
    pool = FakePool()
    pool.responses[:] = responses
    configs = tuple(SimpleNamespace(host_id=host, host_label=host, host_spec="synthetic",
                                    switch_cost_seconds=300.0, daemon_freshness_seconds=90.0)
                    for host in host_ids)
    app = web.create_app(configs, pool)
    route = next(route for route in app.router.routes if getattr(route, "path", None) == "/api/status")
    samples: list[float] = []
    expected_calls = 6 + 14 * host_count
    for index in range(warmups + iterations):
        pool.responses[:] = responses
        pool.calls.clear()
        start = time.perf_counter_ns()
        result = await route.endpoint()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        assert len(result["hosts"]) == host_count
        assert all("serving" in host and "hourly_jobs" in host for host in result["hosts"])
        assert len(pool.calls) == expected_calls and not pool.responses
        if index >= warmups:
            samples.append(elapsed_ms)
    return samples, expected_calls


def _query_samples(name: str, function, responses: tuple[object, ...], warmups: int,
                   iterations: int, check) -> list[float]:
    pool = FakePool(*responses)
    samples = []
    for index in range(warmups + iterations):
        pool.responses[:] = responses
        pool.calls.clear()
        start = time.perf_counter_ns()
        result = function(pool)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        assert check(result)
        assert len(pool.calls) == len(responses) and not pool.responses
        if index >= warmups:
            samples.append(elapsed_ms)
    return samples


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=_positive, default=30)
    parser.add_argument("--warmups", type=_nonnegative, default=5)
    parser.add_argument("--host-counts", type=_positive, nargs="+", default=[1, 4])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    now = time.time()
    history = _history(now)
    hourly_rows = _hourly_rows(now)
    benchmarks: dict[str, object] = {}
    for host_count in args.host_counts:
        samples, calls = asyncio.run(_status_samples(
            host_count, now, history, hourly_rows, args.warmups, args.iterations,
        ))
        benchmarks[f"api_status_{host_count}_hosts"] = {
            "route": "/api/status", "configured_hosts": host_count, "discovered_hosts": 0,
            "pool_calls_per_request": calls, **_summary(samples),
        }

    vote_responses, _ = _fixtures(now, 4, history, hourly_rows)
    for name, function, responses, check in [
        ("serving_percentages_30d", lambda pool: queries.serving_percentages(pool, "host-1", now),
         (history, [{"since": now - 90 * DAY, "model": m, "seconds": 1_000_000.0}
                    for m in HISTORY_MODELS]),
         lambda value: set(value) == set(queries.SERVING_WINDOWS)),
        ("latest_demand_64_models", lambda pool: queries.latest_demand_table(pool, "host-1"),
         (_demand_rows(now, 64),), lambda value: len(value) == 64),
        ("hourly_jobs_960_rows", lambda pool: hourly.hourly_jobs(pool, ["hash"], now),
         (hourly_rows,), lambda value: len(value["rows"]) == 24),
        ("provider_hosts_1024_votes", attribution.provider_hosts,
         (vote_responses[0], []), lambda value: len(value) == VOTE_ROWS),
    ]:
        samples = _query_samples(name, function, responses, args.warmups, args.iterations, check)
        benchmarks[name] = {"input_rows": len(responses[0]), **_summary(samples)}

    stamp = datetime.now(ZoneInfo("Europe/London")).isoformat(timespec="seconds")
    command = shlex.join([sys.executable, str(Path(__file__).relative_to(ROOT)), *sys.argv[1:]])
    if os.environ.get("PYTHONDONTWRITEBYTECODE") == "1":
        command = f"PYTHONDONTWRITEBYTECODE=1 {command}"
    report = {
        "timestamp_local": stamp,
        "timezone": "Europe/London",
        "git_sha": _git_sha(),
        "command": command,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "cpu_count": os.cpu_count()},
        "method": {
            "fixture": "tests.conftest.FakePool with deterministic synthetic rows",
            "timing": "perf_counter_ns wall time, measured after warm-up",
            "percentile": "nearest rank",
            "units": "milliseconds",
            "database_execution_measured": False,
            "http_transport_and_json_serialization_measured": False,
            "history_endpoint_note": "No separate history route exists; serving windows are in /api/status.",
        },
        "workload": {"host_counts": args.host_counts, "history_days": 30,
                     "history_rows_per_host": len(history), "demand_models_per_host": 16,
                     "vote_rows": VOTE_ROWS, "hourly_group_rows": len(hourly_rows),
                     "warmups": args.warmups, "iterations": args.iterations},
        "benchmarks": benchmarks,
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
