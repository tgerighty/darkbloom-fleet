from fleet.queries import _serving_shares


def _snap(t: float, model: str | None) -> dict:
    return {"observed_at": t, "current_model": model}


def test_a_snapshot_before_the_window_counts_from_the_window_start():
    shares = _serving_shares([_snap(900, "a"), _snap(1100, "b")], since=1000, now=1200)
    assert shares == {"a": 50.0, "b": 50.0}


def test_the_last_snapshot_holds_until_now():
    assert _serving_shares([_snap(1000, "a")], since=1000, now=1300) == {"a": 100.0}


def test_gaps_longer_than_ten_minutes_count_as_outage():
    shares = _serving_shares([_snap(0, "a"), _snap(60, "b"), _snap(2000, "a")], since=0, now=2060)
    assert shares == {"a": 100.0}


def test_a_stale_final_snapshot_does_not_cover_the_window():
    assert _serving_shares([_snap(0, "a")], since=0, now=1000) == {}
