# Configuration

## Running locally

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD and the DARKBLOOM_HOST_1_* block
# (add a DARKBLOOM_HOST_2_* block for a second Mac)

mkdir -p secrets/ssh
# put a config, an identity file, and known_hosts for the managed hosts here.
# chmod 600 the key. Each DARKBLOOM_HOST_<N>_SSH_TARGET should name an alias
# defined in secrets/ssh/config, so no real hostname appears in .env either.

docker compose up --build
```

The dashboard is at `http://localhost:8080` (`FLEET_DASHBOARD_PORT`). Postgres
data persists in the `fleet_pgdata` named volume across restarts.

Tests (pure functions, no database needed): `pip install -r requirements.txt
pytest && pytest`.

## Running on the cluster

nxio-deploy releases every push to `main` (`deploy.yml`, `deploy/stack.yml`).
It builds `zillon/darkbloom-fleet`, pins image digests, runs the cluster stack
linter and deploys stack `darkbloom-fleet`. Postgres keeps its data on Gluster
at `/mnt/gluster/apps/darkbloom-fleet/pgdata`. Create these external Swarm
secrets once, on a manager:

| Secret | Contents |
|---|---|
| `darkbloom_fleet_db_password` | Random Postgres password. |
| `darkbloom_fleet_ssh_key` | Private key the Macs accept. |
| `darkbloom_fleet_ssh_config` | One `Host` block per alias, plus `IdentityFile /run/secrets/darkbloom_fleet_ssh_key`, `UserKnownHostsFile /run/secrets/darkbloom_fleet_ssh_known_hosts` and `StrictHostKeyChecking yes`. |
| `darkbloom_fleet_ssh_known_hosts` | Host keys for every alias. |

The dashboard is served at `https://darkbloom.nxio.ai` behind Cloudflare
Access. It has no login of its own, so never publish it without Access.

## Required environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. `docker-compose.yml` builds it from `POSTGRES_PASSWORD`; the Swarm stack gives it without a password and sets `DATABASE_PASSWORD_FILE`. |
| `DARKBLOOM_HOST_1_SSH_TARGET` | SSH alias for the first managed Mac, resolved through the SSH config. Never a literal address in this repo. |
| `POSTGRES_PASSWORD` | Local docker compose only: Postgres password, generated locally, never committed. |

## Optional environment variables and their defaults

Per host. `<N>` is 1, 2, ... and discovery stops at the first missing
`DARKBLOOM_HOST_<N>_SSH_TARGET`:

| Variable | Default | Meaning |
|---|---|---|
| `DARKBLOOM_HOST_<N>_LABEL` | the SSH target | Display name on the dashboard and the `host` column in every table. |
| `DARKBLOOM_HOST_<N>_SPEC` | `unknown` | Display hardware spec, e.g. `Apple M3 Max`. |
| `DARKBLOOM_HOST_<N>_MODELS` | `qwen3.5-35b-a3b,gemma-4-26b-qat-4bit,gpt-oss-20b` | Comma-separated models this Mac has downloaded and may be scored for (see "Deferred" below). |
| `DARKBLOOM_HOST_<N>_SSH_KEY_PATH` | unset | Explicit identity file, if the SSH config does not select one. |
| `DARKBLOOM_HOST_<N>_REMOTE_PYTHON` | `python3` | Interpreter used for the remote earnings-ledger read. |
| `DARKBLOOM_HOST_<N>_LIVE_EXECUTION` | `FLEET_LIVE_EXECUTION` | Per-host override of the live switch. |

Shared by every host:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_PASSWORD_FILE` | unset | File holding the Postgres password (a Swarm secret), merged into `DATABASE_URL`. |
| `DARKBLOOM_SSH_CONFIG` | unset | SSH config passed to every `ssh` call with `-F` (a Swarm secret on the cluster). |
| `DARKBLOOM_BASE_URL` | `https://api.darkbloom.dev` | Public demand-capacity API base. |
| `DARKBLOOM_PRICING_URL` | `https://api.darkbloom.dev/v1/pricing` | Public output-token pricing endpoint. |
| `POLL_INTERVAL_SECONDS` | `60` | Ingestion + decision cadence. |
| `FLEET_LIVE_EXECUTION` | `false` | **The only switch that enables real actions.** See "Safety default" below. |
| `FLEET_EMA_TAU_MINUTES` | `20` | EMA time constant for score smoothing. |
| `FLEET_RELATIVE_MARGIN` | `0.25` | Challenger must clear `current * (1 + margin)`. |
| `FLEET_ABSOLUTE_MARGIN` | `0.01` | Challenger must also clear `current + margin`. |
| `FLEET_SWITCH_COST_SECONDS` | `300` | Estimated unavailable time charged against a challenger's score. |
| `FLEET_DECISION_HORIZON_SECONDS` | `3600` | Window the switch cost is amortized over. |
| `FLEET_MIN_DWELL_SECONDS` | `1800` | Minimum time before another switch is even considered. |
| `FLEET_DAEMON_FRESHNESS_SECONDS` | `90` | A daemon-state read older than this is treated as stale, not authoritative. |
| `FLEET_RESTART_BACKOFF_SECONDS` | `30` | Cooldown after a failed switch attempt before retrying. |
| `FLEET_DASHBOARD_PORT` | `8080` | Port the dashboard/API listens on. |

