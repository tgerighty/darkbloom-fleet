"""Read-only aggregations for the dashboard API. Kept separate from db.py's
writes so each file stays small and single-purpose.
"""
from __future__ import annotations

import time
from itertools import pairwise

from psycopg_pool import ConnectionPool

from .config import Config
from .routability import routability_panel

DAY_SECONDS = 86_400
OUTAGE_GAP_SECONDS = 600
# Dashboard serving windows; None = lifetime (since the first snapshot).
SERVING_WINDOWS: dict[str, float | None] = {
    "1h": 3600, "7h": 7 * 3600, "24h": DAY_SECONDS, "30d": 30 * DAY_SECONDS, "lifetime": None,
}
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


def recent_earnings(pool: ConnectionPool, host: str, limit: int = 50) -> list[Row]:
    """Latest payouts read from this host's ledger. The ledger is
    account-wide, so rows are not attributable to this host (see progress.md)."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT created_at, model, completion_tokens, micro_usd "
            "FROM earnings WHERE host = %s ORDER BY created_at DESC LIMIT %s",
            (host, limit),
        ).fetchall()


def _serving_shares(snapshots: list[Row], since: float, now: float) -> dict[str, float]:
    """Percentage of the window each model was actively serving a request,
    plus "idle" for the rest: warm but not serving, no model, or no snapshot.
    Each snapshot's inference_active holds until the next one (the last until
    now), counted only inside the window; a gap longer than
    OUTAGE_GAP_SECONDS is an outage and counts as idle. Snapshots are a minute
    apart, so requests shorter than that are under-counted."""
    points = [*snapshots, {"observed_at": now, "current_model": None, "inference_active": False}]
    totals: dict[str, float] = {}
    for prev, nxt in pairwise(points):
        model = prev["current_model"]
        if model and prev.get("inference_active") and 0 < nxt["observed_at"] - prev["observed_at"] <= OUTAGE_GAP_SECONDS:
            held = nxt["observed_at"] - max(prev["observed_at"], since)
            totals[model] = totals.get(model, 0.0) + held
    window = now - since
    if window <= 0:
        return {}
    shares = {model: round(100 * seconds / window, 1) for model, seconds in totals.items()}
    shares["idle"] = round(100 * max(window - sum(totals.values()), 0.0) / window, 1)
    return shares


def serving_percentage(pool: ConnectionPool, host: str, window_seconds: float | None) -> dict[str, float]:
    """Share of the window each model was actively serving, including the
    state already in force when the window opened. None = lifetime."""
    now = time.time()
    if window_seconds is None:
        with pool.connection() as conn:
            first = conn.execute(
                "SELECT min(observed_at) AS t FROM daemon_snapshots WHERE host = %s", (host,)
            ).fetchone()
        if not first or first["t"] is None:
            return {}
        window_seconds = now - float(first["t"])
    since = now - window_seconds
    with pool.connection() as conn:
        before = conn.execute(
            "SELECT observed_at, current_model, inference_active FROM daemon_snapshots "
            "WHERE host = %s AND observed_at <= %s ORDER BY observed_at DESC LIMIT 1",
            (host, since),
        ).fetchone()
        rows = conn.execute(
            "SELECT observed_at, current_model, inference_active FROM daemon_snapshots "
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
        "serving": {name: serving_percentage(pool, host, seconds) for name, seconds in SERVING_WINDOWS.items()},
        "recent_decisions": recent_decisions(pool, host, limit=50),
        "recent_earnings": recent_earnings(pool, host),
        "routability": routability_panel(pool, host, daemon),
    }
