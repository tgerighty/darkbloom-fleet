from fleet import config


def test_secret_files_reach_the_config(monkeypatch, tmp_path):
    password = tmp_path / "db_password"
    password.write_text("s3cret\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fleet@db:5432/fleet")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(password))
    monkeypatch.setenv("DARKBLOOM_SSH_CONFIG", "/run/secrets/ssh_config")
    monkeypatch.setenv("DARKBLOOM_HOST_1_SSH_TARGET", "m3")
    monkeypatch.delenv("DARKBLOOM_HOST_2_SSH_TARGET", raising=False)

    (cfg,) = config.load_configs()

    assert "password=s3cret" in cfg.database_url
    assert "host=db" in cfg.database_url
    assert cfg.ssh_config_path == "/run/secrets/ssh_config"
