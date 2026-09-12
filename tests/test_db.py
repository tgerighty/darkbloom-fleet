from fleet import db
from fleet.types import CapacitySample, DaemonState, Decision, Outcome, Payout


def test_get_pool_uses_dict_rows(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "ConnectionPool", lambda url, **kwargs: seen.update(url=url, **kwargs) or "pool")
    assert db.get_pool("postgresql://x") == "pool"
    assert seen["url"] == "postgresql://x" and seen["kwargs"] == {"row_factory": db.dict_row}


def test_init_schema_runs_the_schema(fake_pool):
    pool = fake_pool()
    db.init_schema(pool)
    assert pool.calls == [(db.SCHEMA_SQL, None)]


def test_bulk_inserts_skip_empty_input(fake_pool):
    pool = fake_pool()
    db.insert_demand_samples(pool, "h", 1.0, {}, {}, {}, {})
    db.insert_payouts(pool, "h", [], 1.0)
    db.save_ema(pool, "h", {}, 1.0)
    assert pool.calls == []


def test_bulk_inserts_write_one_row_per_item(fake_pool):
    pool = fake_pool()
    db.insert_demand_samples(pool, "h", 1.0, {"m": CapacitySample("m", 2, 1, 2.0)}, {"m": 0.5}, {"m": 0.1}, {"m": 0.4})
    db.insert_payouts(pool, "h", [Payout(7, "m", 10, 25, 3.0)], 4.0)
    db.save_ema(pool, "h", {"m": 0.4}, 5.0)
    assert [rows for _sql, rows in pool.calls] == [
        [("h", 1.0, "m", 2, 1, 2.0, 0.1, 0.5, 0.4)],
        [("h", 7, "m", 10, 25, 3.0, 4.0)],
        [("h", "m", 0.4, 5.0)],
    ]


def test_daemon_snapshots_and_decisions_are_written(fake_pool):
    pool = fake_pool([], [{"id": 9}], [])
    db.insert_daemon_snapshot(pool, "h", 1.0, DaemonState("m", ("m",), False, 42, 0.5, True))
    decision_id = db.insert_decision(pool, "h", 2.0, "m", Decision("n", "why", "SWITCH"), Outcome("live", False, None))
    db.record_outcome(pool, decision_id, Outcome("live", True, None))
    assert decision_id == 9
    assert pool.calls[0][1] == ("h", 1.0, "m", ["m"], False, True, 42, 0.5, [], 0)
    assert pool.calls[1][1] == ("h", 2.0, "m", "n", "SWITCH", "why", "live", False, None)
    assert pool.calls[2][1] == ("live", True, None, 9)


def test_self_route_samples_record_an_empty_probe_too(fake_pool):
    pool = fake_pool()
    db.insert_self_route_samples(pool, 1.0, {"a": 2})
    db.insert_self_route_samples(pool, 2.0, {})
    assert [rows for _sql, rows in pool.calls] == [[(1.0, "a", 2)], [(2.0, "", 0)]]


def test_reads_fall_back_to_zero_when_the_tables_are_empty(fake_pool):
    pool = fake_pool([{"m": None}], [], [{"t": None}], [{"t": None}])
    assert db.last_payout_rowid(pool, "h") == 0
    assert db.load_ema(pool, "h") == ({}, 0.0)
    assert db.dwell_anchor(pool, "h", 0.0) == 0.0
    assert db.last_failed_switch_at(pool, "h") == 0.0


def test_reads_return_the_stored_values(fake_pool):
    ema_rows = [{"model": "a", "value": 0.3, "updated_at": 5.0}, {"model": "b", "value": 0.1, "updated_at": 7.0}]
    pool = fake_pool([{"m": 12}], ema_rows, [{"t": 100.0}], [{"t": 50.0}])
    assert db.last_payout_rowid(pool, "h") == 12
    assert db.load_ema(pool, "h") == ({"a": 0.3, "b": 0.1}, 7.0)
    assert db.dwell_anchor(pool, "h", 200.0) == 200.0
    assert db.last_failed_switch_at(pool, "h") == 50.0
