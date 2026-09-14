"""One ingestion + decision tick. Every external call is independently
try/except'd so a single failed source (SSH down, public API flaky) degrades
that part only, matching the source project's per-source resilience.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time

from psycopg_pool import ConnectionPool

from . import attribution, db, demand, payout_decision, remote, routability, scoring
from . import decision as decision_mod
from .config import Config
from .types import CapacitySample, DaemonState, Decision, Guardrails, Outcome

log = logging.getLogger("fleet.collector")
_SWITCH_LOCK = threading.Lock()
_SWITCH_LEASE_SECONDS = 1800.0
_PAYOUT_REFRESH_SECONDS = 900.0
_PAYOUT_CACHE: dict[str, tuple[float, dict[tuple[str, ...], tuple[float, float]], float]] = {}


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


def _fetch_model_memory(cfg: Config) -> dict[str, float] | None:
    try:
        return remote.fetch_model_memory(cfg)
    except Exception as error:  # noqa: BLE001
        log.warning("installed-model memory inventory unknown: %s", error)
        return None


def _eligible_models(configured: tuple[str, ...], installed: tuple[str, ...] | None) -> frozenset[str]:
    """Configured allow-list, intersected with on-disk ids when inventory is
    known. Unknown inventory still scores the allow-list; apply_inventory_gate
    forbids SWITCH until inventory is known. Disk-only ids are never enrolled."""
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


def _rank(cfg: Config, ema: dict[str, float], daemon: DaemonState,
          anchor: float, now: float, guardrails: Guardrails) -> Decision:
    if (daemon.total_memory_gb or 0) >= cfg.dual_model_min_gb:
        memory = _fetch_model_memory(cfg)
        if memory is None:
            return Decision(daemon.current_model, "model memory inventory unavailable", "WAIT")
        return decision_mod.decide_pair(ema, daemon, anchor, now, guardrails, memory)
    return decision_mod.decide(ema, daemon.current_model, anchor, now, daemon.inference_active, guardrails)


def _decide(cfg: Config, pool: ConnectionPool, ema: dict[str, float], daemon: DaemonState | None, now: float) -> Decision:
    """Return a gated model decision from one fresh provider snapshot."""
    if daemon is None or not daemon.fresh:
        return Decision(None, "daemon state unavailable or stale", "WAIT")
    anchor = db.dwell_anchor(pool, cfg.host_id, daemon.started_at)
    measured = routability.measured_switch_cost(pool, cfg.host_id)
    guardrails = Guardrails(
        relative_margin=cfg.relative_margin, absolute_margin=cfg.absolute_margin,
        switch_cost_seconds=measured[0] if measured else cfg.switch_cost_seconds,
        decision_horizon_seconds=cfg.decision_horizon_seconds,
        min_dwell_seconds=cfg.min_dwell_seconds,
    )
    result = _rank(cfg, ema, daemon, anchor, now, guardrails)
    result = decision_mod.apply_warm_target_gate(result, daemon)
    result = decision_mod.apply_host_gates(result, daemon, now)
    return decision_mod.apply_inventory_gate(result, daemon)


def _maybe_execute(cfg: Config, pool: ConnectionPool, decision: Decision, now: float) -> tuple[bool, str | None]:
    """Live mode only. Returns (executed, error). The restart-retry backoff is
    applied by the caller before storing the decision, so a deferred switch
    never reaches here as a SWITCH. Re-runs thermal/trust/load-error on a
    fresh daemon read, then re-checks on-disk inventory before the start."""
    if decision.action != "SWITCH" or not cfg.live_execution:
        return False, None
    with _SWITCH_LOCK:
        lease_owner = f"{cfg.host_id}:{time.time_ns()}"
        if pool is not None and not db.acquire_switch_lease(pool, lease_owner, _SWITCH_LEASE_SECONDS):
            return False, "aborted: another host cold boot is in progress"
        try:
            return _execute_with_lease(cfg, decision)
        finally:
            if pool is not None:
                db.release_switch_lease(pool, lease_owner)


def _execute_with_lease(cfg: Config, decision: Decision) -> tuple[bool, str | None]:
    fresh_now = time.time()
    fresh_daemon = _fetch_daemon(cfg, fresh_now)
    if not fresh_daemon or not fresh_daemon.fresh or fresh_daemon.inference_active:
        return False, "aborted: provider is not confirmed fresh and idle immediately before the switch"
    gated = decision_mod.apply_warm_target_gate(decision, fresh_daemon)
    gated = decision_mod.apply_host_gates(gated, fresh_daemon, fresh_now)
    if gated.action != "SWITCH":
        return False, "aborted: host safety gate failed on the fresh daemon read"
    installed = _fetch_installed(cfg)
    gated = decision_mod.apply_inventory_gate(
        gated, dataclasses.replace(fresh_daemon, installed_models=installed))
    if gated.action != "SWITCH" or gated.target is None:
        return False, "aborted: inventory gate failed on the fresh read"
    try:
        remote.execute_switch(cfg, gated.models or (gated.target,))
    except Exception as error:  # noqa: BLE001
        log.warning("switch execution failed: %s", error)
        return False, "switch failed"
    return True, None


def _maybe_launch_fast_poll(cfg: Config, decision: Decision) -> None:
    """Clear the old quick-switch watcher. A checked cold boot needs the
    collector-held consumer key, so the next fresh idle tick executes it."""
    try:
        if not cfg.live_execution:
            if decision.action == "SWITCH_WHEN_IDLE":
                log.info("observe mode: would launch fast-poll watcher for target %s", decision.target)
            remote.remove_fast_switch_target(cfg)
            return
        remote.clear_fast_switch_target(cfg)
    except Exception as error:  # noqa: BLE001 - one bad tick must not kill the loop
        log.warning("fast-poll watcher control failed: %s", error)


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

    current = daemon.current_model if daemon else None
    eligible = _eligible_models(cfg.models, installed)
    db.delete_ineligible_ema(pool, host, eligible)
    if not eligible:
        # Verified empty cache, or no overlap with the allow-list: do not
        # score disk-only models and do not advance EMA freshness.
        _record_and_act(cfg, pool, Decision(None, "no eligible installed models", "WAIT"), current, now)
        return

    samples, prices = _fetch_scores(cfg)
    samples = {model: sample for model, sample in samples.items() if model in eligible}
    scores = scoring.compute_scores(samples, prices, cfg.weights)
    if not scores:
        # No scored models this tick: leave the stored EMA and its timestamp
        # untouched (saving now would fake a fresh dt on the next real update)
        # and wait rather than score stale data.
        _record_and_act(cfg, pool, Decision(None, "demand feeds unavailable", "WAIT"), current, now)
        return

    ema_prev, last_updated = db.load_ema(pool, host)
    # A model removed from DARKBLOOM_HOST_<N>_MODELS or missing from disk
    # must not survive in the restored EMA — its stale score could still win.
    ema_prev = {model: value for model, value in ema_prev.items() if model in eligible}
    dt = max(1.0, now - last_updated) if last_updated else cfg.poll_interval_seconds
    ema = decision_mod.update_ema(ema_prev, scores, dt, cfg.ema_tau_minutes)
    if ema:
        db.save_ema(pool, host, ema, now)
    db.insert_demand_samples(pool, host, now, samples, scores, prices, ema)

    result = _decide(cfg, pool, ema, daemon, now)
    payout = _shadow_payout(cfg, pool, daemon, result, now)
    _record_and_act(cfg, pool, result, current, now, payout)


def _shadow_payout(cfg: Config, pool: ConnectionPool, daemon: DaemonState | None,
                   demand_result: Decision, now: float) -> Decision:
    """Check the demand candidate against the last day of attributed payout
    per healthy warm hour. This is persisted for comparison, never executed."""
    if daemon is None:
        return Decision(None, "daemon state unavailable", "KEEP")
    try:
        cached = _PAYOUT_CACHE.get(cfg.host_id)
        if cached is None or now - cached[0] >= _PAYOUT_REFRESH_SECONDS:
            hashes = [provider_hash for provider_hash, host in attribution.provider_hosts(pool).items()
                      if host == cfg.host_id]
            rates = db.payout_rates(pool, cfg.host_id, now - 86400, now, hashes)
            measured = routability.measured_switch_cost(pool, cfg.host_id)
            switch_cost = measured[0] if measured else cfg.switch_cost_seconds
            cached = (now, rates, switch_cost)
            _PAYOUT_CACHE[cfg.host_id] = cached
        _, rates, switch_cost = cached
        proposed = demand_result.models or ((demand_result.target,) if demand_result.target else ())
        started = db.payout_confirmation_started_at(
            pool, cfg.host_id, proposed, now - 300 - cfg.poll_interval_seconds,
            now, cfg.poll_interval_seconds * 2)
        return payout_decision.decide(daemon.warm_models, demand_result, rates, switch_cost,
                                      3600.0, now - started)
    except Exception as error:  # noqa: BLE001 - shadow data must not break the collector
        log.warning("payout forecast unavailable: %s", error)
        return Decision(daemon.current_model, "payout history unavailable", "KEEP", daemon.warm_models)


def _record_and_act(cfg: Config, pool: ConnectionPool, result: Decision, current_model: str | None,
                    now: float, payout: Decision | None = None) -> None:
    """The decision is stored before any switch is dispatched, so a crash
    mid-switch still leaves a record; the outcome is written back afterwards.
    The restart-retry backoff defers rather than fails: error must stay NULL,
    or last_failed_switch_at() would move forward every tick and the backoff
    would never end."""
    mode = "live" if cfg.live_execution else "observe"
    if (result.action == "SWITCH" and cfg.live_execution
            and now - db.last_failed_switch_at(pool, cfg.host_id) < cfg.restart_backoff_seconds):
        result = Decision(result.target, f"{result.reason}; restart-retry backoff: waiting after a recent failed attempt", "BLOCKED")
    decision_id = db.insert_decision(pool, cfg.host_id, now, current_model, result,
                                     Outcome(mode, False, None), payout)
    executed, error = _maybe_execute(cfg, pool, result, now)
    if executed or error:
        db.record_outcome(pool, decision_id, Outcome(mode, executed, error))
    _maybe_launch_fast_poll(cfg, result)
    log.info("[%s] %s -> %s (%s): %s", mode, current_model or "?", result.target, result.action, result.reason)