## Safety default: OBSERVE / DRY-RUN

`FLEET_LIVE_EXECUTION` defaults to `false`. In that mode the service ingests
data, computes scores, logs and persists every decision it *would* make, and
the dashboard shows it clearly ("OBSERVE" badge) - but it never calls
`darkbloom start` against the real host. This matches the darkbloom-manager
project's own operating practice: never take a live action without
human-verified context. Setting `FLEET_LIVE_EXECUTION=true` is the only way
to let the service execute switches; do that only after watching OBSERVE
mode agree with what you'd have done by hand.

## Guardrail defaults and why

All four guardrails below are forked from the darkbloom-manager project and
carry over its 2026-09-11 validation, run on 54.5 hours of real
earnings-ledger data (2026-09-09 05:54 -> 2026-09-11 12:22 local):

- **EMA-smoothed switching (tau = 20 min)** replaces "N consecutive passing
  checks" as the switch gate. Backtest: following the raw manager target with
  only a 30-minute dwell earned **$7.32 with 48 switches**; EMA-smoothed
  scores earned **$7.60-7.64 with 3-16 switches** across tau = 10-45 minutes;
  a hindsight oracle earned $8.19; the best static single-model choice earned
  $5.16. The raw (un-smoothed) target flipped 122 times in 56 hours - a
  median "meets the bar" run of only 8-9 minutes - so a fast follower would
  switch and then be told to switch back almost immediately. EMA smoothing
  keeps essentially all of the switching revenue (switching itself is the
  +45% over static; the score formula alone is within ~7% of the oracle)
  while cutting switch count 3-5x. tau = 20 minutes sits in the middle of the
  flat plateau (10-45 min all perform similarly) rather than at either edge.
- **30-minute minimum dwell** between switches, unchanged from the source
  project's `--min-warm-time` default - protects a freshly-warmed model's
  residency regardless of what the score says a minute later.
- **Idle-gating before any real restart** - the service re-reads
  `daemon-state.json` immediately before issuing `darkbloom start` and
  aborts if `inference_active` is true or the read isn't fresh. Learned the
  hard way in the source project: the provider's launchd exit timeout is
  only 5 seconds, so restarting during an in-flight request can SIGKILL it
  mid-shutdown, which reads to the coordinator as a failed request and drags
  down reputation. Restarting only when idle is what kept reputation intact
  across every switch in that project's session.
- **30-second restart-retry backoff** after a failed switch attempt, not an
  immediate retry - also learned the hard way: `darkbloom start` can hit
  `launchctl bootstrap failed: ... Input/output error` when the previous
  process is still tearing down; an immediate retry very likely repeats the
  same failure, while a 20-30 second wait lets the old process finish dying
  first.

## Fast idle-gap watcher (no new env var)

Idle-gating (above) can itself starve a switch that never sees an idle
instant at tick time even though idle gaps are opening and closing between
ticks - the real host missed 8 consecutive ~60s ticks in a row on 2026-09-11
this way. When a tick's decision is `SWITCH_WHEN_IDLE` (clears margin and
dwell, blocked only on `inference_active`) and `FLEET_LIVE_EXECUTION=true`,
the collector launches a 1s-poll watcher on the remote host for the rest of
the cycle instead of waiting for the next tick - see README's "Fast idle-gap
watcher" for how it works and `fleet/remote_assets/fast_switch_watcher.py`
for the implementation. Its poll window is derived from the existing
`POLL_INTERVAL_SECONDS` (`poll_interval_seconds - 5`, floored at 5s), not a
separate setting - one less knob, and it stays correct if the cadence
changes. In OBSERVE mode this is also a no-op: the collector only logs what
it would launch.

## What's deferred, and why it's safe to defer for v1

- **Local model-availability discovery** (`darkbloom models list --all` over
  SSH): the source project uses this to auto-exclude models that aren't
  downloaded on the host. v1 instead scores a fixed configured list
  (`DARKBLOOM_MODELS`) - correct as long as that list matches what's actually
  downloaded, which a single operator can verify once at setup. Multi-host
  fleets will need this back; tracked as follow-up work, not built now.
- **Multi-host and LLM-driven decisions**: explicitly out of v1 scope per the
  brainstorm - the schema, config, and code are single-host throughout.
