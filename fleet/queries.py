"""Read-only aggregations for the dashboard API. Kept separate from db.py's
writes so each file stays small and single-purpose.
"""
from __future__ import annotations

import time
from itertools import pairwise

from psycopg_pool import ConnectionPool

from .attribution import provider_hosts, unattributed_recent, unique_payouts_sql
from .card import build_card
from .config import Config
from .hourly import hourly_jobs
from .routability import latest_self_route, routability_panel

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


_EARNINGS_SUM_SQL = (
    "SELECT coalesce(sum(micro_usd), 0) AS total FROM ("
    + unique_payouts_sql("micro_usd", "created_at > %s AND created_at <= %s AND provider_hash = ANY(%s)")
    + ") unique_payouts"
)


def earnings_usd(pool: ConnectionPool, since: float, now: float, hashes: list[str]) -> float:
    """Only payouts whose provider session is attributed to this host; the
    ledger is account-wide, so the ingest host column is not ownership
    (see attribution.py). Replicated copies share payout_rowid."""
    with pool.connection() as conn:
        row = conn.execute(_EARNINGS_SUM_SQL, (since, now, hashes)).fetchone()
    return float(row["total"]) / 1_000_000


_RECENT_SQL = (
    "SELECT created_at, model, completion_tokens, micro_usd FROM ("
    + unique_payouts_sql(
        "created_at, model, completion_tokens, micro_usd",
        "created_at <= %s AND provider_hash = ANY(%s)",
    )
    + ") unique_payouts ORDER BY created_at DESC LIMIT %s"
)


def recent_earnings(pool: ConnectionPool, now: float, hashes: list[str], limit: int = 50) -> list[Row]:
    """Latest unique payouts attributed to this host by provider session
    (the ledger copy itself is account-wide — see attribution.py)."""
    with pool.connection() as conn:
        return conn.execute(_RECENT_SQL, (now, hashes, limit)).fetchall()


_BOUNDED_SERVING_SQL = (
    "SELECT observed_at, current_model, inference_active, fresh FROM ("
    "SELECT observed_at, current_model, inference_active, fresh FROM daemon_snapshots "
    "WHERE host = %s AND observed_at > %s AND observed_at <= %s "
    "UNION ALL "
    "SELECT observed_at, current_model, inference_active, fresh FROM ("
    "SELECT observed_at, current_model, inference_active, fresh FROM daemon_snapshots "
    "WHERE host = %s AND observed_at <= %s ORDER BY observed_at DESC LIMIT 1"
    ") left_boundary) bounded ORDER BY observed_at"
)
_LIFETIME_SERVING_SQL = (
    "WITH snaps AS ("
    "SELECT observed_at, current_model, inference_active, fresh FROM daemon_snapshots "
    "WHERE host = %s AND observed_at <= %s"
    "), bounds AS (SELECT MIN(observed_at) AS since FROM snaps), ordered AS ("
    "SELECT s.observed_at, s.current_model, s.inference_active, s.fresh, "
    "LEAD(s.observed_at) OVER (ORDER BY s.observed_at) AS lead_at, b.since "
    "FROM snaps s CROSS JOIN bounds b"
    "), held AS ("
    "SELECT current_model, since, CASE WHEN current_model IS NOT NULL "
    "AND inference_active AND fresh "
    f"AND 0 < (COALESCE(lead_at, %s) - observed_at) AND (COALESCE(lead_at, %s) - observed_at) <= {int(OUTAGE_GAP_SECONDS)} "
    "THEN COALESCE(lead_at, %s) - GREATEST(observed_at, since) ELSE 0 END AS seconds "
    "FROM ordered) "
    "SELECT b.since, h.model, h.seconds FROM bounds b LEFT JOIN ("
    "SELECT current_model AS model, SUM(seconds) AS seconds FROM held "
    "WHERE seconds > 0 AND current_model IS NOT NULL GROUP BY current_model"
    ") h ON TRUE"
)


def _shares_from_totals(totals: dict[str, float], since: float, now: float) -> dict[str, float]:
    window = now - since
    if window <= 0:
        return {}
    shares = {model: round(100 * seconds / window, 1) for model, seconds in totals.items()}
    shares["idle"] = round(100 * max(window - sum(totals.values()), 0.0) / window, 1)
    return shares


