# Progress

- [NOW] [FEATURE] Per-host health badge on each card: DAEMON_DOWN, DEAD_SESSION, THRASH, STALE, or HEALTHY from daemon_snapshots and demand_samples (fleet/health.py)
- [NOW] [FEATURE] "Jobs · hourly buckets" panel per host card (PR #6):
  last-24 h attributed payout counts bucketed by hour with a letter legend
  and range share (`hourly_jobs` in /api/status, fleet/hourly.py), the
  40-char distribution bar and percentages rendered client-side from the
  row counts (fleet/static/hourly.js); also fixes the self-referential
  SPAN_END/SPAN_DIV_END constants 774217a left in dashboard.js (TDZ crash
  on page load)
- [NOW] [FEATURE] [IN-PROGRESS] Console-style per-host cards matching the
  darkbloom.dev "Your fleet" page: widget metrics + daemon capacity/slots
  ingested in the daemon-state SSH round trip (new daemon_snapshots columns),
  `card` block in /api/status (fleet/card.py), dashboard split into
  dashboard.html + dashboard.js served from a /static mount
- ~~[NOW] [FEATURE] Multi-host config and dashboard~~
- ~~[NOW] [FEATURE] Secret-file DB password and SSH config support~~
- ~~[NOW] [FEATURE] deploy.yml and deploy/stack.yml~~
- ~~[NOW] [FEATURE] Cluster prep: DB password secret, Gluster data directory~~
- ~~[NOW] [FEATURE] SSH secrets, compose destination directory, release webhook~~
- ~~[NOW] [FIX] Sonar round 1 (30 findings) and CodeRabbit round 1 (12 findings)~~
- ~~[NOW] [FIX] CodeRabbit CLI round 2 and Sonar complexity~~
- ~~[NEXT] [FEATURE] Merge, verify the nxio-deploy release~~ (PR #1 merged 2026-09-12 06:02Z; deploy 5181449 verified)
- ~~[NEXT] [FEATURE] nginx vhost for darkbloom.nxio.ai~~ (conf 1fe6f95, 3 replicas, Access 302 verified)
- [NOW] [FEATURE] [IN-PROGRESS] PR #2: self-route routability probe, per-host
  models panel (advertised / warm / routable / last served), single demand
  table, serving windows with idle, scrolling decisions, 1-minute refresh
- ~~[NEXT] [FEATURE] pg_back backup registration~~ (2026-09-12: cluster repo
  11709e1 — `darkbloom-fleet-postgres` target at the 6h tier reusing
  infra_age_recipient; verifier inventory line; first encrypted dump OK)
- ~~[NEXT] [REFACTOR] Retire the cm7 docker compose copy~~ (2026-09-12:
  containers and network removed, `darkbloom-fleet_fleet_pgdata` volume kept;
  `docker-compose.yml` stays for local runs)
- [NEXT] [BUG] CodeRabbit 2026-09-12, pre-existing logic, deferred from PR #2:
  empty demand scores must not refresh/save the EMA (tick should WAIT);
  the restart-retry backoff should not be recorded as a decision error, or it
  extends itself every tick; observe mode should clear a stale remote watcher
  target; the "no eligible current model" branch in decision.py skips the
  idle and dwell gates.
- ~~[NEXT] [REFACTOR] CodeRabbit round 4 (deferred): key hosts by an immutable
  id rather than the editable label; filter the restored EMA to cfg.models so
  a removed model cannot linger; wrap the lifespan shutdown in try/finally.~~
  (2026-09-12: `host_id` from `DARKBLOOM_HOST_<N>_ID`, defaulting to the SSH
  target, keys every table while `LABEL` stays display-only; stack.yml pins
  both ids to the current labels so existing rows keep matching; the restored
  EMA is filtered to `cfg.models` at load; lifespan shutdown runs in finally)
- ~~[NEXT] [FEATURE] Measured switch penalty: feed the routability probe's
  first-request timings back into the switch-cost guardrail instead of the
  fixed 300 s.~~ (2026-09-12: median start-to-first-request delay over the
  last 10 sessions that served, minimum 3 — `routability.measured_switch_cost`
  feeds `collector._decide`, configured value stays the fallback; the
  dashboard's models panel shows measured vs configured)
- ~~[NOW] [FIX] The coordinator's self-route listing uses short model ids
  (`gemma-4-26b`), so the routability panel showed one model as two rows:
  an advertised/warm row with 0 routable providers and a coordinator row
  with 0 advertised/warm.~~ (2026-09-12: coordinator ids are mapped onto our
  advertised/warm ids by equal-or-`-`suffix match, `routability` panel merge)
- ~~[NEXT] [BUG] The payout ledger is account-wide on every Mac, so per-host
  earnings count other machines' payouts. Attribute payouts to a host by
  matching each provider_hash session to that host's daemon restarts.~~
  (2026-09-12: provider_hash ingested; each session attributed to the host
  whose request counter rose across the payout's snapshot minute —
  fleet/attribution.py; dashboard shows the unattributed row count)
- [FUTURE] [FEATURE] Write the remote watcher's asynchronous switch result
  back onto its decision record (only matters once live mode is enabled)
