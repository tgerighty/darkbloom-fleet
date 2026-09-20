from fleet import db
from fleet.types import CapacitySample, DaemonState, Payout, Slot


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
    db.insert_payouts(pool, "h", [Payout(7, "m", 10, 25, 3.0, "session-1")], 4.0)
    db.save_ema(pool, "h", {"m": 0.4}, 5.0)
    assert [rows for _sql, rows in pool.calls] == [
        [("h", 1.0, "m", 2, 1, 2.0, 0.1, 0.5, 0.4, None, None, None)],
        [("h", 7, "m", 10, 25, 3.0, "session-1", 4.0)],
        [("h", "m", 0.4, 5.0)],
    ]


def test_daemon_snapshots_are_written(fake_pool):
    pool = fake_pool([], [{"id": 9}], [])
    daemon = DaemonState("m", ("m",), False, 42, 0.5, True, thermal_state="nominal", memory_pressure=0.41,
                         cpu_usage=0.12, fan_rpm=1780.0, peak_temperature_c=62.5, gpu_active_gb=14.8,
                         gpu_cache_gb=1.2, total_memory_gb=64.0, slots=(Slot("m", "paged", True, False, "idle"),))
    db.insert_daemon_snapshot(pool, "h", 1.0, daemon)
    assert pool.calls[0][1][:20] == ("h", 1.0, "m", ["m"], False, True, 42, 0.5, [], 0, None, None,
                                     "nominal", 0.41, 0.12, 1780.0, 62.5, 14.8, 1.2, 64.0)
    assert pool.calls[0][1][-2].obj == [{"model": "m", "kv_backend": "paged", "mtp_enabled": True,
                                         "mtp_active": False, "mtp_inactive_reason": "idle"}]
    assert pool.calls[0][1][-1] is None
    assert pool.calls[0][1][20:23] == (None, None, None)
    assert pool.calls[0][1][23] is None


def test_daemon_snapshots_persist_last_model_load_error(fake_pool):
    pool = fake_pool()
    daemon = DaemonState("m", ("m",), False, 1, 0.5, True, last_model_load_error_model="n",
                         last_model_load_error_message="oom", last_model_load_error_at=99.0)
    db.insert_daemon_snapshot(pool, "h", 1.0, daemon)
    sql, row = pool.calls[0]
    assert "last_model_load_error_model" in sql
    assert "last_model_load_error_message" in sql
    assert "last_model_load_error_at" in sql
    assert row[20:23] == ("n", "oom", 99.0)
    assert "last_model_load_error_model" in db.SCHEMA_SQL
    assert "last_model_load_error_at" in db.SCHEMA_SQL


def test_daemon_snapshots_persist_nullable_installed_models(fake_pool):
    known = fake_pool()
    db.insert_daemon_snapshot(
        known, "h", 1.0, DaemonState("m", ("m",), False, 1, 0.5, True, installed_models=("a", "b")))
    empty = fake_pool()
    db.insert_daemon_snapshot(
        empty, "h", 1.0, DaemonState("m", ("m",), False, 1, 0.5, True, installed_models=()))
    unknown = fake_pool()
    db.insert_daemon_snapshot(unknown, "h", 1.0, DaemonState("m", ("m",), False, 1, 0.5, True))
    assert known.calls[0][1][23] == ["a", "b"]
    assert empty.calls[0][1][23] == []
    assert unknown.calls[0][1][23] is None
    assert "installed_models TEXT[]" in db.SCHEMA_SQL
    assert "installed_models TEXT[] NOT NULL" not in db.SCHEMA_SQL


def test_daemon_snapshots_persist_manager_report(fake_pool):
    pool = fake_pool()
    daemon = DaemonState("m", ("m",), False, 1, 0.5, True,
                         manager={"mode": "LIVE"})
    db.insert_daemon_snapshot(pool, "h", 1.0, daemon)
    assert pool.calls[0][1][-1].obj == {"mode": "LIVE"}


def test_self_route_samples_record_an_empty_probe_too(fake_pool):
    pool = fake_pool()
    db.insert_self_route_samples(pool, 1.0, {"a": 2})
    db.insert_self_route_samples(pool, 2.0, {})
    assert [rows for _sql, rows in pool.calls] == [[(1.0, "a", 2)], [(2.0, "", 0)]]


def test_reads_fall_back_to_zero_when_the_tables_are_empty(fake_pool):
    pool = fake_pool([{"m": None}], [], [{"t": None}], [{"t": None}])
    assert db.last_payout_rowid(pool, "h") == 0
    assert db.load_ema(pool, "h") == ({}, 0.0)


def test_delete_ineligible_ema_drops_models_outside_the_set(fake_pool):
    pool = fake_pool()
    db.delete_ineligible_ema(pool, "h", frozenset({"a", "b"}))
    sql, params = pool.calls[0]
    assert "DELETE FROM ema_state" in sql
    assert "NOT (model = ANY(%s))" in sql
    assert params[0] == "h" and set(params[1]) == {"a", "b"}
    empty = fake_pool()
    db.delete_ineligible_ema(empty, "h", frozenset())
    empty_sql, empty_params = empty.calls[0]
    assert "DELETE FROM ema_state WHERE host = %s" in empty_sql
    assert "ANY" not in empty_sql
    assert empty_params == ("h",)


def test_update_snapshot_installed_models_targets_the_tick_row(fake_pool):
    pool = fake_pool()
    db.update_snapshot_installed_models(pool, "h", 1.0, ("a", "b"))
    sql, params = pool.calls[0]
    assert "UPDATE daemon_snapshots SET installed_models = %s" in sql
    assert params == (["a", "b"], "h", 1.0)


def test_reads_return_the_stored_values(fake_pool):
    ema_rows = [{"model": "a", "value": 0.3, "updated_at": 5.0}, {"model": "b", "value": 0.1, "updated_at": 7.0}]
    pool = fake_pool([{"m": 12}], ema_rows, [{"t": 100.0}], [{"t": 50.0}])
    assert db.last_payout_rowid(pool, "h") == 12
    assert db.load_ema(pool, "h") == ({"a": 0.3, "b": 0.1}, 7.0)


def test_demand_sample_insert_persists_tps_fields(fake_pool):
    pool = fake_pool()
    sample = CapacitySample("m", 2, 1, 2.0, observed_prefill_tps=11.0,
                            observed_decode_tps=7.5, aggregate_tps=90.0)
    db.insert_demand_samples(pool, "h", 1.0, {"m": sample}, {"m": 0.5}, {"m": 0.1}, {"m": 0.4})
    assert pool.calls[0][1] == [("h", 1.0, "m", 2, 1, 2.0, 0.1, 0.5, 0.4, 11.0, 7.5, 90.0)]
    assert "observed_prefill_tps" in pool.calls[0][0]
    assert "observed_decode_tps" in pool.calls[0][0]
    assert "aggregate_tps" in pool.calls[0][0]
