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
- **Deployment**: v1 ships as `docker-compose.yml` (one app container + one
  Postgres container) - not a Swarm stack yet. See "Running locally" below.
- **Credentials**: SSH target, key, and host identity all come from
  environment variables or a mounted `./secrets/ssh` directory - never
  committed. See `.gitignore` and `CONFIG.md`.

## Deferred to a follow-up (explicitly out of v1 scope)

- Multi-host support (schema and code are single-host; `host` is a config
  label, not a table to join against yet).
- LLM-driven decision-making (today's heuristic is the scored formula above).
- Discovering which models are actually downloaded/loadable on the host via
  `darkbloom models list` over SSH - v1 scores a fixed configured model list
  (`DARKBLOOM_MODELS`) instead.
- A Docker Swarm stack manifest for this cluster.

## Running locally

```bash
cp .env.example .env            # fill in DARKBLOOM_SSH_TARGET, POSTGRES_PASSWORD
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
