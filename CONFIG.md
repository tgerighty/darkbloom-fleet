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
| `DARKBLOOM_HOST_<N>_MODELS` | `qwen3.5-35b-a3b,gemma-4-26b-qat-4bit,gpt-oss-20b` | Comma-separated models this Mac has downloaded and may be scored for for demand logging. |
| `DARKBLOOM_HOST_<N>_SSH_KEY_PATH` | unset | Explicit identity file, if the SSH config does not select one. |
| `DARKBLOOM_HOST_<N>_REMOTE_PYTHON` | `python3` | Interpreter used for the remote earnings-ledger read. |

Shared by every host:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_PASSWORD_FILE` | unset | Set to `darkbloom_fleet_db_password` to load that Swarm secret into `DATABASE_URL`. |
| `DARKBLOOM_SSH_CONFIG` | unset | SSH config passed to every `ssh` call with `-F` (a Swarm secret on the cluster). |
| `DARKBLOOM_API_KEY_FILE` | unset | Set to `darkbloom_fleet_api_key` to load the shared API key. It authenticates read-only routing and provider identity queries. |
| `FLEET_BIND_HOST` | `127.0.0.1` | Address the dashboard binds to. Containers set `0.0.0.0` so Docker can reach it. |
| `DARKBLOOM_BASE_URL` | `https://api.darkbloom.dev` | Public demand-capacity API base. |
| `DARKBLOOM_PRICING_URL` | `https://api.darkbloom.dev/v1/pricing` | Public output-token pricing endpoint. |
| `POLL_INTERVAL_SECONDS` | `60` | Data collection cadence. |
| `FLEET_EMA_TAU_MINUTES` | `20` | EMA time constant for score smoothing. |
| `FLEET_SWITCH_COST_SECONDS` | `300` | Display fallback for measured start-to-first-request delay; does not control switching. |
| `FLEET_DAEMON_FRESHNESS_SECONDS` | `90` | A daemon-state read older than this is treated as stale, not authoritative. |
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
  NULL and never fail the daemon read. The card shows the error and whether it is recent.

Both land in `daemon_snapshots` (one ALTER-added column each; `slots` as
JSONB), so the card needs no extra endpoint and history is queryable.

## Local model inventory

Each tick runs a read-only `~/.darkbloom/bin/darkbloom models list --all --json`
over SSH, separate from the daemon-state command. Presence of `models[].id`
means that model is on disk. Scoring uses the intersection of that list and
`DARKBLOOM_HOST_<N>_MODELS`; disk-only ids are never enrolled. A failed or
malformed read logs a warning and falls back to the configured allow-list
for that tick. A verified empty list scores nothing without
advancing EMA freshness. The snapshot stores the ids as NULL (unknown) or
an array (including empty). Inventory is observation only: no download,
remove, or warmup.


## Model control

Model manager 0.1.7 on each Mac owns model selection and switching.
This service only collects data. The old fleet switch environment variables
are no longer read. Historical shadow decisions remain in Postgres.

## Earnings

Per-machine earnings include inference payouts and base rewards, deduplicated
by payout ID and attributed by provider session. Unassigned payouts are not
included in either machine's total. Base rewards do not count as jobs or as
evidence for request-counter attribution.

When upgrading from a collector that excluded base rewards, replay each Mac's
ledger once with `remote.fetch_new_payouts(cfg, 0)` and `db.insert_payouts`.
The existing primary key makes this replay safe; normal incremental collection
then includes new rewards. The replay restores only records still in the Mac's
saved ledger.

The demand table uses each Mac manager's saved score snapshot: average network
pressure over five one-minute samples × blended token price (85% input, 15%
output) × configured model weight. Rows are separate per host and include only
eligible models. Snapshots older than three minutes are omitted. The table's
ranking is before the manager's dwell, improvement, and switching-cost checks.
