"""Console-style per-host card for the dashboard: status band, resources,
GPU memory, loaded/catalog chips, KPI tiles and backend-slot rows, assembled
from the latest daemon snapshot plus the attribution-filtered session payout
totals. Exposed by queries.build_status under "card" so the page needs no
extra endpoint. Kept here to keep queries.py small and single-purpose.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

from .attribution import unique_payouts_sql
from .types import LOAD_ERROR_BLOCK_SECONDS

Row = dict[str, object]

# darkbloom.dev shows "receiving traffic" while a request landed in the last
# 10 minutes; our minute-cadence snapshots make that inference_active now or
# a request counter that rose at most this long ago.
RECENT_TRAFFIC_SECONDS = 600
HARDWARE_TRUST = "hardware"
PRIORITY = "normal"  # every managed Mac routes at full priority today


def _served_recently(snapshot: Row, last_served_at: float | None, now: float) -> bool:
    if snapshot.get("inference_active"):
        return True
    return last_served_at is not None and now - last_served_at <= RECENT_TRAFFIC_SECONDS


def _status_band(snapshot: Row, last_served_at: float | None, now: float) -> Row:
    """The card's top band: OFF beats nothing, STALE beats everything (a stale
    read is not authoritative about trust or traffic), then trust decides."""
    if not snapshot:
        return {"state": "OFF", "tone": "red", "detail": "no daemon snapshot — host offline or not yet polled",
                "priority": PRIORITY}
    if not snapshot.get("fresh"):
        return {"state": "STALE", "tone": "red", "detail": "daemon state not fresh — last read is not authoritative",
                "priority": PRIORITY}
    if snapshot.get("trust_level") == HARDWARE_TRUST:
        if _served_recently(snapshot, last_served_at, now):
            return {"state": "EARNING", "tone": "green", "detail": "Full routing priority — no action needed.",
                    "priority": PRIORITY}
        return {"state": "TRUSTED", "tone": "amber",
                "detail": "Hardware trust held — no request served in the last 10 minutes.", "priority": PRIORITY}
    return {"state": "ATTESTING", "tone": "amber",
            "detail": "Trust re-attestation in progress — no public traffic until hardware trust returns.",
            "priority": PRIORITY}


def _gpu(snapshot: Row) -> Row:
    """GPU memory block plus the peak figure the slots panel tiles: cache sits
    on top of active, so peak is whichever of active and cache+active is larger."""
    active = snapshot.get("gpu_active_gb")
    cache = snapshot.get("gpu_cache_gb")
    peak = None
    if active is not None:
        peak = max(float(active), float(active) + float(cache or 0.0))
    return {"active_gb": active, "cache_gb": cache, "total_gb": snapshot.get("total_memory_gb"), "peak_gb": peak}


def _load_error(snapshot: Row, now: float) -> Row | None:
    """Last daemon load failure, or None when every field is missing."""
    model = snapshot.get("last_model_load_error_model")
    message = snapshot.get("last_model_load_error_message")
    at = snapshot.get("last_model_load_error_at")
    if model is None and message is None and at is None:
        return None
    age = None
    try:
        age = now - float(at) if at is not None else None
    except (TypeError, ValueError):
        age = None
    return {"model": model, "message": message, "at": at,
            "recent": age is not None and abs(age) <= LOAD_ERROR_BLOCK_SECONDS}


def _loaded(snapshot: Row) -> list[Row]:
    """Warm models as chips; the current one is marked active while a request
    is actually in flight on it."""
    busy = bool(snapshot.get("inference_active"))
    current = snapshot.get("current_model")
    return [{"model": m, "active": busy and m == current} for m in (snapshot.get("warm_models") or [])]


_SESSION_TOTALS_SQL = (
    "SELECT coalesce(sum(completion_tokens), 0) AS tokens, count(*) AS requests FROM ("
    + unique_payouts_sql(
        "completion_tokens",
        "created_at > %s AND created_at <= %s AND provider_hash = ANY(%s)",
    )
    + ") unique_payouts"
)


def session_totals(pool: ConnectionPool, since: float, now: float, hashes: list[str]) -> Row:
    """Tokens paid out and unique payout-row count for this host's attributed
    sessions since `since` — the TOKENS tile's value and its "n reqs" sub."""
    with pool.connection() as conn:
        row = conn.execute(_SESSION_TOTALS_SQL, (since, now, hashes)).fetchone()
    return {"tokens": int(row["tokens"]), "requests": int(row["requests"])}


def build_card(pool: ConnectionPool, host: str, daemon: Row | None,
               last_served_at: float | None, hashes: list[str], now: float) -> Row:
    snapshot = daemon or {}
    started_at = float(snapshot.get("started_at") or 0)
    totals = session_totals(pool, started_at, now, hashes)
    return {
        "status": _status_band(snapshot, last_served_at, now),
        "resources": {"thermal_state": snapshot.get("thermal_state"),
                      "memory_pressure": snapshot.get("memory_pressure"),
                      "cpu_usage": snapshot.get("cpu_usage")},
        "gpu": _gpu(snapshot),
        "loaded": _loaded(snapshot),
        "catalog": list(snapshot.get("advertised_models") or []),
        "kpis": {"requests": int(snapshot.get("requests_served") or 0),
                 "tokens": totals["tokens"], "token_requests": totals["requests"],
                 "started_at": started_at or None, "last_served_at": last_served_at},
        "slots": list(snapshot.get("slots") or []),
        "last_model_load_error": _load_error(snapshot, now),
    }
