"""Robot mode resolution: ROBOT_MODE_LOCK > ROBOT_MODE > runtime mode file (web UI) > robot.yaml."""

import pytest

from robot_tools import config


@pytest.fixture()
def cfg(monkeypatch, tmp_path):
    path = tmp_path / "robot.yaml"
    path.write_text("mode: real\n")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "run" / "mode")
    monkeypatch.delenv("ROBOT_MODE", raising=False)
    monkeypatch.delenv("ROBOT_MODE_LOCK", raising=False)
    config.load.cache_clear()
    yield config
    config.load.cache_clear()


def test_mode_file_overrides_yaml(cfg):
    assert cfg.load()["mode"] == "real"
    cfg.set_mode("sim")
    assert cfg.is_sim()
    cfg.set_mode(None)
    assert not cfg.MODE_FILE.exists() and cfg.load()["mode"] == "real"


def test_environment_overrides_mode_file(cfg, monkeypatch):
    cfg.set_mode("sim")
    monkeypatch.setenv("ROBOT_MODE", "real")
    cfg.load.cache_clear()
    assert cfg.load()["mode"] == "real"


def test_invalid_mode_rejected(cfg):
    with pytest.raises(ValueError):
        cfg.set_mode("hardware")
    assert not cfg.MODE_FILE.exists()


def test_mode_lock_overrides_everything(cfg, monkeypatch):
    cfg.set_mode("real")
    monkeypatch.setenv("ROBOT_MODE", "real")
    monkeypatch.setenv("ROBOT_MODE_LOCK", "SIM")
    cfg.load.cache_clear()
    assert cfg.locked_mode() == "sim" and cfg.is_sim()


def test_invalid_mode_lock_rejected(cfg, monkeypatch):
    monkeypatch.setenv("ROBOT_MODE_LOCK", "hardware")
    with pytest.raises(ValueError):
        cfg.load()
