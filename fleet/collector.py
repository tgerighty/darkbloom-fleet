"""One read-only ingestion tick. Every external call is independently
try/except'd so a single failed source (SSH down, public API flaky) degrades
that part only, matching the source project's per-source resilience.
"""
from __future__ import annotations

import dataclasses
import logging
import time

from psycopg_pool import ConnectionPool

from . import db, demand, remote, scoring
from .config import Config
from .types import CapacitySample, DaemonState

log = logging.getLogger("fleet.collector")


def _fetch_daemon(cfg: Config, now: float) -> DaemonState | None:
    try:
        return remote.fetch_daemon_state(cfg, now)
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("daemon state unavailable: %s", error)
        return None


def _fetch_installed(cfg: Config) -> tuple[str, ...] | None:
    """Verified on-disk ids, or None when inventory is unknown this tick."""
    try:
        return remote.fetch_installed_models(cfg)
    except Exception as error:  # noqa: BLE001 - must not stall or fail daemon state
        log.warning("installed-model inventory unknown: %s", error)
        return None


def _eligible_models(configured: tuple[str, ...], installed: tuple[str, ...] | None) -> frozenset[str]:
    """Configured allow-list, intersected with on-disk ids when inventory is
    known. Unknown inventory still scores the allow-list. Disk-only ids
    are never enrolled."""
    if installed is None:
        return frozenset(configured)
    return frozenset(configured) & frozenset(installed)


def _fetch_scores(cfg: Config) -> tuple[dict[str, CapacitySample], dict[str, float]]:
    """Returns (capacity samples by model, resolved price by model)."""
    try:
        samples = demand.fetch_capacity(cfg.base_url)
    except Exception as error:  # noqa: BLE001
        log.warning("public demand feed unavailable: %s", error)
        samples = {}
    try:
        raw_prices, fallback = demand.fetch_output_prices(cfg.pricing_url)
        prices = demand.resolve_prices(cfg.models, raw_prices, fallback)
    except Exception as error:  # noqa: BLE001
        log.warning("pricing feed unavailable: %s", error)
        prices = {}
    return {m: s for m, s in samples.items() if m in cfg.models}, prices


def _ingest_earnings(cfg: Config, pool: ConnectionPool, now: float) -> None:
    host = cfg.host_id
    since_rowid = db.last_payout_rowid(pool, host)
    try:
        payouts = remote.fetch_new_payouts(cfg, since_rowid)
    except Exception as error:  # noqa: BLE001
        log.warning("earnings ledger unavailable: %s", error)
        return
    db.insert_payouts(pool, host, payouts, now)


def _ingest_provider_identity(cfg: Config, pool: ConnectionPool, daemon: DaemonState | None) -> None:
    if not (cfg.api_key and daemon and daemon.fresh and daemon.attestation_public_key):
        return
    try:
        hashes = demand.fetch_provider_hashes(cfg.base_url, cfg.api_key, daemon.attestation_public_key)
        with pool.connection() as conn:
            conn.cursor().executemany(
                "INSERT INTO provider_identities (provider_hash, host) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                [(digest, cfg.host_id) for digest in sorted(hashes)],
            )
    except Exception:  # identity failure must not stop ingestion or expose authenticated responses
        log.warning("provider payout identity unavailable for %s", cfg.host_id)


def _probe_self_route(cfg: Config, pool: ConnectionPool, now: float) -> None:
    """Once per tick, from one host only (the view is account-wide): what the
    coordinator will route to on our machines. This is the penalty-box
    detector, so a probe that finds nothing routable is recorded too."""
    if not (cfg.probe_self_route and cfg.api_key):
        return
    try:
        counts = demand.fetch_self_route(cfg.base_url, cfg.api_key)
    except Exception as error:  # noqa: BLE001
        log.warning("self-route probe unavailable: %s", error)
        return
    db.insert_self_route_samples(pool, now, counts)


def _persist_tick_daemon(
    cfg: Config, pool: ConnectionPool, host: str, now: float,
) -> tuple[DaemonState | None, tuple[str, ...] | None]:
    """Insert the daemon row as soon as it is readable. Inventory is a second
    SSH and must not stall that insert, or run at all when the daemon read
    failed. Scoring uses the in-memory installed ids."""
    daemon = _fetch_daemon(cfg, now)
    if daemon is None:
        return None, None
    db.insert_daemon_snapshot(pool, host, now, daemon)
    installed = _fetch_installed(cfg)
    if installed is not None:
        db.update_snapshot_installed_models(pool, host, now, installed)
    return dataclasses.replace(daemon, installed_models=installed), installed


def run_tick(cfg: Config, pool: ConnectionPool) -> None:
    now = time.time()
    host = cfg.host_id

    daemon, installed = _persist_tick_daemon(cfg, pool, host, now)
    _probe_self_route(cfg, pool, now)
    _ingest_earnings(cfg, pool, now)
    _ingest_provider_identity(cfg, pool, daemon)

    eligible = _eligible_models(cfg.models, installed)
    db.delete_ineligible_ema(pool, host, eligible)
    if not eligible:
        # Verified empty cache, or no overlap with the allow-list: do not
        # score disk-only models and do not advance EMA freshness.
        return

    samples, prices = _fetch_scores(cfg)
    samples = {model: sample for model, sample in samples.items() if model in eligible}
    scores = scoring.compute_scores(samples, prices, cfg.weights)
    if not scores:
        # No scored models this tick: leave the stored EMA and its timestamp
        # untouched (saving now would fake a fresh dt on the next real update)
        # and wait rather than score stale data.
        return

    ema_prev, last_updated = db.load_ema(pool, host)
    # A model removed from DARKBLOOM_HOST_<N>_MODELS or missing from disk
    # must not survive in the restored EMA — its stale score would distort the demand history.
    ema_prev = {model: value for model, value in ema_prev.items() if model in eligible}
    dt = max(1.0, now - last_updated) if last_updated else cfg.poll_interval_seconds
    ema = scoring.update_ema(ema_prev, scores, dt, cfg.ema_tau_minutes)
    if ema:
        db.save_ema(pool, host, ema, now)
    db.insert_demand_samples(pool, host, now, samples, scores, prices, ema)
