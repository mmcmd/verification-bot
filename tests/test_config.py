import json

import pytest

from verification_bot.config import ConfigError, config_from_mapping, load_config, load_messages

VALID = {"token": "token-value", "homeserver_id": "1", "irc_relay_id": "irc-relay"}


@pytest.fixture(autouse=True)
def _no_token_in_environment(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)


def test_server_id_is_coerced_to_int():
    config = config_from_mapping(VALID)
    assert config.home_server_id == 1
    assert config.irc_relay_id == "irc-relay"


def test_token_env_var_wins(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "from-env")
    assert config_from_mapping(VALID).token == "from-env"


def test_token_is_not_shown_in_repr():
    assert "token-value" not in repr(config_from_mapping(VALID))


def test_missing_server_id_is_reported():
    with pytest.raises(ConfigError, match="homeserver_id"):
        config_from_mapping({"token": "token-value"})


def test_non_numeric_id_is_rejected():
    with pytest.raises(ConfigError, match="homeserver_id"):
        config_from_mapping({**VALID, "homeserver_id": "not-a-number"})


def test_missing_token_is_rejected():
    with pytest.raises(ConfigError, match="token"):
        config_from_mapping({**VALID, "token": ""})


def test_null_token_is_treated_as_missing():
    with pytest.raises(ConfigError, match="token"):
        config_from_mapping({**VALID, "token": None})


@pytest.mark.parametrize("value", ["", None])
def test_optional_irc_relay_id(value):
    assert config_from_mapping({**VALID, "irc_relay_id": value}).irc_relay_id is None


def test_old_style_keys_are_ignored_here():
    """A legacy config.json still loads; its extra keys are imported elsewhere."""
    config = config_from_mapping({**VALID, "prefix": "+", "verified_role": "2", "status": "x"})
    assert config.home_server_id == 1


def test_load_config_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_load_config_reports_bad_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_shipped_example_config_is_valid():
    with open("config.json.example", encoding="utf-8") as stream:
        data = json.load(stream)
    assert set(data) == {"token", "homeserver_id", "irc_relay_id"}


def test_shipped_messages_load():
    messages = load_messages()
    assert "verification" in messages
    assert "emergency" in messages
