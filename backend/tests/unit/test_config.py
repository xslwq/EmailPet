"""Tests for emailpet.config — YAML config loading."""
import pytest
import yaml
from pathlib import Path
from emailpet.config import Config


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Helper to write a yaml file."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True))
    return p


VALID_CONFIG = {
    "mail": {
        "imap": {"host": "imap.qq.com", "port": 993, "username": "u@qq.com", "password": "p"},
        "smtp": {"host": "smtp.qq.com", "port": 465, "username": "u@qq.com", "password": "p"},
        "poll_interval_seconds": 30,
    },
    "llm": {"base_url": "https://api.openai.com/v1", "api_key": "sk-x", "model": "gpt-4o-mini"},
    "server": {"ws_host": "127.0.0.1", "ws_port": 8765},
}


def test_load_config_success(tmp_path):
    p = _write_config(tmp_path, VALID_CONFIG)
    cfg = Config.from_yaml(p)
    assert cfg.imap.host == "imap.qq.com"
    assert cfg.imap.port == 993
    assert cfg.smtp.host == "smtp.qq.com"
    assert cfg.smtp.port == 465
    assert cfg.llm.base_url == "https://api.openai.com/v1"
    assert cfg.llm.api_key == "sk-x"
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.server.ws_host == "127.0.0.1"
    assert cfg.server.ws_port == 8765
    assert cfg.poll_interval_seconds == 30


def test_load_config_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        Config.from_yaml(tmp_path / "nope.yaml")


def test_load_config_missing_mail_section(tmp_path):
    bad = dict(VALID_CONFIG)
    del bad["mail"]
    p = _write_config(tmp_path, bad)
    with pytest.raises(ValueError, match="mail"):
        Config.from_yaml(p)


def test_load_config_missing_imap_field(tmp_path):
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    del bad["mail"]["imap"]["password"]
    p = _write_config(tmp_path, bad)
    with pytest.raises(ValueError, match="imap.password"):
        Config.from_yaml(p)


def test_load_config_missing_llm_field(tmp_path):
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    del bad["llm"]["api_key"]
    p = _write_config(tmp_path, bad)
    with pytest.raises(ValueError, match="llm.api_key"):
        Config.from_yaml(p)


def test_load_config_invalid_port(tmp_path):
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["mail"]["imap"]["port"] = 99999
    p = _write_config(tmp_path, bad)
    with pytest.raises(ValueError, match="port"):
        Config.from_yaml(p)


def test_load_config_default_poll_interval(tmp_path):
    """If poll_interval_seconds is missing, default to 30."""
    import copy
    cfg_data = copy.deepcopy(VALID_CONFIG)
    del cfg_data["mail"]["poll_interval_seconds"]
    p = _write_config(tmp_path, cfg_data)
    cfg = Config.from_yaml(p)
    assert cfg.poll_interval_seconds == 30


def test_load_config_default_server(tmp_path):
    """If server is missing, defaults to 127.0.0.1:8765."""
    import copy
    cfg_data = copy.deepcopy(VALID_CONFIG)
    del cfg_data["server"]
    p = _write_config(tmp_path, cfg_data)
    cfg = Config.from_yaml(p)
    assert cfg.server.ws_host == "127.0.0.1"
    assert cfg.server.ws_port == 8765


def test_load_config_root_not_dict(tmp_path):
    """YAML root that is not a mapping (e.g. a bare string) → ValueError."""
    p = tmp_path / "config.yaml"
    p.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        Config.from_yaml(p)


def test_load_config_nested_not_dict(tmp_path):
    """A nested section that should be a mapping but is a scalar → ValueError with field path."""
    p = tmp_path / "config.yaml"
    p.write_text("mail:\n  imap: oops\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mail.imap"):
        Config.from_yaml(p)
