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
