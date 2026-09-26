import json

from fleet.watch import conditions, payload, transition


def test_watch_failure_timing_restart_and_recovery():
    healthy = {'provider_running': True, 'provider_fresh': True,
               'warm': ['gemma'], 'manager_running': True, 'manager_fresh': True,
               'pending': None, 'reason': ''}
    assert transition({}, conditions(healthy), 1000) == {}
    stopped = {**healthy, 'provider_running': False, 'manager_running': False}
    state = transition({}, conditions(stopped), 1000)
    assert payload('m1', state, 1299) == []
    state = transition(state, conditions(stopped), 1299)
    assert payload('m1', state, 1299) == []
    # Persistence round trip: an app restart must not reset the five-minute timer.
    state = transition(json.loads(json.dumps(state)), conditions(stopped), 1300)
    alerts = payload('m1', state, 1300)
    assert len(alerts) == 2
    assert all(a['labels']['instance'] == 'm1' for a in alerts)
    assert all(a['startsAt'] < a['endsAt'] for a in alerts)
    # A failure to read SSH must not falsely resolve an existing alert.
    unknown = transition(state, conditions(None), 1310)
    assert len(payload('m1', unknown, 1310)) == 2
    resolved = transition(unknown, conditions(healthy), 1320)
    assert all(a['endsAt'].endswith('00:22:00+00:00') for a in payload('m1', resolved, 1320))
    # Failed recovery delivery retains the original end timestamp for retry.
    assert transition(resolved, conditions(healthy), 1330) == resolved
    # A short outage that recovers never sends a notification.
    assert transition(transition({}, conditions(stopped), 1), conditions(healthy), 299) == {}


def test_switch_error_alerts_immediately_but_normal_warmup_does_not():
    status = {'provider_running': True, 'provider_fresh': True,
              'warm': ['oss'], 'manager_running': True, 'manager_fresh': True,
              'pending': {'target': 'gemma'}, 'reason': 'waiting for Darkbloom to finish loading'}
    assert transition({}, conditions(status), 1000) == {}
    status['pending']['command_error'] = 'launchctl bootstrap failed'
    state = transition({}, conditions(status), 1000)
    alerts = payload('m3', state, 1000)
    assert len(alerts) == 1
    assert alerts[0]['labels']['alertname'] == 'DarkbloomManagerSwitchFailed'
    assert 'gemma' in alerts[0]['annotations']['description']
    assert 'ended' not in transition(state, conditions(None), 1001)['DarkbloomManagerSwitchFailed']
    missing_manager = {**status, 'manager_fresh': False, 'pending': None}
    assert 'ended' not in transition(state, conditions(missing_manager), 1001)['DarkbloomManagerSwitchFailed']
    # Correct warm state proves recovery before the manager clears its old error.
    status['warm'] = ['gemma']
    assert transition(state, conditions(status), 1002)['DarkbloomManagerSwitchFailed']['ended'] == 1002
    status['warm'] = []
    status['pending'].pop('command_error')
    status['reason'] = 'model loading exceeded 3m; automatic restart is blocked'
    assert conditions(status)['DarkbloomManagerSwitchFailed']


def test_empty_pending_switch_keeps_healthy_provider_state():
    status = {'provider_running': True, 'provider_fresh': True,
              'manager_running': True, 'manager_fresh': True,
              'pending': [], 'warm': [], 'reason': ''}
    result = conditions(status)
    assert result['DarkbloomProviderUnavailable'] is False
    assert result['DarkbloomManagerSwitchFailed'] is False


def test_malformed_pending_switch_keeps_provider_status():
    status = {'provider_running': True, 'provider_fresh': True,
              'manager_running': True, 'manager_fresh': True,
              'warm': [], 'reason': ''}
    for pending in ('broken', [1]):
        result = conditions({**status, 'pending': pending})
        assert result['DarkbloomProviderUnavailable'] is False
        assert result['DarkbloomManagerSwitchFailed'] is False


def test_malformed_probe_cannot_claim_a_healthy_provider():
    status = {'provider_running': 'yes', 'provider_fresh': True, 'manager_running': True,
              'manager_fresh': True, 'warm': [], 'pending': None, 'reason': ''}
    assert conditions(status)['DarkbloomProviderUnavailable'] is not False


def test_missing_optional_reason_keeps_valid_provider_and_manager_signals():
    status = {'provider_running': True, 'provider_fresh': True, 'manager_running': False,
              'manager_fresh': True, 'warm': [], 'pending': {'target': 'm'}, 'reason': None}
    result = conditions(status)
    assert result['DarkbloomProviderUnavailable'] is False
    assert result['DarkbloomManagerUnavailable'] == (300, 'Model manager is stopped or its decisions are stale.')


def test_malformed_saved_alert_does_not_block_valid_alert_delivery():
    saved = {'DarkbloomProviderUnavailable': {'since': 'bad', 'firing': False, 'detail': 'bad'},
             'DarkbloomManagerUnavailable': {'since': 1000, 'firing': True, 'detail': 'stopped'},
             'unknown': {'since': 1000, 'firing': True, 'detail': 'bad'}}
    observed = {'DarkbloomProviderUnavailable': (300, 'provider stopped'),
                'DarkbloomManagerUnavailable': None}
    state = transition(saved, observed, 1300)
    assert state['DarkbloomProviderUnavailable']['since'] == 1300
    assert len(payload('m1', state, 1300)) == 1
