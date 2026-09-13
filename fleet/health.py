"""Per-host health from daemon_snapshots and demand_samples.

Severity, worst first: DAEMON_DOWN, DEAD_SESSION, THRASH, STALE, HEALTHY.
The dashboard badge reads this dict; the card status band is unchanged.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

Row = dict[str, object]

DAEMON_DOWN = "DAEMON_DOWN"
DEAD_SESSION = "DEAD_SESSION"
THRASH = "THRASH"
STALE = "STALE"
HEALTHY = "HEALTHY"
HARDWARE = "hardware"

DOWN_AFTER = 120.0          # not-fresh for more than 2 consecutive minutes
SESSION_AGE = 1800.0        # dead session: age > 30 min with 0 served
WARM_FLIPS = 6              # thrash: more than 6 warm-set changes in 1 h
FROZEN_FOR = 300.0          # thrash: inference_active > 5 min, counter frozen
HOUR = 3600.0

_STALE_SQL = (
    "SELECT max(observed_at) FILTER (WHERE fresh) AS last_fresh, "
    "min(observed_at) AS first_seen FROM daemon_snapshots WHERE host = %s"
)
_DEAD_SQL = (
    "SELECT (SELECT coalesce(max(active_requests), 0) FROM demand_samples "
    " WHERE host = %s AND observed_at >= %s AND model = ANY(%s)) AS n, "
    "EXISTS (SELECT 1 FROM ("
    "  SELECT requests_served - lag(requests_served) OVER "
    "    (PARTITION BY host, started_at ORDER BY observed_at) AS delta "
    "  FROM daemon_snapshots WHERE host <> %s AND observed_at >= %s"
    ") d WHERE delta > 0) AS other_served"
)
_RECENT_SQL = (
    "SELECT observed_at, warm_models, inference_active, requests_served "
    "FROM daemon_snapshots WHERE host = %s AND observed_at >= %s "
    "ORDER BY observed_at"
)


def _result(state: str, since: float, detail: str) -> Row:
    return {"state": state, "since": since, "detail": detail}


def host_health(pool: ConnectionPool, host_id: str, daemon_row: Row | None, now: float) -> Row:
    snapshot = daemon_row or {}
    if not snapshot:
        return _result(STALE, now, "No daemon snapshot is available.")
    if snapshot.get("fresh"):
        return _dead_session(pool, host_id, snapshot, now) or _thrash(pool, host_id, now) or _healthy(snapshot, now)
    down = _down_or_stale(pool, host_id, now)
    if down["state"] == DAEMON_DOWN:
        return down
    return _thrash(pool, host_id, now) or down


def _healthy(snapshot: Row, now: float) -> Row:
    return _result(HEALTHY, float(snapshot.get("observed_at") or now),
                   "The daemon is fresh and no fault is detected.")


def _down_or_stale(pool: ConnectionPool, host_id: str, now: float) -> Row:
    with pool.connection() as conn:
        row = conn.execute(_STALE_SQL, (host_id,)).fetchone() or {}
    marker = row.get("last_fresh")
    if marker is None:
        marker = row.get("first_seen")
    since = float(marker) if marker is not None else now
    if now - since > DOWN_AFTER:
        return _result(DAEMON_DOWN, since, "The provider daemon is not fresh for more than 2 minutes.")
    return _result(STALE, since, "The daemon snapshot is not fresh.")


def _dead_candidate(snapshot: Row, now: float) -> float | None:
    started = float(snapshot.get("started_at") or 0)
    models = snapshot.get("advertised_models") or []
    if snapshot.get("trust_level") != HARDWARE:
        return None
    if int(snapshot.get("requests_served") or 0) or not started or not models:
        return None
    if now - started <= SESSION_AGE:
        return None
    return started


def _dead_signals(pool: ConnectionPool, host_id: str, started: float, models: list[str]) -> tuple[int, bool]:
    with pool.connection() as conn:
        row = conn.execute(_DEAD_SQL, (host_id, started, models, host_id, started)).fetchone()
    if not row:
        return 0, False
    return int(row["n"]), bool(row["other_served"])


def _dead_session(pool: ConnectionPool, host_id: str, snapshot: Row, now: float) -> Row | None:
    started = _dead_candidate(snapshot, now)
    if started is None:
        return None
    n, other = _dead_signals(pool, host_id, started, list(snapshot.get("advertised_models") or []))
    if n <= 0 or not other:
        return None
    minutes = int((now - started) / 60)
    return _result(DEAD_SESSION, started,
                   f"This session is {minutes} minutes old, served 0 requests, and the network has demand.")


def _thrash(pool: ConnectionPool, host_id: str, now: float) -> Row | None:
    with pool.connection() as conn:
        rows = conn.execute(_RECENT_SQL, (host_id, now - HOUR)).fetchall()
    flips, since = _warm_flips(rows)
    if since is not None:
        return _result(THRASH, since, f"The warm model set changed {flips} times in the last hour.")
    frozen = _frozen_since(rows, now)
    if frozen is not None:
        return _result(THRASH, frozen, "Inference is active for more than 5 minutes with no new request.")
    return None


def _warm_flips(rows: list[Row]) -> tuple[int, float | None]:
    prev: frozenset[str] | None = None
    flips = 0
    since: float | None = None
    for row in rows:
        warm = frozenset(row.get("warm_models") or ())
        if prev is not None and warm != prev:
            flips += 1
            if flips > WARM_FLIPS:
                since = float(row["observed_at"])
        prev = warm
    return flips, since


def _step_frozen(active: bool, n: int, t: float,
                 start: float | None, served: int | None) -> tuple[float | None, int | None]:
    if not active:
        return None, None
    if start is None or n != served:
        return t, n
    return start, n


def _frozen_since(rows: list[Row], now: float) -> float | None:
    start: float | None = None
    served: int | None = None
    found: float | None = None
    for row in rows:
        t = float(row["observed_at"])
        start, served = _step_frozen(bool(row.get("inference_active")),
                                     int(row.get("requests_served") or 0), t, start, served)
        if start is not None and t - start > FROZEN_FOR:
            found = start
    if start is not None and now - start > FROZEN_FOR:
        found = start
    return found
