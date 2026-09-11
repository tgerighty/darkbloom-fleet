# Progress

- ~~[NOW] [FEATURE] Multi-host config and dashboard~~
- ~~[NOW] [FEATURE] Secret-file DB password and SSH config support~~
- ~~[NOW] [FEATURE] deploy.yml and deploy/stack.yml~~
- ~~[NOW] [FEATURE] Cluster prep: DB password secret, Gluster data directory~~
- ~~[NOW] [FEATURE] SSH secrets, compose destination directory, release webhook~~
- ~~[NOW] [FIX] Sonar round 1 (30 findings) and CodeRabbit round 1 (12 findings)~~
- [NOW] [FIX] [IN-PROGRESS] CodeRabbit CLI round 2 (6 of 7 fixed; observe-mode
  target clearing skipped: observe mode stays read-only) and Sonar complexity
- [NEXT] [FEATURE] Merge, verify the nxio-deploy release
- [NEXT] [FEATURE] nginx vhost for darkbloom.nxio.ai (Cloudflare needs no
  change: the `*.nxio.ai` DNS, tunnel rule and Access app already cover it)
- [NEXT] [FEATURE] pg_back backup registration
- [NEXT] [REFACTOR] Retire the cm7 docker compose copy
- [NEXT] [BUG] The payout ledger is account-wide on every Mac, so per-host
  earnings count other machines' payouts. Attribute payouts to a host by
  matching each provider_hash session to that host's daemon restarts.
- [FUTURE] [FEATURE] Write the remote watcher's asynchronous switch result
  back onto its decision record (only matters once live mode is enabled)
