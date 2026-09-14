"""Postgres schema + connection pool. v1 is single-host, so every table
carries a plain `host` column (the immutable host id, not the display label)
rather than a hosts table — no join, no multi-host abstraction to build yet
(see README "v1 scope").
"""
from __future__ import annotations

import dataclasses

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .types import CapacitySample, DaemonState, Decision, Outcome, Payout

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS demand_samples (
    id BIGSERIAL PRIMARY KEY,
    host TEXT NOT NULL,
    observed_at DOUBLE PRECISION NOT NULL,
    model TEXT NOT NULL,
    active_requests INTEGER NOT NULL,
    warm_providers INTEGER NOT NULL,
    pressure DOUBLE PRECISION NOT NULL,
    output_usd_per_million DOUBLE PRECISION,
    score DOUBLE PRECISION,
    ema_score DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS demand_samples_host_model_time
    ON demand_samples (host, model, observed_at DESC);

CREATE TABLE IF NOT EXISTS switch_lease (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    owner TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS daemon_snapshots (
    id BIGSERIAL PRIMARY KEY,
    host TEXT NOT NULL,
    observed_at DOUBLE PRECISION NOT NULL,
    current_model TEXT,
    warm_models TEXT[] NOT NULL DEFAULT '{}',
    inference_active BOOLEAN NOT NULL,
    fresh BOOLEAN NOT NULL,
    pid INTEGER NOT NULL DEFAULT 0,
    started_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS daemon_snapshots_host_time
    ON daemon_snapshots (host, observed_at DESC);
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS advertised_models TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS requests_served BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS trust_level TEXT;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS trust_reason TEXT;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS thermal_state TEXT;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS memory_pressure DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS cpu_usage DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS fan_rpm DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS peak_temperature_c DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS gpu_active_gb DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS gpu_cache_gb DOUBLE PRECISION;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS total_memory_gb DOUBLE PRECISION;
-- One JSON array of {model, kv_backend, mtp_enabled, mtp_active, mtp_inactive_reason}
-- per snapshot: the daemon's resident model slots for the backend-slots panel.
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS slots JSONB;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS last_model_load_error_model TEXT;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS last_model_load_error_message TEXT;
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS last_model_load_error_at DOUBLE PRECISION;
-- Nullable: NULL = inventory unknown this tick; '{}' = verified empty cache.
ALTER TABLE daemon_snapshots ADD COLUMN IF NOT EXISTS installed_models TEXT[];

-- One row per model the coordinator will route to on our machines, per probe.
-- A probe that found nothing routable writes one row with model = '' so the
-- gap itself is recorded: that gap is the post-restart penalty box.
CREATE TABLE IF NOT EXISTS self_route_samples (
    id BIGSERIAL PRIMARY KEY,
    observed_at DOUBLE PRECISION NOT NULL,
    model TEXT NOT NULL,
    routable_providers INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS self_route_samples_time ON self_route_samples (observed_at DESC);

CREATE TABLE IF NOT EXISTS earnings (
    host TEXT NOT NULL,
    payout_rowid BIGINT NOT NULL,
    model TEXT NOT NULL,
    completion_tokens BIGINT NOT NULL,
    micro_usd BIGINT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    ingested_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (host, payout_rowid)
);
CREATE INDEX IF NOT EXISTS earnings_host_time ON earnings (host, created_at DESC);
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS provider_hash TEXT;

CREATE TABLE IF NOT EXISTS ema_state (
    host TEXT NOT NULL,
    model TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (host, model)
);

CREATE TABLE IF NOT EXISTS decisions (
    id BIGSERIAL PRIMARY KEY,
    host TEXT NOT NULL,
    observed_at DOUBLE PRECISION NOT NULL,
    current_model TEXT,
    target_model TEXT,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    mode TEXT NOT NULL,
    executed BOOLEAN NOT NULL DEFAULT false,
    error TEXT
);
CREATE INDEX IF NOT EXISTS decisions_host_time ON decisions (host, observed_at DESC);
"""


def get_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(database_url, min_size=1, max_size=4, kwargs={"row_factory": dict_row})


def init_schema(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute(SCHEMA_SQL)


def insert_demand_samples(pool: ConnectionPool, host: str, observed_at: float,
                           samples: dict[str, CapacitySample], scores: dict[str, float],
                           prices: dict[str, float], ema: dict[str, float]) -> None:
    rows = [
        (host, observed_at, model, s.active_requests, s.warm_providers, s.pressure,
         prices.get(model), scores.get(model), ema.get(model))
        for model, s in samples.items()
    ]
    if not rows:
        return
    with pool.connection() as conn:
        conn.cursor().executemany(
            "INSERT INTO demand_samples (host, observed_at, model, active_requests, warm_providers, "
            "pressure, output_usd_per_million, score, ema_score) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )


def update_snapshot_installed_models(
    pool: ConnectionPool, host: str, observed_at: float, installed: tuple[str, ...],
) -> None:
    """Fill installed_models on the snapshot just inserted for this tick."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE daemon_snapshots SET installed_models = %s WHERE host = %s AND observed_at = %s",
            (list(installed), host, observed_at),
        )


def acquire_switch_lease(pool: ConnectionPool, owner: str, now: float, ttl_seconds: float) -> bool:
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO switch_lease (singleton, owner, expires_at) VALUES (true, %s, %s) "
            "ON CONFLICT (singleton) DO UPDATE SET owner = EXCLUDED.owner, expires_at = EXCLUDED.expires_at "
            "WHERE switch_lease.expires_at < %s RETURNING owner",
            (owner, now + ttl_seconds, now),
        ).fetchone()
    return bool(row and row["owner"] == owner)


def release_switch_lease(pool: ConnectionPool, owner: str) -> None:
    with pool.connection() as conn:
        conn.execute("DELETE FROM switch_lease WHERE owner = %s", (owner,))


def insert_daemon_snapshot(pool: ConnectionPool, host: str, observed_at: float, daemon: DaemonState) -> None:
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO daemon_snapshots (host, observed_at, current_model, warm_models, "
            "inference_active, fresh, pid, started_at, advertised_models, requests_served, "
            "trust_level, trust_reason, thermal_state, memory_pressure, cpu_usage, fan_rpm, "
            "peak_temperature_c, gpu_active_gb, gpu_cache_gb, total_memory_gb, "
            "last_model_load_error_model, last_model_load_error_message, last_model_load_error_at, "
            "installed_models, slots) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (host, observed_at, daemon.current_model, list(daemon.warm_models),
             daemon.inference_active, daemon.fresh, daemon.pid, daemon.started_at,
             list(daemon.advertised_models), daemon.requests_served, daemon.trust_level, daemon.trust_reason,
             daemon.thermal_state, daemon.memory_pressure, daemon.cpu_usage, daemon.fan_rpm,
             daemon.peak_temperature_c, daemon.gpu_active_gb, daemon.gpu_cache_gb, daemon.total_memory_gb,
             daemon.last_model_load_error_model, daemon.last_model_load_error_message,
             daemon.last_model_load_error_at,
             None if daemon.installed_models is None else list(daemon.installed_models),
             Jsonb([dataclasses.asdict(s) for s in daemon.slots])),
        )


def insert_self_route_samples(pool: ConnectionPool, observed_at: float, counts: dict[str, int]) -> None:
    rows = [(observed_at, model, n) for model, n in counts.items()] or [(observed_at, "", 0)]
    with pool.connection() as conn:
        conn.cursor().executemany(
            "INSERT INTO self_route_samples (observed_at, model, routable_providers) VALUES (%s,%s,%s)", rows
        )


def insert_payouts(pool: ConnectionPool, host: str, payouts: list[Payout], now: float) -> None:
    if not payouts:
        return
    rows = [(host, p.rowid, p.model, p.completion_tokens, p.micro_usd, p.created_at, p.provider_hash, now)
            for p in payouts]
    with pool.connection() as conn:
        conn.cursor().executemany(
            "INSERT INTO earnings (host, payout_rowid, model, completion_tokens, micro_usd, created_at, "
            "provider_hash, ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (host, payout_rowid) DO NOTHING",
            rows,
        )


def last_payout_rowid(pool: ConnectionPool, host: str) -> int:
    with pool.connection() as conn:
        row = conn.execute("SELECT max(payout_rowid) AS m FROM earnings WHERE host = %s", (host,)).fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0


def load_ema(pool: ConnectionPool, host: str) -> tuple[dict[str, float], float]:
    """Returns (ema_by_model, last_updated_at). last_updated_at is 0 when unset."""
    with pool.connection() as conn:
        rows = conn.execute("SELECT model, value, updated_at FROM ema_state WHERE host = %s", (host,)).fetchall()
    if not rows:
        return {}, 0.0
    return {r["model"]: r["value"] for r in rows}, max(r["updated_at"] for r in rows)


def delete_ineligible_ema(pool: ConnectionPool, host: str, eligible: frozenset[str]) -> None:
    """Drop ema_state rows for this host that are not in eligible. Does not
    bump updated_at on the rows that remain. An empty set deletes every row."""
    with pool.connection() as conn:
        if eligible:
            conn.execute(
                "DELETE FROM ema_state WHERE host = %s AND NOT (model = ANY(%s))",
                (host, list(eligible)),
            )
        else:
            conn.execute("DELETE FROM ema_state WHERE host = %s", (host,))


def save_ema(pool: ConnectionPool, host: str, ema: dict[str, float], updated_at: float) -> None:
    rows = [(host, model, value, updated_at) for model, value in ema.items()]
    if not rows:
        return
    with pool.connection() as conn:
        conn.cursor().executemany(
            "INSERT INTO ema_state (host, model, value, updated_at) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (host, model) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            rows,
        )


def dwell_anchor(pool: ConnectionPool, host: str, daemon_started_at: float) -> float:
    """The later of: this service's last executed switch, or the daemon
    process's own start time (an externally-triggered restart also resets
    residency). 0 means "no anchor; nothing to protect yet"."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT max(observed_at) AS t FROM decisions WHERE host = %s AND executed = true", (host,)
        ).fetchone()
    return max(row["t"] or 0.0, daemon_started_at or 0.0)


def last_failed_switch_at(pool: ConnectionPool, host: str) -> float:
    """Most recent SWITCH attempt that errored, for the restart-retry backoff."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT max(observed_at) AS t FROM decisions WHERE host = %s AND action = 'SWITCH' AND error IS NOT NULL",
            (host,),
        ).fetchone()
    return row["t"] or 0.0


def insert_decision(pool: ConnectionPool, host: str, observed_at: float, current_model: str | None,
                     decision: Decision, outcome: Outcome) -> int:
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO decisions (host, observed_at, current_model, target_model, action, reason, "
            "mode, executed, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (host, observed_at, current_model, decision.target, decision.action, decision.reason,
             outcome.mode, outcome.executed, outcome.error),
        ).fetchone()
    return int(row["id"])


def record_outcome(pool: ConnectionPool, decision_id: int, outcome: Outcome) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE decisions SET mode = %s, executed = %s, error = %s WHERE id = %s",
            (outcome.mode, outcome.executed, outcome.error, decision_id),
        )
