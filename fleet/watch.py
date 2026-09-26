"""Read-only Mac watchdog. Alertmanager owns grouping, repeats and Discord delivery."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import shlex
import time
import urllib.request

from psycopg.types.json import Jsonb

from . import remote

log = logging.getLogger("fleet.watch")
INTERVAL = 30
GRACE = 300
SUMMARIES = {
    "DarkbloomProviderUnavailable": "provider unavailable for five minutes",
    "DarkbloomManagerUnavailable": "model manager unavailable for five minutes",
    "DarkbloomManagerSwitchFailed": "model switch failed",
}
# A separate small SSH read keeps earnings and demand-feed delays out of alerts.
PROBE = '''import json, pathlib, subprocess, os, time
p = pathlib.Path.home()
def read(path):
    try:
        value = json.loads((p/path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}
def running(label):
    r = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{label}'], capture_output=True, text=True, timeout=5)
    return r.returncode == 0 and any(line.strip() == 'state = running' for line in r.stdout.splitlines())
s = read('.darkbloom/daemon-state.json')
m = read('.local/share/benbuschmann-darkbloom-manager/state.json')
print(json.dumps({'provider_running': running('io.darkbloom.provider') or running('dev.darkbloom.provider'),
    'provider_fresh': abs(time.time() - float(s.get('written_at') or 0)) < 90,
    'warm': s.get('warm_models', []), 'manager_running': running('dev.darkbloom.warm-manager-live'),
    'manager_fresh': abs(time.time() - float(m.get('last_decision_at') or 0)) < 180,
    'pending': m.get('pending_switch'), 'reason': m.get('last_decision_reason', '')}))
'''


def _switch_condition(status: dict[str, object], provider: bool, manager: bool) -> tuple[int, str] | bool | None:
    warm = status.get('warm')
    if not _valid_warm(warm):
        return None
    pending = status.get('pending')
    pending = pending if isinstance(pending, dict) else {}
    target = pending.get('target')
    recovered = provider and status.get('warm') == [target]
    reason = status.get('reason')
    reason = reason if isinstance(reason, str) else ''
    failed = target and not recovered and (pending.get('command_error') or
                                         'automatic restart is blocked' in reason)
    if failed:
        return 0, f"Model manager failed to start {str(target)[:160]}. Check the manager log."
    return False if manager or recovered else None


def _valid_warm(warm: object) -> bool:
    return isinstance(warm, list) and all(isinstance(model, str) for model in warm)


def _valid_probe(status: object) -> bool:
    return isinstance(status, dict) and all(type(status.get(key)) is bool for key in
                                            ('provider_running', 'provider_fresh', 'manager_running', 'manager_fresh'))


def conditions(status):
    """None means unknown: retain an existing switch alert until a good read."""
    if status is not None and not _valid_probe(status):
        status = None
    if status is None:
        return {"DarkbloomProviderUnavailable": (GRACE, "Machine cannot be reached; provider status is unknown."),
                "DarkbloomManagerUnavailable": None, "DarkbloomManagerSwitchFailed": None}
    provider = status['provider_running'] and status['provider_fresh']
    manager = status['manager_running'] and status['manager_fresh']
    return {
        "DarkbloomProviderUnavailable": False if provider else (GRACE, "Provider is stopped or its heartbeat is stale."),
        "DarkbloomManagerUnavailable": False if manager else (GRACE, "Model manager is stopped or its decisions are stale."),
        "DarkbloomManagerSwitchFailed": _switch_condition(status, provider, manager),
    }


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        dt.datetime.fromtimestamp(value, dt.timezone.utc)
        return True
    except (OverflowError, OSError, ValueError):
        return False


def _valid_record(value: object) -> bool:
    return (isinstance(value, dict) and _finite_number(value.get('since'))
            and type(value.get('firing')) is bool and isinstance(value.get('detail'), str)
            and ('ended' not in value or _finite_number(value['ended'])))


def _saved_state(saved: object) -> dict[str, dict[str, object]]:
    if not isinstance(saved, dict):
        return {}
    return {name: dict(value) for name, value in saved.items()
            if name in SUMMARIES and _valid_record(value)}


def _advance_alert(state: dict[str, dict[str, object]], name: str,
                   condition: tuple[int, str] | bool | None, now: float) -> None:
    if condition is None:
        return
    if condition is False:
        item = state.get(name)
        if item and item['firing']:
            item.setdefault('ended', now)
        else:
            state.pop(name, None)
        return
    delay, detail = condition
    if name not in state or 'ended' in state[name]:
        state[name] = {'since': now, 'firing': False}
    item = state[name]
    item['detail'] = detail
    item['firing'] = item['firing'] or now - item['since'] >= delay


def transition(saved: object, observed: dict[str, tuple[int, str] | bool | None],
               now: float) -> dict[str, dict[str, object]]:
    state = _saved_state(saved)
    for name, condition in observed.items():
        _advance_alert(state, name, condition, now)
    return state


def timestamp(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def payload(host, state, now):
    return [{
        'labels': {'alertname': name, 'cluster': 'darkbloom', 'instance': host,
                   'severity': 'critical', 'service': 'darkbloom-fleet'},
        'annotations': {'summary': f'{host}: {SUMMARIES[name]}',
                        'description': item['detail']},
        'startsAt': timestamp(item['since']),
        'endsAt': timestamp(item.get('ended', now + 300)),
        'generatorURL': 'https://darkbloom.nxio.ai',
    } for name, item in state.items() if item['firing']]


def save(conn, host, state):
    conn.execute('INSERT INTO watch_state (host, state) VALUES (%s, %s) '
                 'ON CONFLICT (host) DO UPDATE SET state = EXCLUDED.state', (host, Jsonb(state)))


def tick(cfg, pool, url):
    try:
        raw = remote._run_ssh(cfg, f"{shlex.quote(cfg.remote_python)} - <<'PY'\n{PROBE}\nPY", timeout=25)
        status = json.loads(raw)
        observed = conditions(status)
    except Exception:
        log.warning('watch probe unavailable for %s', cfg.host_id)
        observed = conditions(None)
    now = time.time()
    with pool.connection() as conn:
        row = conn.execute('SELECT state FROM watch_state WHERE host = %s', (cfg.host_id,)).fetchone()
        state = transition(row['state'] if row else {}, observed, now)
        save(conn, cfg.host_id, state)
    alerts = payload(cfg.host_id, state, now)
    if alerts:
        request = urllib.request.Request(url.rstrip('/') + '/api/v2/alerts',
                                         data=json.dumps(alerts).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('Alertmanager rejected alerts')
        # Keep resolved records until delivery succeeds, including across restarts.
        with pool.connection() as conn:
            save(conn, cfg.host_id, {k: v for k, v in state.items() if 'ended' not in v})
    log.info('checked %s: %s', cfg.host_id, ', '.join(state) or 'healthy')


async def run_forever(cfg, pool, stop):
    url = os.environ.get('FLEET_ALERTMANAGER_URL')
    if not url:
        return
    while not stop.is_set():
        started = time.monotonic()
        try:
            await asyncio.to_thread(tick, cfg, pool, url)
        except Exception:
            log.exception('watch check or alert delivery failed for %s', cfg.host_id)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), max(0.1, INTERVAL - (time.monotonic() - started)))
