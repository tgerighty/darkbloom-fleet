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
| `darkbloom_fleet_api_key` | A Darkbloom consumer API key for the account that owns the Macs; used only for the read-only self-route listing (`DARKBLOOM_API_KEY_FILE`). |

The dashboard is served at `https://darkbloom.nxio.ai` behind Cloudflare
Access. It has no login of its own, so never publish it without Access.

## Required environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string, without the password: `docker-compose.yml` passes `POSTGRES_PASSWORD` as `PGPASSWORD`, and the Swarm stack sets `DATABASE_PASSWORD_FILE`. |
| `DARKBLOOM_HOST_1_SSH_TARGET` | SSH alias for the first managed Mac, resolved through the SSH config. Never a literal address in this repo. |
| `POSTGRES_PASSWORD` | Local docker compose only: Postgres password, generated locally, never committed. |

## Optional environment variables and their defaults

Per host. `<N>` is 1, 2, ... and discovery stops at the first missing
`DARKBLOOM_HOST_<N>_SSH_TARGET`:

| Variable | Default | Meaning |
|---|---|---|
| `DARKBLOOM_HOST_<N>_ID` | the SSH target | Immutable database identity: the `host` column in every table. Changing it orphans that host's history, so set it once and never edit it — rename the host with `LABEL` instead. |
| `DARKBLOOM_HOST_<N>_LABEL` | the SSH target | Display name on the dashboard only (logs and the `host` block of `/api/status`); never a database key. |
| `DARKBLOOM_HOST_<N>_SPEC` | `unknown` | Display hardware spec, e.g. `Apple M3 Max`. |
| `DARKBLOOM_HOST_<N>_MODELS` | `qwen3.5-35b-a3b,gemma-4-26b-qat-4bit,gpt-oss-20b` | Comma-separated models this Mac has downloaded and may be scored for (see "Deferred" below). |
| `DARKBLOOM_HOST_<N>_SSH_KEY_PATH` | unset | Explicit identity file, if the SSH config does not select one. |
| `DARKBLOOM_HOST_<N>_REMOTE_PYTHON` | `python3` | Interpreter used for the remote earnings-ledger read. |
| `DARKBLOOM_HOST_<N>_LIVE_EXECUTION` | `FLEET_LIVE_EXECUTION` | Per-host override of the live switch. |

Shared by every host:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_PASSWORD_FILE` | unset | Set to `darkbloom_fleet_db_password` to load that Swarm secret into `DATABASE_URL`. |
| `DARKBLOOM_SSH_CONFIG` | unset | SSH config passed to every `ssh` call with `-F` (a Swarm secret on the cluster). |
| `DARKBLOOM_API_KEY_FILE` | unset | Set to `darkbloom_fleet_api_key` to load the shared API key. It authenticates the self-routed model listing and live chat-completion warm-ups. |
| `FLEET_BIND_HOST` | `127.0.0.1` | Address the dashboard binds to. Containers set `0.0.0.0` so Docker can reach it. |
| `DARKBLOOM_BASE_URL` | `https://api.darkbloom.dev` | Public demand-capacity API base. |
| `DARKBLOOM_PRICING_URL` | `https://api.darkbloom.dev/v1/pricing` | Public output-token pricing endpoint. |
| `POLL_INTERVAL_SECONDS` | `60` | Ingestion + decision cadence. |
| `FLEET_LIVE_EXECUTION` | `false` | **The only switch that enables real actions.** See "Safety default" below. Live switches use a five-minute cold boot and require local and self-routed API checks. |
| `FLEET_EMA_TAU_MINUTES` | `20` | EMA time constant for score smoothing. |
| `FLEET_RELATIVE_MARGIN` | `0.25` | Challenger must clear `current * (1 + margin)`. |
| `FLEET_ABSOLUTE_MARGIN` | `0.01` | Challenger must also clear `current + margin`. |
| `FLEET_SWITCH_COST_SECONDS` | `300` | Estimated unavailable time charged against a challenger's score. Fallback only: once the host has 3+ past daemon sessions that served a request, each tick uses the measured median start-to-first-request delay over the last 10 such sessions instead (`routability.measured_switch_cost`); the dashboard's models panel shows which value is in force. |
| `FLEET_DECISION_HORIZON_SECONDS` | `3600` | Window the switch cost is amortized over. |
| `FLEET_MIN_DWELL_SECONDS` | `1800` | Minimum time before another switch is even considered. |
| `FLEET_DAEMON_FRESHNESS_SECONDS` | `90` | A daemon-state read older than this is treated as stale, not authoritative. |
| `FLEET_RESTART_BACKOFF_SECONDS` | `30` | Cooldown after a failed switch attempt before retrying. |
| `FLEET_DUAL_MODEL_MIN_GB` | `64` | Hosts at or above this reported RAM rank and launch two-model combinations. |
| `FLEET_DASHBOARD_PORT` | `8080` | Port the dashboard/API listens on. |