def _serving_shares(snapshots: list[Row], since: float, now: float) -> dict[str, float]:
    """Percentage of the window each model was actively serving a request,
    plus "idle" for the rest: warm but not serving, no model, no snapshot, or
    a snapshot with fresh=false. Each fresh snapshot's inference_active holds
    until the next one (the last until now), counted only inside the window;
    a gap longer than OUTAGE_GAP_SECONDS is an outage and counts as idle.
    Snapshots are a minute apart, so requests shorter than that are under-counted.
    Rows after `now` never contribute."""
    usable = [snap for snap in snapshots if float(snap["observed_at"]) <= now]
    points = [*usable, {"observed_at": now, "current_model": None, "inference_active": False}]
    totals: dict[str, float] = {}
    for prev, nxt in pairwise(points):
        model = prev["current_model"]
        nxt_at = min(float(nxt["observed_at"]), now)
        if (model and prev.get("inference_active") and prev.get("fresh", True)
                and 0 < nxt_at - float(prev["observed_at"]) <= OUTAGE_GAP_SECONDS):
            held = nxt_at - max(float(prev["observed_at"]), since)
            if held > 0:
                totals[str(model)] = totals.get(str(model), 0.0) + held
    return _shares_from_totals(totals, since, now)


def _window_shares(snapshots: list[Row], window_seconds: float | None, now: float) -> dict[str, float]:
    """Reduce one ordered history to a window. None = since the first snapshot.
    The latest row at or before `since` is the state already in force; later
    rows fill the window. Every window of one status row uses the same `now`."""
    snapshots = [snap for snap in snapshots if float(snap["observed_at"]) <= now]
    if window_seconds is not None:
        since = now - window_seconds
    elif not snapshots:
        return {}
    else:
        since = min(float(row["observed_at"]) for row in snapshots)
    before = None
    after: list[Row] = []
    for snap in snapshots:
        if snap["observed_at"] <= since:
            before = snap
        else:
            after.append(snap)
    return _serving_shares(([before] if before else []) + after, since, now)


def _lifetime_shares(rows: list[Row], now: float) -> dict[str, float]:
    if not rows:
        return {}
    since = rows[0].get("since")
    if since is None:
        return {}
    totals: dict[str, float] = {}
    for row in rows:
        model = row.get("model")
        seconds = row.get("seconds")
        if not model or seconds is None:
            continue
        totals[str(model)] = totals.get(str(model), 0.0) + float(seconds)
    return _shares_from_totals(totals, float(since), now)


def serving_percentages(pool: ConnectionPool, host: str, now: float) -> dict[str, dict[str, float]]:
    """Share of each dashboard window that each model was actively serving.
    Named windows share one 30-day history plus the left-boundary row;
    lifetime is a separate LEAD aggregate. Future rows are excluded."""
    bound_start = now - 30 * DAY_SECONDS
    with pool.connection() as conn:
        snapshots = conn.execute(
            _BOUNDED_SERVING_SQL, (host, bound_start, now, host, bound_start),
        ).fetchall()
        lifetime_rows = conn.execute(
            _LIFETIME_SERVING_SQL, (host, now, now, now, now),
        ).fetchall()
    named = {
        name: _window_shares(snapshots, seconds, now)
        for name, seconds in SERVING_WINDOWS.items() if seconds is not None
    }
    named["lifetime"] = _lifetime_shares(lifetime_rows, now)
    return named


def shared_status_data(
    pool: ConnectionPool,
) -> tuple[dict[str, str], tuple[float | None, dict[str, int]]]:
    """Account-wide maps shared by every host row of one /api/status."""
    return provider_hosts(pool), latest_self_route(pool)


def build_status(cfg: Config, pool: ConnectionPool, attributed: dict[str, str],
                 self_route: tuple[float | None, dict[str, int]]) -> Row:
    host = cfg.host_id
    daemon = latest_daemon(pool, host)
    now = time.time()
    demand = latest_demand_table(pool, host)
    hashes = [h for h, owner in attributed.items() if owner == host]
    routability = routability_panel(pool, host, daemon, cfg.switch_cost_seconds, self_route)
    return {
        "host": {"label": cfg.host_label, "spec": cfg.host_spec},
        "mode": "MONITOR",
        "current_model": daemon["current_model"] if daemon else None,
        "daemon_fresh": daemon["fresh"] if daemon else False,
        "inference_active": daemon["inference_active"] if daemon else None,
        "as_of": daemon["observed_at"] if daemon else None,
        "demand": demand,
        "earnings_usd_24h": round(earnings_usd(pool, now - DAY_SECONDS, now, hashes), 4),
        "earnings_usd_1h": round(earnings_usd(pool, now - 3600, now, hashes), 4),
        "serving": serving_percentages(pool, host, now),
        "recent_earnings": recent_earnings(pool, now, hashes),
        "unattributed_recent": unattributed_recent(pool, attributed, now),
        "routability": routability,
        "card": build_card(pool, host, daemon, routability["last_served_at"], hashes, now,
                           cfg.daemon_freshness_seconds),
        "hourly_jobs": hourly_jobs(pool, hashes, now),
    }
