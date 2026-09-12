"""One ingestion + decision tick. Every external call is independently
try/except'd so a single failed source (SSH down, public API flaky) degrades
that part only, matching the source project's per-source resilience.
"""
from __future__ import annotations

import logging
import time

from psycopg_pool import ConnectionPool

from . import db, demand, remote, routability, scoring
from . import decision as decision_mod
from .config import Config
from .types import CapacitySample, DaemonState, Decision, Guardrails, Outcome

log = logging.getLogger("fleet.collector")


def _fetch_daemon(cfg: Config, now: float) -> DaemonState | None:
    try:
        return remote.fetch_daemon_state(cfg, now)
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("daemon state unavailable: %s", error)
        return None


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
    host = cfg.host_label
    since_rowid = db.last_payout_rowid(pool, host)
    try:
        payouts = remote.fetch_new_payouts(cfg, since_rowid)
    except Exception as error:  # noqa: BLE001
        log.warning("earnings ledger unavailable: %s", error)
        return
    db.insert_payouts(pool, host, payouts, now)


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


def _decide(cfg: Config, pool: ConnectionPool, ema: dict[str, float], daemon: DaemonState | None, now: float) -> Decision:
    """Without a fresh daemon read neither the current model nor idleness is
    known, so the only safe decision is to wait for the next tick."""
    if daemon is None or not daemon.fresh:
        return Decision(None, "daemon state unavailable or stale", "WAIT")
    anchor = db.dwell_anchor(pool, cfg.host_label, daemon.started_at)
    # The measured post-restart penalty replaces the configured estimate once
    # enough completed sessions exist (routability.measured_switch_cost); the
    # configured value stays the fallback.
    measured = routability.measured_switch_cost(pool, cfg.host_label)
    guardrails = Guardrails(
        relative_margin=cfg.relative_margin, absolute_margin=cfg.absolute_margin,
        switch_cost_seconds=measured[0] if measured else cfg.switch_cost_seconds,
        decision_horizon_seconds=cfg.decision_horizon_seconds,
        min_dwell_seconds=cfg.min_dwell_seconds,
    )
    return decision_mod.decide(ema, daemon.current_model, anchor, now, daemon.inference_active, guardrails)


def _maybe_execute(cfg: Config, pool: ConnectionPool, decision: Decision, now: float) -> tuple[bool, str | None]:
    """Live mode only. Returns (executed, error). The restart-retry backoff is
    applied by the caller before storing the decision, so a deferred switch
    never reaches here as a SWITCH."""
    if decision.action != "SWITCH" or not cfg.live_execution:
        return False, None
    fresh_daemon = _fetch_daemon(cfg, time.time())
    if not fresh_daemon or not fresh_daemon.fresh or fresh_daemon.inference_active:
        return False, "aborted: provider is not confirmed fresh and idle immediately before the switch"
    try:
        remote.execute_switch(cfg, decision.target)
    except Exception as error:  # noqa: BLE001
        return False, str(error)
    return True, None


def _maybe_launch_fast_poll(cfg: Config, decision: Decision) -> None:
    """A SWITCH_WHEN_IDLE decision means the challenger already clears every
    gate except idle. Waiting out the rest of this ~60s poll cycle risks
    missing a narrow idle gap that opens and closes between ticks - exactly
    what missed 8 consecutive ticks in a row on the real host (see README) -
    so launch the self-locking 1s-poll watcher on the remote host instead;
    it re-checks the live recommendation every second and switches the
    instant a gap opens. Any other decision clears the watcher's target, so a
    watcher still running from an earlier tick cannot act on a stale one.
    Observe mode never launches or executes anything, but still clears a
    target left behind by an earlier live tick."""
    try:
        if not cfg.live_execution:
            if decision.action == "SWITCH_WHEN_IDLE":
                log.info("observe mode: would launch fast-poll watcher for target %s", decision.target)
            remote.remove_fast_switch_target(cfg)
            return
        if decision.action == "SWITCH_WHEN_IDLE":
            remote.launch_fast_switch_watcher(cfg, decision.target, max_seconds=max(5.0, cfg.poll_interval_seconds - 5))
        else:
            remote.clear_fast_switch_target(cfg)
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("fast-poll watcher control failed: %s", error)


def run_tick(cfg: Config, pool: ConnectionPool) -> None:
    now = time.time()
    host = cfg.host_label

    daemon = _fetch_daemon(cfg, now)
    if daemon is not None:
        db.insert_daemon_snapshot(pool, host, now, daemon)
    _probe_self_route(cfg, pool, now)
    _ingest_earnings(cfg, pool, now)

    samples, prices = _fetch_scores(cfg)
    scores = scoring.compute_scores(samples, prices, cfg.weights)
    if not scores:
        # No scored models this tick: leave the stored EMA and its timestamp
        # untouched (saving now would fake a fresh dt on the next real update)
        # and wait rather than score stale data.
        result = Decision(None, "demand feeds unavailable", "WAIT")
        _record_and_act(cfg, pool, result, daemon.current_model if daemon else None, now)
        return

    ema_prev, last_updated = db.load_ema(pool, host)
    dt = max(1.0, now - last_updated) if last_updated else cfg.poll_interval_seconds
    ema = decision_mod.update_ema(ema_prev, scores, dt, cfg.ema_tau_minutes)
    if ema:
        db.save_ema(pool, host, ema, now)
    db.insert_demand_samples(pool, host, now, samples, scores, prices, ema)

    result = _decide(cfg, pool, ema, daemon, now)
    _record_and_act(cfg, pool, result, daemon.current_model if daemon else None, now)


def _record_and_act(cfg: Config, pool: ConnectionPool, result: Decision, current_model: str | None, now: float) -> None:
    """The decision is stored before any switch is dispatched, so a crash
    mid-switch still leaves a record; the outcome is written back afterwards.
    The restart-retry backoff defers rather than fails: error must stay NULL,
    or last_failed_switch_at() would move forward every tick and the backoff
    would never end."""
    mode = "live" if cfg.live_execution else "observe"
    if (result.action == "SWITCH" and cfg.live_execution
            and now - db.last_failed_switch_at(pool, cfg.host_label) < cfg.restart_backoff_seconds):
        result = Decision(result.target, f"{result.reason}; restart-retry backoff: waiting after a recent failed attempt", "BLOCKED")
    decision_id = db.insert_decision(pool, cfg.host_label, now, current_model, result, Outcome(mode, False, None))
    executed, error = _maybe_execute(cfg, pool, result, now)
    if executed or error:
        db.record_outcome(pool, decision_id, Outcome(mode, executed, error))
    _maybe_launch_fast_poll(cfg, result)
    log.info("[%s] %s -> %s (%s): %s", mode, current_model or "?", result.target, result.action, result.reason)
