# darkbloom-fleet

A standalone service for managing and optimizing revenue across a small
fleet of Macs serving inference on the [darkbloom](https://darkbloom.dev)
network. Starts with one host, designed to grow to a handful.

**Status: design in progress, no application code yet.** See below for
what's decided so far and what's still open.

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
  (idle-before-switch, minimum consecutive confirmations before acting,
  etc.) - not just advisory. The specific default values for those
  guardrails are still open.
- **v1 scope: single host.** Multi-host support and any LLM-driven
  decision-making (as opposed to today's scored heuristic) are explicit
  follow-on work, not built into v1.

## Still open

- Exact ingestion cadence and mechanism (polling interval, how failures
  are handled without ever leaving a host in an ambiguous state)
- Guardrail defaults (idle-gating, consecutive-check thresholds,
  restart-retry backoff) - today's manual practice is the starting
  point, needs porting into config
- Deployment target (this cluster's Docker Swarm vs. something simpler
  for v1)
- Credential handling for SSH access to managed hosts (this repo is
  public - no key material, tokens, or host-identifying secrets ever
  get committed here; real config lives outside the repo, see
  `.gitignore`)

## Security

**This repository is public.** Never commit credentials, SSH keys,
API tokens, or anything that identifies a real host by private
address/hostname beyond what's needed to understand the code. See
`.gitignore` for the enforced patterns. Configuration containing real
values (hosts, credentials) is supplied at deploy time via environment
variables or a mounted secret, never checked in.
