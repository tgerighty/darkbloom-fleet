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
