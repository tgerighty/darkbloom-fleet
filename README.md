# darkbloom-fleet

A standalone service for managing and optimizing revenue across a small
fleet of Macs serving inference on the [darkbloom](https://darkbloom.dev)
network. Starts with one host, designed to grow to a handful.

**Status: v1 implemented — single host, observe/dry-run by default.** See
below for what's decided, what's running, and what's still deferred.

## Credit

The model-switching heuristic in `fleet/scoring.py` and `fleet/decision.py`
originated in a private project (`darkbloom-manager`, not public — referenced
here only by name, no internal paths or hostnames) and was forked and
extended for this standalone service. Two pieces come from there directly:

- The score formula, switch-cost discount, and relative/absolute margins are
  ported from that project's `warm_model_manager.py`.
- Replacing the "N consecutive passing checks" switch gate with a 20-minute
  EMA of each candidate model's score is ported from that project's
  `analysis/dry_run_switcher.py`, which validated it against 54.5 hours of
  real earnings-ledger data: same revenue as the consecutive-checks gate,
  with 3-5x fewer switches (48 -> 3-16). See `CONFIG.md` for the full numbers
  and the guardrail defaults that carry them forward here.

## Why

Running darkbloom's provider daemon well means constantly picking the
right model to keep warm, based on live network demand, price, and each
model's real earnings on the actual hardware. Doing that by hand (or via
a human/LLM watching a terminal) doesn't scale past one machine. This
service automates it: it decides, it switches, it shows you what
happened and why.

## Decided so far

- **Standalone.** No dependency on any particular chat session or tool
  to stay running or stay updated - it's its own long-running service.
- **Own database: Postgres.** State (host status, demand history,
  decisions, earnings) lives in a Postgres instance the service owns,
  not scattered across ad-hoc CSVs or SQLite files on individual hosts.
- **Pulls data itself** from each managed host (over SSH, reading the
  darkbloom provider's own state/earnings) and from the public
  network-wide demand dashboard - it doesn't wait on a human to run a
  script.
- **Its own dashboard.** A real web UI the service serves itself, not a
  page that needs anyone to keep it updated by hand.
- **Executes switches autonomously**, gated by configurable guardrails
  (idle-before-switch, EMA-smoothed confirmation, restart-retry backoff)
  - not just advisory, though v1 ships with those guardrails defaulted to
    OBSERVE mode (see "Safety default" in CONFIG.md).
- **Catches idle gaps between poll ticks.** On 2026-09-11 the real host
  wanted to switch to `gemma-4-26b-qat-4bit` for 8 consecutive ~60s ticks in
  a row, because the host never happened to be idle at the exact instant any
  tick ran - even though idle gaps were opening and closing between ticks.
  When a tick finds a switch that clears every gate except idle, it launches
  a self-locking 1s-poll watcher on the remote host (see "Fast idle-gap
  watcher" below) instead of waiting for the next full cycle.
- **v1 scope: single host.** Multi-host support and any LLM-driven
  decision-making (as opposed to today's scored heuristic) are explicit
  follow-on work, not built into v1.

## Resolved for v1 (see CONFIG.md for details)

- **Ingestion**: a plain asyncio loop polls every 60s by default
  (`POLL_INTERVAL_SECONDS`) - daemon state and the public demand/pricing
  feeds every tick, the real earnings ledger every tick since the last seen
  payout row. Each source fails independently and is logged; a bad tick
  never crashes the service or blocks the others.
- **Guardrails**: EMA-smoothed switching (see "Credit" above), a 30-minute
  minimum dwell, idle-gating before any real restart, and a 30-second
  restart-retry backoff after a failed switch attempt. Defaults and
  rationale are in `CONFIG.md`.
- **Deployment**: the cluster runs the Swarm stack in `deploy/stack.yml`,
  released by nxio-deploy (see CONFIG.md "Running on the cluster");
  `docker-compose.yml` runs the same app locally.
- **Credentials**: SSH target, key, and host identity all come from
  environment variables or a mounted `./secrets/ssh` directory - never
  committed. See `.gitignore` and `CONFIG.md`.

## Fast idle-gap watcher

The ~60s poll cadence is coarse: a challenger can clear every switch gate
except idle, and the host can open and close idle gaps *between* ticks
without ever being idle at the exact moment a tick runs. That's exactly what
happened on the real host on 2026-09-11: the switcher wanted
`gemma-4-26b-qat-4bit` for 8 consecutive ticks, all 8 blocked on
"provider is serving a request", while idle gaps came and went unseen.

When `decision.decide()` returns `SWITCH_WHEN_IDLE` (challenger clears
margin and dwell, blocked only on `inference_active`), the collector deploys
and launches `fleet/remote_assets/fast_switch_watcher.py` on the remote host
via SSH (`fleet/remote.py:launch_fast_switch_watcher`). That script polls
locally every 1s for the rest of the cycle, re-reading its target from a
small JSON state file the collector rewrites over SSH each tick (it can't
call back into fleet's own process once launched) - so it self-corrects if
the recommendation changes mid-wait - and executes the switch the instant
`inference_active` goes false, using the same bootstrap-race
retry-after-25s and 5x3s post-switch verification as `remote.execute_switch`.

It's self-locking via a PID file (`/tmp/darkbloom-fast-switch.lock`, checked
with `os.kill(pid, 0)` - the target host is macOS, which has no `flock`
CLI), so launching it again while one is already running is a cheap no-op:
the new process sees the lock held and exits immediately. Like every other
real action, it's gated by `FLEET_LIVE_EXECUTION`: in OBSERVE mode the
collector only logs what it would launch.

## Deferred to a follow-up (explicitly out of v1 scope)

- LLM-driven decision-making (today's heuristic is the scored formula above).
- Discovering which models are actually downloaded/loadable on each host via
  `darkbloom models list` over SSH - each host scores a fixed configured model
  list (`DARKBLOOM_HOST_<N>_MODELS`) instead.

## Running locally

```bash
cp .env.example .env            # fill in POSTGRES_PASSWORD and DARKBLOOM_HOST_1_*
mkdir -p secrets/ssh             # SSH config + key + known_hosts for the host
docker compose up --build
# dashboard: http://localhost:8080
```

Full environment variable reference, guardrail defaults, and the backtest
numbers behind them: see `CONFIG.md`.

## Security

**This repository is public.** Never commit credentials, SSH keys,
API tokens, or anything that identifies a real host by private
address/hostname beyond what's needed to understand the code. See
`.gitignore` for the enforced patterns. Configuration containing real
values (hosts, credentials) is supplied at deploy time via environment
variables or a mounted secret, never checked in.
