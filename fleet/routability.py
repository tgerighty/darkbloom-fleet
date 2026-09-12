"""Post-restart routability for the dashboard: what the coordinator will route
to on our machines (the self-route listing) against what each host advertises
and has warm, plus how long the current daemon session took to become routable
and to get its first request. Those two durations are the measured switch
penalty that the fixed switch-cost guardrail only estimates.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

Row = dict[str, object]


def latest_self_route(pool: ConnectionPool) -> tuple[float | None, dict[str, int]]:
    """(observed_at, routable providers by model) from the most recent probe."""
    with pool.connection() as conn:
        last = conn.execute("SELECT max(observed_at) AS t FROM self_route_samples").fetchone()
        if not last or last["t"] is None:
            return None, {}
        rows = conn.execute(
            "SELECT model, routable_providers FROM self_route_samples WHERE observed_at = %s AND model <> ''",
            (last["t"],),
        ).fetchall()
    return float(last["t"]), {str(r["model"]): int(r["routable_providers"]) for r in rows}


def session_timing(pool: ConnectionPool, host: str, started_at: float) -> Row:
    """Minutes from the daemon's start to the first probe that listed anything
    routable on ANY of our hosts, and to this host's first served request.
    The probe is account-wide, so the first figure is a lower bound for this
    host (another host may be the routable one); the request counter is this
    host's own and is the reliable per-host penalty measure."""
    with pool.connection() as conn:
        routable = conn.execute(
            "SELECT min(observed_at) AS t FROM self_route_samples "
            "WHERE observed_at >= %s AND routable_providers > 0",
            (started_at,),
        ).fetchone()
        served = conn.execute(
            "SELECT min(observed_at) AS t FROM daemon_snapshots "
            "WHERE host = %s AND started_at = %s AND requests_served > 0",
            (host, started_at),
        ).fetchone()

    def minutes(row: Row | None) -> float | None:
        return round((float(row["t"]) - started_at) / 60, 1) if row and row["t"] is not None else None

    return {
        "started_at": started_at,
        "any_host_routable_after_min": minutes(routable),
        "first_request_after_min": minutes(served),
    }


def last_served(pool: ConnectionPool, host: str) -> dict[str, float]:
    """When each model last served on this host: the latest snapshot whose
    request counter rose since the previous one in the same daemon session.
    current_model is the most recently used model, so it names the server."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT current_model AS model, max(observed_at) AS t FROM ("
            "  SELECT observed_at, current_model, requests_served"
            "    - lag(requests_served) OVER (PARTITION BY started_at ORDER BY observed_at) AS delta"
            "  FROM daemon_snapshots WHERE host = %s) d "
            "WHERE delta > 0 AND current_model IS NOT NULL GROUP BY current_model",
            (host,),
        ).fetchall()
    return {str(r["model"]): float(r["t"]) for r in rows}


def _our_id(model: str, known: set[str]) -> str:
    """The coordinator's self-route listing uses short ids (`gemma-4-26b`)
    while our configured ids carry quantization suffixes (`gemma-4-26b-qat-4bit`):
    a coordinator id names the known model that equals it or extends it with
    one more `-` part."""
    return next((m for m in sorted(known) if m == model or m.startswith(model + "-")), model)


def _aliased_counts(counts: dict[str, int], known: set[str]) -> dict[str, int]:
    """Re-key the self-route counts onto our advertised/warm ids, so one model
    is one dashboard row; a coordinator id matching nothing known keeps its
    own row."""
    return {_our_id(model, known): n for model, n in counts.items()}


def _switch_cost_sessions(pool: ConnectionPool, host: str) -> tuple[float | None, int]:
    """(median seconds from daemon start to first served request, how many
    sessions that covers) over the host's last 10 sessions that served at
    least one request. A session is one distinct started_at; its delay is
    complete the moment the first request arrives, so a session still waiting
    (or one that never serves) simply drops out."""
    with pool.connection() as conn:
        row = conn.execute(
            "WITH sessions AS ("
            "  SELECT started_at, min(observed_at) FILTER (WHERE requests_served > 0) - started_at AS delay"
            "  FROM daemon_snapshots WHERE host = %s GROUP BY started_at), "
            "served AS (SELECT delay FROM sessions WHERE delay IS NOT NULL"
            "  ORDER BY started_at DESC LIMIT 10) "
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY delay) AS median, count(*) AS n FROM served",
            (host,),
        ).fetchone()
    median = round(float(row["median"]), 1) if row and row["median"] is not None else None
    return median, int(row["n"]) if row else 0


def measured_switch_cost(pool: ConnectionPool, host: str) -> tuple[float, int] | None:
    """The measured post-restart penalty the switch-cost guardrail uses in
    place of the fixed DARKBLOOM_SWITCH_COST_SECONDS estimate: (median
    seconds, session count), or None until 3 sessions have served a request —
    fewer would make the median noise."""
    median, n = _switch_cost_sessions(pool, host)
    return (median, n) if median is not None and n >= 3 else None


def routability_panel(pool: ConnectionPool, host: str, daemon: Row | None, switch_cost_seconds: float) -> Row:
    as_of, counts = latest_self_route(pool)
    served = last_served(pool, host)
    snapshot = daemon or {}
    advertised = set(snapshot.get("advertised_models") or [])
    warm = set(snapshot.get("warm_models") or [])
    counts = _aliased_counts(counts, advertised | warm)
    started_at = float(snapshot.get("started_at") or 0)
    median, n = _switch_cost_sessions(pool, host)
    return {
        "self_route_as_of": as_of,
        # The coordinator only routes to hardware-trusted providers; after a
        # restart the level drops to self_signed until MDM and Apple device
        # attestation re-verify. One of the per-host penalty-box signals.
        "trust_level": snapshot.get("trust_level"),
        "trust_reason": snapshot.get("trust_reason"),
        "last_served_at": max(served.values()) if served else None,
        "models": [
            {"model": m, "advertised": m in advertised, "warm": m in warm,
             "routable_providers": counts.get(m, 0), "last_served_at": served.get(m)}
            for m in sorted(advertised | warm | set(counts) | set(served))
        ],
        "session": session_timing(pool, host, started_at) if started_at else None,
        "switch_cost": {"configured_seconds": switch_cost_seconds,
                        "measured_seconds": median, "measured_sessions": n},
    }
