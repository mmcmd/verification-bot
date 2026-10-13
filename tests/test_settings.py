import json

import pytest

from verification_bot.config import ConfigError
from verification_bot.settings import (
    DEFAULT_STATUS_TEXT,
    SETTINGS,
    SettingsError,
    SettingsStore,
    format_value,
    import_legacy,
    load_or_import,
)

#: The shape of the production config.json: every value a string, a single
#: string for the bypass role, no rules/roles channel, the old status, and keys
#: the new bot no longer uses. The token is a placeholder.
PRODUCTION_SHAPE = {
    "token": "placeholder",
    "homeserver_id": "362843193617678337",
    "verification_requirement_join": "1440",
    "verification_requirement_message": "14",
    "moderator_mail_id": "562349906648629259",
    "log_channel_id": "372072613461098517",
    "status": "message me to get verified!",
    "colored_roles": ["452201509816369162", "623681022717984779"],
    "nitro_role": "1536385732061433986",
    "prefix": "+",
    "unboost_announcement_channel_id": "573214438086410240",
    "moderator_role_IDs": ["364496737563312160", "380867296316489738"],
    "birthday_role_ID": "411581664888750098",
    "verified_role": "568189133617364998",
    "emergency_request_approval_threshold": "3",
    "emergency_request_deny_threshold": "2",
    "ontopic_category_id": "372118957181763585",
    "emergency_role_id": "385498779471839233",
    "emergency_role_reminder": "180",
    "emergency_role_timeout": "5",
    "emergency_top_role_bypass_id": "362980050527715329",
    "irc_relay_id": "24e0c0ee42c8",
    "log_directory": "logs",
    "log_retention_days": "14",
}


# -- legacy import ----------------------------------------------------------


def test_production_config_imports_without_notes():
    values, notes = import_legacy(PRODUCTION_SHAPE)
    assert notes == []
    assert values["verified_role"] == 568189133617364998
    assert values["moderator_roles"] == (364496737563312160, 380867296316489738)
    assert values["colour_roles"] == (452201509816369162, 623681022717984779)
    assert values["booster_role"] == 1536385732061433986
    assert values["mod_log_channel"] == 372072613461098517
    assert values["unboost_channel"] == 573214438086410240
    assert values["ontopic_category"] == 372118957181763585
    assert values["emergency_role"] == 385498779471839233
    assert values["moderator_mail_user"] == 562349906648629259
    assert values["join_age_days"] == 1440
    assert values["verify_age_days"] == 14
    assert values["approval_threshold"] == 3
    assert values["denial_threshold"] == 2
    assert values["reminder_interval_seconds"] == 180
    assert values["reminder_count"] == 5


def test_single_string_bypass_role_becomes_one_role():
    """The old bot split this string into digits, so the bypass never worked."""
    values, _ = import_legacy(PRODUCTION_SHAPE)
    assert values["emergency_bypass_roles"] == (362980050527715329,)


def test_bypass_roles_may_also_be_a_list():
    values, _ = import_legacy({**PRODUCTION_SHAPE, "emergency_top_role_bypass_id": ["1", "2"]})
    assert values["emergency_bypass_roles"] == (1, 2)


def test_production_server_gets_the_channels_the_old_bot_hard_coded():
    values, _ = import_legacy(PRODUCTION_SHAPE)
    assert values["rules_channel"] == 448941767325253632
    assert values["roles_channel"] == 516816975427797012
    assert values["booster_channel"] == 585867795942604800


def test_other_servers_do_not_get_production_channels():
    values, _ = import_legacy({**PRODUCTION_SHAPE, "homeserver_id": "314794048646938646"})
    assert "rules_channel" not in values
    assert "roles_channel" not in values
    assert "booster_channel" not in values


def test_explicit_channels_win_over_production_defaults():
    values, _ = import_legacy({**PRODUCTION_SHAPE, "rules_channel_id": "42"})
    assert values["rules_channel"] == 42


def test_outdated_status_is_replaced():
    values, _ = import_legacy(PRODUCTION_SHAPE)
    assert values["status_text"] == DEFAULT_STATUS_TEXT


def test_custom_status_is_kept():
    values, _ = import_legacy({**PRODUCTION_SHAPE, "status": "hello"})
    assert values["status_text"] == "hello"


def test_unused_legacy_keys_are_ignored():
    values, _ = import_legacy(PRODUCTION_SHAPE)
    assert set(values) <= set(SETTINGS)
    assert "sudo_voter_roles" not in values


def test_bad_legacy_value_is_skipped_with_a_note():
    values, notes = import_legacy({**PRODUCTION_SHAPE, "verified_role": "not-a-number"})
    assert "verified_role" not in values
    assert len(notes) == 1 and "verified_role" in notes[0]


