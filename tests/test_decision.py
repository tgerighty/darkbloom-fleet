import math

from fleet.decision import decide, update_ema

MARGINS = dict(relative_margin=0.25, absolute_margin=0.01, switch_cost_seconds=300.0,
               decision_horizon_seconds=3600.0, min_dwell_seconds=1800.0)


def test_update_ema_seeds_on_first_observation():
    ema = update_ema({}, {"a": 1.0}, dt_seconds=60, tau_minutes=20)
    assert ema == {"a": 1.0}


def test_update_ema_moves_toward_the_new_score_but_not_all_the_way():
    ema = update_ema({"a": 1.0}, {"a": 2.0}, dt_seconds=60, tau_minutes=20)
    alpha = 1 - math.exp(-60 / (20 * 60))
    assert math.isclose(ema["a"], 1.0 + alpha * 1.0)
    assert ema["a"] < 2.0


def test_decide_switches_to_the_only_scored_model_when_current_is_unscored():
    result = decide({"a": 1.0}, current_model=None, last_switch_at=0, now=1000,
                     inference_active=False, **MARGINS)
    assert result.target == "a" and result.action == "SWITCH"


def test_decide_keeps_current_when_challenger_is_below_margin():
    result = decide({"a": 1.0, "b": 1.1}, current_model="a", last_switch_at=0, now=10_000,
                     inference_active=False, **MARGINS)
    assert result.target == "a" and result.action == "KEEP"


def test_decide_switches_when_challenger_clears_margin_dwell_and_idle():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=0, now=10_000,
                     inference_active=False, **MARGINS)
    assert result.target == "b" and result.action == "SWITCH"


def test_decide_blocks_on_minimum_dwell_even_with_a_clear_margin():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=9_900, now=10_000,
                     inference_active=False, **MARGINS)
    assert result.target == "a" and "dwell" in result.reason


def test_decide_blocks_while_the_provider_is_serving_a_request():
    result = decide({"a": 1.0, "b": 2.0}, current_model="a", last_switch_at=0, now=10_000,
                     inference_active=True, **MARGINS)
    assert result.target == "a" and "idle" in result.reason
