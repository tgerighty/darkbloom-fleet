-- Run once after the corrected collector has refreshed each configured host.
-- Removes only #28 provider_id UUIDs; rerunning is safe. Do not run from Rig.
BEGIN;
DELETE FROM provider_identities
WHERE host ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
COMMIT;