def test_first_start_imports_and_writes_the_file(tmp_path):
    path = tmp_path / "data" / "settings.json"
    store, imported = load_or_import(path, PRODUCTION_SHAPE)
    assert imported is True
    assert store.get("verified_role") == 568189133617364998

    on_disk = path.read_text(encoding="utf-8")
    assert "placeholder" not in on_disk  # the token never reaches the settings file
    assert set(json.loads(on_disk)["settings"]) <= set(SETTINGS)


def test_existing_settings_file_is_not_overwritten_by_config(tmp_path):
    path = tmp_path / "settings.json"
    SettingsStore(path, {"verified_role": 99}).save()
    store, imported = load_or_import(path, PRODUCTION_SHAPE)
    assert imported is False
    assert store.get("verified_role") == 99
    assert store.get("emergency_role") is None


def test_fresh_install_starts_with_nothing_to_import(tmp_path):
    path = tmp_path / "settings.json"
    store, imported = load_or_import(path, {"token": "t", "homeserver_id": "1"})
    assert imported is False
    assert path.exists()
    assert store.get("verified_role") is None
    assert store.get("moderator_roles") == ()
    assert store.get("status_text") == DEFAULT_STATUS_TEXT
    assert store.get("approval_threshold") == 3


def test_unwritable_settings_folder_is_a_config_error(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    with pytest.raises(ConfigError, match="settings file"):
        load_or_import(blocker / "settings.json", PRODUCTION_SHAPE)


# -- the store --------------------------------------------------------------


def test_changes_are_saved_and_survive_a_reload(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.set("verified_role", 5)
    store.set("moderator_roles", [7, 8, 7])
    store.set("status_text", "  hi  ")

    reloaded = SettingsStore.load(path)
    assert reloaded.get("verified_role") == 5
    assert reloaded.get("moderator_roles") == (7, 8)
    assert reloaded.get("status_text") == "hi"


def test_save_leaves_no_temporary_files(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.set("verified_role", 5)
    assert [entry.name for entry in tmp_path.iterdir()] == ["settings.json"]


def test_failed_save_changes_nothing(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json", {"verified_role": 5})

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(OSError):
        store.set("verified_role", 6)
    assert store.get("verified_role") == 5


def test_clearing_a_setting_restores_the_default(tmp_path):
    store = SettingsStore(tmp_path / "settings.json", {"approval_threshold": 9})
    assert store.is_set("approval_threshold")
    assert store.reset("approval_threshold") == 3
    assert not store.is_set("approval_threshold")
    store.set("moderator_roles", [1])
    store.set("moderator_roles", [])
    assert not store.is_set("moderator_roles")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("approval_threshold", 0),
        ("reminder_interval_seconds", 5),
        ("reminder_count", 0),
        ("join_age_days", -1),
        ("verified_role", "abc"),
        ("verified_role", -4),
        ("moderator_roles", ["x"]),
        ("status_text", "   "),
        ("status_text", "x" * 200),
    ],
)
def test_values_that_do_not_fit_are_rejected(tmp_path, key, value):
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(SettingsError):
        store.set(key, value)


def test_unknown_setting_is_a_key_error(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(KeyError):
        store.get("no_such_setting")
    with pytest.raises(KeyError):
        store.set("no_such_setting", 1)


def test_broken_settings_file_is_a_config_error(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        SettingsStore.load(path)


def test_unknown_keys_in_the_file_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"version": 1, "settings": {"verified_role": 5, "mystery": 1}}),
        encoding="utf-8",
    )
    assert SettingsStore.load(path).get("verified_role") == 5


def test_every_setting_named_in_the_brief_exists():
    assert set(SETTINGS) == {
        "verified_role", "moderator_roles", "sudo_voter_roles", "emergency_bypass_roles",
        "emergency_role", "booster_role", "colour_roles", "mod_log_channel",
        "unboost_channel", "rules_channel", "roles_channel", "booster_channel",
        "ontopic_category", "moderator_mail_user", "join_age_days", "verify_age_days",
        "approval_threshold", "denial_threshold", "reminder_interval_seconds",
        "reminder_count", "status_text",
    }


def test_values_are_shown_as_mentions():
    assert format_value(SETTINGS["verified_role"], 5) == "<@&5>"
    assert format_value(SETTINGS["moderator_roles"], (5, 6)) == "<@&5>, <@&6>"
    assert format_value(SETTINGS["mod_log_channel"], 5) == "<#5>"
    assert format_value(SETTINGS["moderator_mail_user"], 5) == "<@5>"
    assert format_value(SETTINGS["approval_threshold"], 3) == "3"
    assert format_value(SETTINGS["verified_role"], None) == "*not set*"
    assert format_value(SETTINGS["moderator_roles"], ()) == "*not set*"
