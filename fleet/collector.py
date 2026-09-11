"""One ingestion + decision tick. Every external call is independently
try/except'd so a single failed source (SSH down, public API flaky) degrades
that part only, matching the source project's per-source resilience.
"""
from __future__ import annotations

import logging
import time

from psycopg_pool import ConnectionPool

from . import db, decision as decision_mod, demand, remote, scoring
from .config import Config
from .types import DaemonState

log = logging.getLogger("fleet.collector")


def _fetch_daemon(cfg: Config, now: float) -> DaemonState | None:
    try:
        return remote.fetch_daemon_state(cfg, now)
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("daemon state unavailable: %s", error)
        return None


def _fetch_scores(cfg: Config) -> tuple[dict, dict[str, float]]:
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
    host = cfg.host_label
    since_rowid = db.last_payout_rowid(pool, host)
    try:
        payouts = remote.fetch_new_payouts(cfg, since_rowid)
    except Exception as error:  # noqa: BLE001
        log.warning("earnings ledger unavailable: %s", error)
        return
    db.insert_payouts(pool, host, payouts, now)


def _decide(cfg: Config, pool: ConnectionPool, ema: dict[str, float], daemon: DaemonState | None, now: float):
    host = cfg.host_label
    current = daemon.current_model if daemon and daemon.fresh else None
    anchor = db.dwell_anchor(pool, host, daemon.started_at if daemon else 0.0)
    return decision_mod.decide(
        ema, current, anchor, now,
        inference_active=bool(daemon and daemon.inference_active),
        relative_margin=cfg.relative_margin, absolute_margin=cfg.absolute_margin,
        switch_cost_seconds=cfg.switch_cost_seconds, decision_horizon_seconds=cfg.decision_horizon_seconds,
        min_dwell_seconds=cfg.min_dwell_seconds,
    )


def _maybe_execute(cfg: Config, pool: ConnectionPool, decision, daemon: DaemonState | None, now: float) -> tuple[bool, str | None]:
    """Live mode only. Returns (executed, error)."""
    if decision.action != "SWITCH" or not cfg.live_execution:
        return False, None
    host = cfg.host_label
    if now - db.last_failed_switch_at(pool, host) < cfg.restart_backoff_seconds:
        return False, "restart-retry backoff: waiting after a recent failed attempt"
    fresh_daemon = _fetch_daemon(cfg, time.time())
    if not fresh_daemon or not fresh_daemon.fresh or fresh_daemon.inference_active:
        return False, "aborted: provider is not confirmed fresh and idle immediately before the switch"
    try:
        remote.execute_switch(cfg, decision.target)
    except Exception as error:  # noqa: BLE001
        return False, str(error)
    return True, None


def _maybe_launch_fast_poll(cfg: Config, decision, now: float) -> None:
    """A SWITCH_WHEN_IDLE decision means the challenger already clears every
    gate except idle. Waiting out the rest of this ~60s poll cycle risks
    missing a narrow idle gap that opens and closes between ticks - exactly
    what missed 8 consecutive ticks in a row on the real host (see README) -
    so launch the self-locking 1s-poll watcher on the remote host instead;
    it re-checks the live recommendation every second and switches the
    instant a gap opens."""
    if decision.action != "SWITCH_WHEN_IDLE":
        return
    if not cfg.live_execution:
        log.info("observe mode: would launch fast-poll watcher for target %s", decision.target)
        return
    try:
        remote.launch_fast_switch_watcher(cfg, decision.target, max_seconds=max(5.0, cfg.poll_interval_seconds - 5))
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("failed to launch fast-poll watcher: %s", error)


def run_tick(cfg: Config, pool: ConnectionPool) -> None:
    now = time.time()
    host = cfg.host_label

    daemon = _fetch_daemon(cfg, now)
    if daemon is not None:
        db.insert_daemon_snapshot(pool, host, now, daemon)

    samples, prices = _fetch_scores(cfg)
    scores = scoring.compute_scores(samples, prices, cfg.weights)

    ema_prev, last_updated = db.load_ema(pool, host)
    dt = max(1.0, now - last_updated) if last_updated else cfg.poll_interval_seconds
    ema = decision_mod.update_ema(ema_prev, scores, dt, cfg.ema_tau_minutes)
    if ema:
        db.save_ema(pool, host, ema, now)
    db.insert_demand_samples(pool, host, now, samples, scores, prices, ema)

    _ingest_earnings(cfg, pool, now)

    result = _decide(cfg, pool, ema, daemon, now)
    executed, error = _maybe_execute(cfg, pool, result, daemon, now)
    _maybe_launch_fast_poll(cfg, result, now)
    mode = "live" if cfg.live_execution else "observe"
    db.insert_decision(pool, host, now, daemon.current_model if daemon else None, result, mode, executed, error)
    log.info("[%s] %s -> %s (%s): %s", mode, daemon.current_model if daemon else "?", result.target, result.action, result.reason)
