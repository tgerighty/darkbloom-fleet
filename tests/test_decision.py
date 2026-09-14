import math

from fleet.decision import apply_host_gates, apply_inventory_gate, apply_warm_target_gate, decide, decide_pair, update_ema
from fleet.types import DaemonState, Decision, Guardrails, LOAD_ERROR_BLOCK_SECONDS

GUARDRAILS = Guardrails(relative_margin=0.25, absolute_margin=0.01, switch_cost_seconds=300.0,
                        decision_horizon_seconds=3600.0, min_dwell_seconds=1800.0)


def test_update_ema_seeds_on_first_observation():
    ema = update_ema({}, {"a": 1.0}, dt_seconds=60, tau_minutes=20)
    assert ema == {"a": 1.0}


def test_update_ema_moves_toward_the_new_score_but_not_all_the_way():
    ema = update_ema({"a": 1.0}, {"a": 2.0}, dt_seconds=60, tau_minutes=20)
    alpha = 1 - math.exp(-60 / (20 * 60))
    assert math.isclose(ema["a"], 1.0 + alpha * 1.0)
    assert ema["a"] < 2.0


def test_decide_waits_when_nothing_is_scored_yet():
    result = decide({}, current_model="a", last_switch_at=0, now=1000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "a" and result.action == "WAIT"


def test_decide_switches_to_the_only_scored_model_when_current_is_unscored():
    result = decide({"a": 1.0}, current_model=None, last_switch_at=0, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "a" and result.action == "SWITCH"


def test_decide_blocks_on_minimum_dwell_when_current_is_unscored():
    result = decide({"a": 1.0}, current_model=None, last_switch_at=9_900, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target is None and result.action == "KEEP" and "dwell" in result.reason


def test_decide_waits_for_idle_when_current_is_unscored_and_the_provider_is_busy():
    result = decide({"a": 1.0}, current_model=None, last_switch_at=0, now=10_000,
                    inference_active=True, guardrails=GUARDRAILS)
    assert result.target == "a" and result.action == "SWITCH_WHEN_IDLE" and "idle" in result.reason


def test_decide_keeps_current_when_it_ranks_first_after_switch_cost():
    result = decide({"a": 1.0, "b": 1.05}, current_model="a", last_switch_at=0, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "a" and "ranks first" in result.reason


def test_decide_keeps_current_when_challenger_is_below_margin():
    result = decide({"a": 1.0, "b": 1.2}, current_model="a", last_switch_at=0, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "a" and result.action == "KEEP" and "below margin" in result.reason


def test_decide_switches_when_challenger_clears_margin_dwell_and_idle():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=0, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "b" and result.action == "SWITCH"


def test_decide_blocks_on_minimum_dwell_even_with_a_clear_margin():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=9_900, now=10_000,
                    inference_active=False, guardrails=GUARDRAILS)
    assert result.target == "a" and "dwell" in result.reason


def test_decide_marks_switch_when_idle_while_the_provider_is_serving_a_request():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=0, now=10_000,
                    inference_active=True, guardrails=GUARDRAILS)
    assert result.target == "b" and result.action == "SWITCH_WHEN_IDLE" and "idle" in result.reason


NOW = 10_000.0
SWITCH = Decision("b", "b clears margin", "SWITCH")
WHEN_IDLE = Decision("b", "waiting for idle", "SWITCH_WHEN_IDLE")


def _daemon(**fields) -> DaemonState:
    return DaemonState("a", ("a",), False, 1, 0.0, True, **fields)


def test_serious_or_critical_thermal_blocks_a_switch():
    for thermal in ("serious", "critical"):
        result = apply_host_gates(SWITCH, _daemon(thermal_state=thermal), NOW)
        assert result.action == "BLOCKED" and result.target == "b"
        assert thermal in result.reason


def test_thermal_also_blocks_switch_when_idle():
    result = apply_host_gates(WHEN_IDLE, _daemon(thermal_state="serious"), NOW)
    assert result.action == "BLOCKED" and "serious" in result.reason


def test_nominal_thermal_does_not_block():
    result = apply_host_gates(SWITCH, _daemon(trust_level="hardware", thermal_state="nominal"), NOW)
    assert result == SWITCH


def test_keep_and_wait_pass_through_even_when_thermal_is_critical():
    keep = Decision("a", "ranks first", "KEEP")
    wait = Decision(None, "no scored models yet", "WAIT")
    hot = _daemon(thermal_state="critical")
    assert apply_host_gates(keep, hot, NOW) is keep
    assert apply_host_gates(wait, hot, NOW) is wait


def test_non_hardware_trust_keeps_current_and_does_not_restart():
    result = apply_host_gates(SWITCH, _daemon(trust_level="self_signed"), NOW)
    assert result.action == "KEEP" and result.target == "a"
    assert "self_signed" in result.reason and "attestation" in result.reason


def test_absent_trust_keeps_current_and_does_not_count_as_hardware():
    result = apply_host_gates(SWITCH, _daemon(), NOW)
    assert result.action == "KEEP" and result.target == "a"
    assert "unknown" in result.reason and "not hardware" in result.reason


def test_hardware_trust_leaves_a_switch_in_place():
    result = apply_host_gates(SWITCH, _daemon(trust_level="hardware"), NOW)
    assert result == SWITCH


def test_an_already_warm_target_does_not_cold_boot_a_multi_model_host():
    daemon = DaemonState("a", ("a", "b"), False, 1, 0.0, True)
    result = apply_warm_target_gate(SWITCH, daemon)
    assert result.action == "KEEP" and result.target == "b"
    assert "already warm" in result.reason


def test_pair_decision_keeps_or_replaces_the_two_model_set():
    ema = {"qwen": 2.0, "oss": 1.5, "gemma": 0.5}
    memory = {"qwen": 23.0, "oss": 14.0, "gemma": 18.0}
    keep = decide_pair(ema, ("oss", "qwen"), 0, NOW, False, GUARDRAILS, memory, 57.6)
    switch = decide_pair(ema, ("oss", "gemma"), 0, NOW, False, GUARDRAILS, memory, 57.6)
    assert keep.action == "KEEP" and keep.models == ("qwen", "oss")
    assert switch.action == "SWITCH" and switch.target == "qwen"
    assert switch.models == ("qwen", "oss")


def test_pair_decision_excludes_a_combination_that_does_not_fit():
    ema = {"large": 4.0, "medium": 2.0, "small": 1.0}
    memory = {"large": 40.0, "medium": 30.0, "small": 10.0}
    result = decide_pair(ema, ("medium", "small"), 0, NOW, False, GUARDRAILS, memory, 55.0)
    assert result.models == ("large", "small")


def test_a_recent_load_error_for_the_target_blocks():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_message="oom", last_model_load_error_at=NOW - 5)
    result = apply_host_gates(SWITCH, daemon, NOW)
    assert result.action == "BLOCKED" and result.target == "b"
    assert "b" in result.reason and "load" in result.reason


def test_a_load_error_at_the_120s_boundary_blocks():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_at=NOW - LOAD_ERROR_BLOCK_SECONDS)
    assert apply_host_gates(SWITCH, daemon, NOW).action == "BLOCKED"


def test_a_load_error_older_than_120s_does_not_block():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_at=NOW - LOAD_ERROR_BLOCK_SECONDS - 0.001)
    assert apply_host_gates(SWITCH, daemon, NOW) == SWITCH


