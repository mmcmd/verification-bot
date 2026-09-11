import json

import pytest

from verification_bot.config import ConfigError, config_from_mapping, load_config, load_messages

VALID = {
    "token": "token-value",
    "homeserver_id": "1",
    "status": "hello",
    "verified_role": "2",
    "verification_requirement_join": "90",
    "verification_requirement_message": "5",
    "moderator_mail_id": "3",
    "moderator_role_IDs": ["4", "5"],
    "log_channel_id": "6",
    "unboost_announcement_channel_id": "7",
    "rules_channel_id": "8",
    "roles_channel_id": "9",
    "colored_roles": ["10", "11"],
    "ontopic_category_id": "13",
    "emergency_role_id": "14",
    "emergency_request_approval_threshold": "3",
    "emergency_request_deny_threshold": "2",
    "emergency_role_reminder": "180",
    "emergency_role_timeout": "5",
    "emergency_top_role_bypass_id": ["15"],
    "irc_relay_id": "abc123",
}


def test_values_are_coerced_to_ints():
    config = config_from_mapping(VALID)
    assert config.home_server_id == 1
    assert config.moderator_role_ids == (4, 5)
    assert config.colored_role_ids == (10, 11)


def test_emergency_timeout_is_derived():
    config = config_from_mapping(VALID)
    assert config.emergency_total_timeout_seconds == 900


def test_token_env_var_wins(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "from-env")
    assert config_from_mapping(VALID).token == "from-env"


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    data = {key: value for key, value in VALID.items() if key != "verified_role"}
    with pytest.raises(ConfigError, match="verified_role"):
        config_from_mapping(data)


def test_non_numeric_id_is_rejected(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="homeserver_id"):
        config_from_mapping({**VALID, "homeserver_id": "not-a-number"})


def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="token"):
        config_from_mapping({**VALID, "token": ""})


def test_optional_irc_relay_id(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    assert config_from_mapping({**VALID, "irc_relay_id": ""}).irc_relay_id is None


def test_reminder_interval_floor(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="emergency_role_reminder"):
        config_from_mapping({**VALID, "emergency_role_reminder": "5"})


def test_log_retention_defaults_within_policy():
    assert config_from_mapping(VALID).log_retention_days == 14


def test_log_retention_over_30_days_is_rejected(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="log_retention_days"):
        config_from_mapping({**VALID, "log_retention_days": "31"})


def test_secrets_can_come_from_a_file(monkeypatch, tmp_path):
    secret = tmp_path / "discord_token"
    secret.write_text("token-from-file\n", encoding="utf-8")
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_TOKEN_FILE", str(secret))
    assert config_from_mapping(VALID).token == "token-from-file"


def test_missing_secret_file_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN_FILE", str(tmp_path / "absent"))
    with pytest.raises(ConfigError, match="DISCORD_TOKEN_FILE"):
        config_from_mapping(VALID)


def test_encryption_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOG_ENCRYPTION_KEY", "some-key")
    assert config_from_mapping(VALID).log_encryption_key == "some-key"


def test_load_config_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_load_config_reports_bad_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_shipped_example_config_is_valid_json():
    data = json.loads(open("config.json.example", encoding="utf-8").read())
    assert "homeserver_id" in data


def test_shipped_messages_load():
    messages = load_messages()
    assert "verification" in messages
    assert "emergency" in messages
