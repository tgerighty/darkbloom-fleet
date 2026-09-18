# darkbloom-fleet

Read-only monitoring and data collection for Macs serving inference on the
[darkbloom](https://darkbloom.dev) network. Model manager **0.1.7** on each Mac
controls model selection and switching.

The fleet service records provider state, manager reports, installed models,
thermal and fan metrics, demand and pricing samples, smoothed demand scores,
self-route availability, provider identities, and attributed earnings in Postgres.
The dashboard shows manager status, serving history, hourly jobs, the last five
jobs, payouts, backend slots, and trust information.

The fleet demand and payout shadow engines and fleet switch controls have been
removed. Existing decision history remains in Postgres; no new shadow decisions
are generated. Manager reports continue to be stored with daemon snapshots.

## Credit

The demand score formula and exponential moving average in `fleet/scoring.py`
come from the darkbloom-manager project. They are retained for data logging and
the demand table, and do not control the providers.

## Running locally

```bash
cp .env.example .env
mkdir -p secrets/ssh
docker compose up --build
# dashboard: http://localhost:8080
```

See [CONFIG.md](CONFIG.md) for configuration and cluster deployment.

## Security

This repository is public. Keep credentials and private host details in
runtime environment variables or mounted secrets. SSH collection is read-only.
The production dashboard requires Cloudflare Access.

## Discord watch alerts

The deployed fleet runs a read-only watcher for every configured Mac every
30 seconds, independently of demand and earnings collection. It sends alerts
to the existing cluster Alertmanager (`FLEET_ALERTMANAGER_URL`), which handles
Discord delivery, grouping, repeat notifications and recovery messages.

- `DarkbloomManagerSwitchFailed`: a pending switch has a command error or the
  manager reports that automatic restart is blocked. Alerts on the next check.
- `DarkbloomProviderUnavailable`: no running provider, a stale provider
  heartbeat, or an unreachable machine for five continuous minutes.
- `DarkbloomManagerUnavailable`: manager stopped or decisions stale for five
  continuous minutes. An unreachable machine does not falsely clear this alert.

The watcher checks launchd and state files over the existing SSH connection.
It does not restart providers or interrupt inference. Timers and pending
recovery notifications are stored in PostgreSQL and survive service restarts.
A confirmed warm target clears an old switch error even before the manager
updates its state. Brief outages do not notify. Alertmanager adds its normal
notification grouping delay (currently 30 seconds for a new group).

Unset `FLEET_ALERTMANAGER_URL` to disable notifications in local development.
Planned maintenance can be silenced in Alertmanager using `cluster=darkbloom`
and the Mac's `instance` label. These checks verify processes and heartbeats;
they do not send inference requests or prove public API routing.

### Earnings shadow evidence

With `FLEET_EARNINGS_SHADOW=true`, every five minutes the fleet publishes
`~/.darkbloom/fleet-earnings-profile.json` on each configured Mac. It uses the
last 24 hours of allocated model time (including idle and observed loading
failures), warm time, matching network pressure, and deduplicated inference
payouts. Only unambiguous verified provider identities assign earnings to a
machine. Base rewards and unknown identities are excluded; missing evidence
must not be interpreted as a measured zero. Collection gaps over 90 seconds
are excluded from allocation time. This is an observational baseline, not a
controlled benchmark; delayed payouts and missing observations can affect it.

The manager's optional `--earnings-profile` and `--earnings-host` arguments
consume this evidence in shadow mode only. The fleet preserves its
`earnings_shadow` report in manager snapshots and the status API for comparison
with live decisions. No provider restart, model change or extra inference job
is issued by the evidence publisher.