## Per-host card data (no new env vars)

The dashboard's per-host console card and `/api/status`'s `card` block are fed
by two data points the tick reads alongside `daemon-state.json`, in the same
SSH round trip:

- The Mac widget's metrics DB, latest sample
  (`sqlite3 ~/.darkbloom-widget/metrics.db "select json from samples order by
  timestamp desc limit 1"`): `thermalState`, `memoryPressure` (0-1),
  `cpuUsage` (0-1), `fanRPM`, `gpuActiveGb`, `peakTemperatureC`. A missing or
  malformed widget row degrades to NULL columns — it never fails the daemon
  read — and `gpuActiveGb` only stands in for GPU memory when the daemon's own
  capacity section has no `gpu_memory_active_gb`.
- The daemon state's `capacity` (`gpu_memory_active_gb`,
  `gpu_memory_cache_gb`, `total_memory_gb`) and `slots` (per resident model:
  `model`, `kv_backend`, `mtp_enabled`, `mtp_active`,
  `mtp_inactive_reason`).
- The daemon state's `last_model_load_error` (`model`, `message`, and `at` as
  an absolute unix timestamp). Missing, malformed, or non-finite values become
  NULL and never fail the daemon read. The card shows it; a matching target
  whose error is at most 120 seconds old blocks a switch.

Both land in `daemon_snapshots` (one ALTER-added column each; `slots` as
JSONB), so the card needs no extra endpoint and history is queryable.

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
- **Host safety gates** (same in OBSERVE and LIVE; OBSERVE still never
  executes): a fresh thermal state of `serious` or `critical` returns
  `BLOCKED`. A present `trust_level` other than `hardware` returns `KEEP`
  (no restart during attestation). Absent trust is not treated as hardware
  and keeps the current model (no restart). A proposed target whose last
  load error is in the future or at most 120 seconds in the past returns
  `BLOCKED`; older past errors and other models do not.
- **30-second restart-retry backoff** after a failed switch attempt, not an
  immediate retry - also learned the hard way: `darkbloom start` can hit
  `launchctl bootstrap failed: ... Input/output error` when the previous
  process is still tearing down; an immediate retry very likely repeats the
  same failure, while a 20-30 second wait lets the old process finish dying
  first.

## Idle-gated cold boots

The collector rechecks fresh idle state immediately before each live switch.
It then stops the provider for five minutes, starts the selected one- or
two-model set with the local endpoint enabled, and requires a completed local
inference plus a self-routed Darkbloom API inference for each model. A missing
consumer key or either failed check records a failed switch. Busy providers
wait for a later collector tick. One manager lock serializes host cold boots.
The local check identifies the selected host. The self-routed API check is
account-wide and confirms that an owned provider can receive the model.

## Local model inventory

Each tick runs a read-only `~/.darkbloom/bin/darkbloom models list --all --json`
over SSH, separate from the daemon-state command. Presence of `models[].id`
means that model is on disk. Scoring uses the intersection of that list and
`DARKBLOOM_HOST_<N>_MODELS`; disk-only ids are never enrolled. A failed or
malformed read logs a warning and falls back to the configured allow-list
for that tick. A verified empty list scores nothing and records WAIT without
advancing EMA freshness. The snapshot stores the ids as NULL (unknown) or
an array (including empty). Inventory is observation only: no download,
remove, or warmup.

## What's deferred, and why it's safe to defer for v1

- **LLM-driven decisions**: out of scope; decisions use the scored formula.