def test_a_load_error_for_another_model_does_not_block():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="c",
                     last_model_load_error_at=NOW - 1)
    assert apply_host_gates(SWITCH, daemon, NOW) == SWITCH


def test_a_load_error_without_at_blocks():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_message="oom")
    result = apply_host_gates(SWITCH, daemon, NOW)
    assert result.action == "BLOCKED" and "no timestamp" in result.reason


def test_a_slightly_future_load_error_still_blocks():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_at=NOW + 2)
    assert apply_host_gates(SWITCH, daemon, NOW).action == "BLOCKED"


def test_a_far_future_load_error_blocks():
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="b",
                     last_model_load_error_at=NOW + LOAD_ERROR_BLOCK_SECONDS + 1)
    assert apply_host_gates(SWITCH, daemon, NOW).action == "BLOCKED"


def test_unknown_inventory_keeps_current_instead_of_switching():
    result = apply_inventory_gate(SWITCH, _daemon(installed_models=None))
    assert result.action == "KEEP" and result.target == "a"
    assert "inventory unknown" in result.reason
    idle = apply_inventory_gate(WHEN_IDLE, _daemon())
    assert idle.action == "KEEP" and idle.target == "a"


def test_a_known_target_absent_from_installed_ids_is_blocked():
    result = apply_inventory_gate(SWITCH, _daemon(installed_models=("a",)))
    assert result.action == "BLOCKED" and result.target == "b"
    assert "not installed" in result.reason


def test_a_known_installed_target_is_not_blocked_by_inventory():
    assert apply_inventory_gate(SWITCH, _daemon(installed_models=("a", "b"))) == SWITCH
    keep = Decision("a", "ranks first", "KEEP")
    assert apply_inventory_gate(keep, _daemon(installed_models=None)) is keep


def test_every_model_in_a_pair_must_be_installed_and_loadable():
    pair = Decision("b", "best pair", "SWITCH", ("b", "c"))
    inventory = apply_inventory_gate(pair, _daemon(installed_models=("a", "b")))
    daemon = _daemon(trust_level="hardware", last_model_load_error_model="c",
                     last_model_load_error_at=NOW - 1)
    assert inventory.action == "BLOCKED" and inventory.target == "c"
    assert apply_host_gates(pair, daemon, NOW).action == "BLOCKED"
