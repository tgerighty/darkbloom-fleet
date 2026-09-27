-- Remap-then-join repair for provider identity hosts (idempotent).
--
-- Context: #28 stored Darkbloom provider_id (UUID) in provider_identities.host
-- (correct key). #31 also wrote fleet host_ids (m3-48-1 / M1-64-1) for some
-- hashes, which dual-keyed the same sessions and hid Jobs on configured cards
-- that filtered only by fleet host_id. Do NOT delete UUID identity rows.
--
-- This script:
--   1) Backfills provider_fleet_hosts (UUID -> fleet host_id) from shared-hash
--      majority votes among non-UUID identity hosts / daemon hosts.
--   2) Removes bare fleet-host_id rows from provider_identities so the UUID
--      remains the sole identity key (dashboard joins via provider_fleet_hosts).
--
-- Safe to re-run. Does not touch earnings.host. Wait for Terry Merge/Hold
-- before applying on live Postgres.

-- ---------------------------------------------------------------------------
-- Dry-run previews (run these SELECTs first; they mutate nothing)
-- ---------------------------------------------------------------------------
-- SELECT uuid_id.host AS provider_id, fleet_id.host AS fleet_host,
--        count(*) AS shared_hashes
-- FROM provider_identities AS uuid_id
-- JOIN provider_identities AS fleet_id
--   ON fleet_id.provider_hash = uuid_id.provider_hash
--  AND fleet_id.host <> uuid_id.host
-- WHERE uuid_id.host ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
--   AND fleet_id.host !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
-- GROUP BY uuid_id.host, fleet_id.host
-- ORDER BY shared_hashes DESC;

BEGIN;

CREATE TABLE IF NOT EXISTS provider_fleet_hosts (
    provider_id TEXT PRIMARY KEY,
    fleet_host TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS provider_fleet_hosts_fleet
    ON provider_fleet_hosts (fleet_host);

WITH shared AS (
    SELECT uuid_id.host AS provider_id,
           fleet_id.host AS fleet_host,
           count(*)::bigint AS shared_hashes
    FROM provider_identities AS uuid_id
    JOIN provider_identities AS fleet_id
      ON fleet_id.provider_hash = uuid_id.provider_hash
     AND fleet_id.host <> uuid_id.host
    WHERE uuid_id.host ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      AND fleet_id.host !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    GROUP BY uuid_id.host, fleet_id.host
), ranked AS (
    SELECT provider_id, fleet_host, shared_hashes,
           rank() OVER (PARTITION BY provider_id ORDER BY shared_hashes DESC, fleet_host) AS rnk,
           count(*) OVER (PARTITION BY provider_id, shared_hashes) AS ties_at_top
    FROM shared
), winners AS (
    SELECT provider_id, fleet_host
    FROM ranked
    WHERE rnk = 1 AND ties_at_top = 1
)
INSERT INTO provider_fleet_hosts (provider_id, fleet_host)
SELECT provider_id, fleet_host FROM winners
ON CONFLICT (provider_id) DO NOTHING;

-- Drop fleet-host_id identity rows only (keep UUID keys). History stays on UUID;
-- build_status joins UUID -> fleet label via provider_fleet_hosts.
DELETE FROM provider_identities AS identity
WHERE identity.host !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

COMMIT;
