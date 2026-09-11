"""Read-only aggregations for the dashboard API. Kept separate from db.py's
writes so each file stays small and single-purpose.
"""
from __future__ import annotations

import time
from itertools import pairwise

from psycopg_pool import ConnectionPool

from .config import Config

DAY_SECONDS = 86_400
OUTAGE_GAP_SECONDS = 600
Row = dict[str, object]


def latest_demand_table(pool: ConnectionPool, host: str) -> list[Row]:
    """Most recent sample per model, newest first by score."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (model) model, active_requests, warm_providers, pressure, "
            "output_usd_per_million, score, ema_score, observed_at "
            "FROM demand_samples WHERE host = %s ORDER BY model, observed_at DESC",
            (host,),
        ).fetchall()
    return sorted(rows, key=lambda r: r["ema_score"] or 0, reverse=True)


def latest_daemon(pool: ConnectionPool, host: str) -> Row | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT * FROM daemon_snapshots WHERE host = %s ORDER BY observed_at DESC LIMIT 1", (host,)
        ).fetchone()


def earnings_usd(pool: ConnectionPool, host: str, since: float) -> float:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT coalesce(sum(micro_usd), 0) AS total FROM earnings WHERE host = %s AND created_at > %s",
            (host, since),
        ).fetchone()
    return float(row["total"]) / 1_000_000


def recent_decisions(pool: ConnectionPool, host: str, limit: int = 20) -> list[Row]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT observed_at, current_model, target_model, action, reason, mode, executed, error "
            "FROM decisions WHERE host = %s ORDER BY observed_at DESC LIMIT %s",
            (host, limit),
        ).fetchall()


def _serving_shares(snapshots: list[Row], since: float, now: float) -> dict[str, float]:
    """Percentage of covered window time per model. Each snapshot holds until
    the next one (the last until now), counted only inside the window; a gap
    longer than OUTAGE_GAP_SECONDS is an outage and counts for nobody."""
    points = [*snapshots, {"observed_at": now, "current_model": None}]
    totals: dict[str, float] = {}
    for prev, nxt in pairwise(points):
        model = prev["current_model"]
        if model and 0 < nxt["observed_at"] - prev["observed_at"] < OUTAGE_GAP_SECONDS:
            held = nxt["observed_at"] - max(prev["observed_at"], since)
            if held > 0:
                totals[model] = totals.get(model, 0.0) + held
    covered = sum(totals.values())
    return {model: round(100 * seconds / covered, 1) for model, seconds in totals.items()} if covered else {}


def serving_percentage(pool: ConnectionPool, host: str, window_seconds: float) -> dict[str, float]:
    """Share of the window each model was the reported current_model, including
    the model already serving when the window opened."""
    now = time.time()
    since = now - window_seconds
    with pool.connection() as conn:
        before = conn.execute(
            "SELECT observed_at, current_model FROM daemon_snapshots "
            "WHERE host = %s AND observed_at <= %s ORDER BY observed_at DESC LIMIT 1",
            (host, since),
        ).fetchone()
        rows = conn.execute(
            "SELECT observed_at, current_model FROM daemon_snapshots "
            "WHERE host = %s AND observed_at > %s ORDER BY observed_at",
            (host, since),
        ).fetchall()
    return _serving_shares(([before] if before else []) + rows, since, now)


def build_status(cfg: Config, pool: ConnectionPool) -> Row:
    host = cfg.host_label
    daemon = latest_daemon(pool, host)
    now = time.time()
    return {
        "host": {"label": cfg.host_label, "spec": cfg.host_spec},
        "mode": "LIVE" if cfg.live_execution else "OBSERVE",
        "current_model": daemon["current_model"] if daemon else None,
        "daemon_fresh": daemon["fresh"] if daemon else False,
        "inference_active": daemon["inference_active"] if daemon else None,
        "as_of": daemon["observed_at"] if daemon else None,
        "demand": latest_demand_table(pool, host),
        "earnings_usd_24h": round(earnings_usd(pool, host, now - DAY_SECONDS), 4),
        "earnings_usd_1h": round(earnings_usd(pool, host, now - 3600), 4),
        "serving_percentage_24h": serving_percentage(pool, host, DAY_SECONDS),
        "recent_decisions": recent_decisions(pool, host),
    }
