# Swarm deployment: implementation plan

Goal: run darkbloom-fleet on the rk/cm Swarm through nxio-deploy, reachable at
`https://darkbloom.nxio.ai` behind Cloudflare Zero Trust (nxio.ai and
gerighty.com logins only), observing m3-48-1 and M1-64-1. Live switching
stays off (`FLEET_LIVE_EXECUTION=false`).

## Design

- Stack `darkbloom-fleet` (`deploy/stack.yml`), released by nxio-deploy with
  `stack_lint: true`, so the deployer pins digests and runs the cluster linter.
- `postgres`: `postgres:18-alpine`, data on
  `/mnt/gluster/apps/darkbloom-fleet/pgdata`, placed on brick hosts
  (`gluster == true`, `gluster_local == true`).
- `fleet`: the app on `production`/`stateless` nodes, read-only root, on
  `nginx_network` plus the stack's own `fleet_internal` overlay.
- External secrets: `darkbloom_fleet_db_password`, `darkbloom_fleet_ssh_key`,
  `darkbloom_fleet_ssh_config`, `darkbloom_fleet_ssh_known_hosts`. The app
  reads them through `DATABASE_PASSWORD_FILE` and `DARKBLOOM_SSH_CONFIG`.
- Ingress: nginx vhost `30-darkbloom-nxio.conf` to `darkbloom-fleet_fleet:8080`;
  Cloudflare DNS, nxio tunnel rule and Access app cloned from `uptime.nxio.ai`,
  whose policy allows only `email_domain` nxio.ai and gerighty.com.
- Backups: pg_back target `darkbloom-fleet-postgres` on `infra_age_recipient`,
  plus a verify-targets entry.

## Order (each step verified before the next)

1. Code: secret-file DB password and SSH config support, with tests.
2. Cluster prep: Swarm secrets, Gluster data and compose directories.
3. PR with `@coderabbitai ignore`; Sonar priority scan; CodeRabbit through a
   slot reservation; fix findings.
4. GitHub webhook; merge; confirm the queue `.done` file, the running image
   SHA, a healthy service, and the collector reading both Macs.
5. Cloudflare before the vhost exists, so the gap between the DNS record and
   the Access app only reaches nginx's default page. Verify a 302 to the
   Access login.
6. nginx vhost; verify all three replicas; verify the 302 again.
7. Backup registration; parity suite; pg_back and verifier deploys; first
   encrypted dump verified.
8. Retire the temporary docker compose copy on cm7.

## Rollback

- App: `docker service update --rollback`, or remove the stack. Data stays on
  Gluster.
- Cloudflare: the tunnel config saved before the change; remove the
  darkbloom Access app, DNS record and ingress rule.
- nginx: revert the vhost commit, push, rebuild the bundle.
