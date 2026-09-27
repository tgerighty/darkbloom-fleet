-- Run once after the corrected collector has refreshed each configured host.
-- Removes #28 provider_id UUIDs, preserving collector hosts; rerunning is safe.
BEGIN;
DELETE FROM provider_identities AS identity
WHERE identity.host ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  AND NOT EXISTS (SELECT 1 FROM daemon_snapshots AS daemon WHERE daemon.host = identity.host);
COMMIT;
