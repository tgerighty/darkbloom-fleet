"""Publish host-attributed earnings evidence; never control a provider."""
import asyncio
import contextlib
import json
import logging
import os
import shlex
import time

from . import remote

log = logging.getLogger('fleet.earnings_shadow')
WINDOW = 86400
INTERVAL = 300

EXPOSURE_SQL = """
WITH observations AS (
 SELECT observed_at, fresh, warm_models, manager,
        lead(observed_at) OVER (ORDER BY observed_at) next_at,
        CASE WHEN fresh AND cardinality(warm_models) = 1 THEN warm_models[1]
             ELSE manager->>'target_model' END model
 FROM daemon_snapshots WHERE host = %s AND observed_at BETWEEN %s AND %s
), intervals AS (
 SELECT *, next_at-observed_at seconds FROM observations
 WHERE next_at-observed_at BETWEEN 1 AND 90 AND model IS NOT NULL
)
SELECT i.model, sum(seconds) allocated_seconds,
 sum(CASE WHEN fresh AND warm_models = ARRAY[i.model] THEN seconds ELSE 0 END) warm_seconds,
 sum(d.pressure * seconds) / nullif(sum(CASE WHEN d.pressure IS NOT NULL THEN seconds ELSE 0 END),0) pressure_average
FROM intervals i LEFT JOIN LATERAL (
 SELECT pressure FROM demand_samples
 WHERE host = %s AND model = i.model AND observed_at BETWEEN i.observed_at-90 AND i.observed_at
 ORDER BY observed_at DESC LIMIT 1
) d ON true GROUP BY i.model
"""

PAYOUT_SQL = """
WITH identities AS (
 SELECT provider_hash, min(host) host FROM provider_identities
 GROUP BY provider_hash HAVING count(DISTINCT host) = 1
), payouts AS (
 SELECT DISTINCT ON (payout_rowid) provider_hash, model, micro_usd
 FROM earnings WHERE created_at BETWEEN %s AND %s AND model != 'base_reward'
 ORDER BY payout_rowid
)
SELECT e.model, count(*) paid_requests, sum(micro_usd)/1000000.0 inference_usd
FROM payouts e JOIN identities i USING (provider_hash)
WHERE i.host = %s GROUP BY e.model
"""


def build_profile(pool, host, now):
    start = now - WINDOW
    with pool.connection() as conn:
        exposures = conn.execute(EXPOSURE_SQL, (host, start, now, host)).fetchall()
        payouts = {r['model']: r for r in conn.execute(PAYOUT_SQL, (start, now, host)).fetchall()}
    models = {}
    for row in exposures:
        earnings = payouts.get(row['model'], {})
        models[row['model']] = {
            'allocated_seconds': float(row['allocated_seconds']),
            'warm_seconds': float(row['warm_seconds']),
            'pressure_average': float(row['pressure_average']) if row['pressure_average'] is not None else None,
            'paid_requests': int(earnings.get('paid_requests', 0)),
            'inference_usd': float(earnings.get('inference_usd', 0)),
        }
    return {'schema': 1, 'host': host, 'generated_at': now, 'window_start': start,
            'window_end': now, 'attribution': 'verified_provider_identity', 'models': models}


def publish(cfg, profile):
    # Only aggregated evidence crosses SSH; no account key or raw ledger rows.
    data = json.dumps(profile, allow_nan=False)
    script = """import os,pathlib,tempfile
p=pathlib.Path.home()/'.darkbloom/fleet-earnings-profile.json'
p.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.earnings-')
try:
 with os.fdopen(fd,'w') as f:
  f.write(DATA);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
finally:
 if os.path.exists(tmp):os.unlink(tmp)
""".replace('DATA', repr(data))
    remote._run_ssh(cfg, f"{shlex.quote(cfg.remote_python)} - <<'PY'\n{script}\nPY", timeout=20)


def tick(cfg, pool):
    profile = build_profile(pool, cfg.host_id, time.time())
    publish(cfg, profile)
    log.info('published earnings evidence for %s: %d models', cfg.host_id, len(profile['models']))


async def run_forever(cfg, pool, stop):
    if os.environ.get('FLEET_EARNINGS_SHADOW') != 'true':
        return
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick, cfg, pool)
        except Exception:
            log.exception('earnings profile refresh failed for %s', cfg.host_id)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), INTERVAL)
