import pytest

from fleet import config


@pytest.fixture
def base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fleet@db:5432/fleet")
    monkeypatch.delenv("DATABASE_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("DARKBLOOM_HOST_1_SSH_TARGET", "m3")
    monkeypatch.delenv("DARKBLOOM_HOST_2_SSH_TARGET", raising=False)
    return monkeypatch


def test_secret_files_reach_the_config(base_env, tmp_path):
    password = tmp_path / "db_password"
    password.write_text("s3cret\n")
    base_env.setenv("DATABASE_PASSWORD_FILE", str(password))
    base_env.setenv("DARKBLOOM_SSH_CONFIG", "/run/secrets/ssh_config")

    (cfg,) = config.load_configs()

    assert "password=s3cret" in cfg.database_url
    assert "host=db" in cfg.database_url
    assert cfg.ssh_config_path == "/run/secrets/ssh_config"


@pytest.mark.parametrize(("name", "value"), [
    ("FLEET_EMA_TAU_MINUTES", "0"),
    ("POLL_INTERVAL_SECONDS", "-1"),
    ("FLEET_DECISION_HORIZON_SECONDS", "soon"),
    ("FLEET_RELATIVE_MARGIN", "nan"),
    ("FLEET_MIN_DWELL_SECONDS", "inf"),
])
def test_invalid_numeric_settings_are_rejected(base_env, name, value):
    base_env.setenv(name, value)
    with pytest.raises(RuntimeError, match=name):
        config.load_configs()


def test_zero_is_allowed_where_it_means_something(base_env):
    base_env.setenv("FLEET_MIN_DWELL_SECONDS", "0")
    (cfg,) = config.load_configs()
    assert cfg.min_dwell_seconds == 0.0


def test_duplicate_host_labels_are_rejected(base_env):
    base_env.setenv("DARKBLOOM_HOST_2_SSH_TARGET", "m1")
    base_env.setenv("DARKBLOOM_HOST_1_LABEL", "mac")
    base_env.setenv("DARKBLOOM_HOST_2_LABEL", "mac")
    with pytest.raises(RuntimeError, match="unique"):
        config.load_configs()


def test_host_ids_default_to_the_ssh_target_and_read_their_own_variable(base_env):
    base_env.setenv("DARKBLOOM_HOST_1_ID", "mac-1")
    base_env.setenv("DARKBLOOM_HOST_2_SSH_TARGET", "m1")
    first, second = config.load_configs()
    assert first.host_id == "mac-1" and second.host_id == "m1"


def test_duplicate_host_ids_are_rejected(base_env):
    base_env.setenv("DARKBLOOM_HOST_2_SSH_TARGET", "m1")
    base_env.setenv("DARKBLOOM_HOST_1_ID", "mac")
    base_env.setenv("DARKBLOOM_HOST_2_ID", "mac")
    with pytest.raises(RuntimeError, match="host ids"):
        config.load_configs()


def test_database_url_is_required(base_env):
    base_env.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        config.load_configs()


def test_at_least_one_host_is_required(base_env):
    base_env.delenv("DARKBLOOM_HOST_1_SSH_TARGET")
    with pytest.raises(RuntimeError, match="At least one host"):
        config.load_configs()


def test_the_consumer_key_is_shared_but_only_the_first_host_probes(base_env, tmp_path):
    key = tmp_path / "api_key"
    key.write_text("k-123\n")
    base_env.setenv("DARKBLOOM_API_KEY_FILE", str(key))
    base_env.setenv("DARKBLOOM_HOST_2_SSH_TARGET", "m1")
    first, second = config.load_configs()
    assert first.api_key == second.api_key == "k-123"
    assert first.probe_self_route is True and second.probe_self_route is False


def test_per_host_live_execution_overrides_the_default(base_env):
    base_env.setenv("DARKBLOOM_HOST_1_LIVE_EXECUTION", "yes")
    (cfg,) = config.load_configs()
    assert cfg.live_execution is True
