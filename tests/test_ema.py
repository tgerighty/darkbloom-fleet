import math
from fleet.scoring import update_ema

def test_update_ema_seeds_on_first_observation():
    ema = update_ema({}, {"a": 1.0}, dt_seconds=60, tau_minutes=20)
    assert ema == {"a": 1.0}


def test_update_ema_moves_toward_the_new_score_but_not_all_the_way():
    ema = update_ema({"a": 1.0}, {"a": 2.0}, dt_seconds=60, tau_minutes=20)
    alpha = 1 - math.exp(-60 / (20 * 60))
    assert math.isclose(ema["a"], 1.0 + alpha * 1.0)
    assert ema["a"] < 2.0


