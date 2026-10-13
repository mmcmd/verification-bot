"""Startup, the reduced-mode fallback and the exit codes the service relies on."""

import json

import discord
import pytest

from verification_bot import __main__ as entry
from verification_bot.config import BotConfig, load_messages
from verification_bot.settings import SettingsStore


class FakeResponse:
    status = 401
    reason = "Unauthorized"


@pytest.fixture
def starts(monkeypatch):
    """Replace the real connection with a script of outcomes, and record each start."""
    recorded = []
    outcomes = []

    async def fake_start(bot, token):
        recorded.append(bot)
        outcome = outcomes.pop(0) if outcomes else None
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(entry, "_start", fake_start)
    monkeypatch.setattr(entry, "setup_logging", lambda **kwargs: None)
    return recorded, outcomes


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"token": "placeholder", "homeserver_id": "1", "verified_role": "2"}),
        encoding="utf-8",
    )
    return ["--config", str(config), "--settings", str(tmp_path / "data" / "settings.json")]


async def run(tmp_path):
    config = BotConfig(token="placeholder", home_server_id=1)
    return await entry.run_bot(config, load_messages(), SettingsStore(tmp_path / "s.json"))


async def test_normal_start_connects_once_in_full_mode(starts, tmp_path):
    recorded, _ = starts
    assert await run(tmp_path) == entry.EXIT_OK
    assert len(recorded) == 1
    assert recorded[0].reduced_mode is False


async def test_refused_intent_starts_once_more_in_reduced_mode(starts, tmp_path):
    recorded, outcomes = starts
    outcomes.append(discord.PrivilegedIntentsRequired(None))
    assert await run(tmp_path) == entry.EXIT_OK
    assert [bot.reduced_mode for bot in recorded] == [False, True]
    assert recorded[1].intents.members is False
    # The commands were registered on the first attempt; do not register twice.
    assert recorded[1]._sync_commands_on_start is False


async def test_reduced_mode_is_tried_only_once(starts, tmp_path):
    recorded, outcomes = starts
    outcomes.extend([discord.PrivilegedIntentsRequired(None)] * 5)
    assert await run(tmp_path) == entry.EXIT_INTENTS_REFUSED
    assert len(recorded) == 2


def test_rejected_token_exits_without_a_second_attempt(starts, files):
    recorded, outcomes = starts
    outcomes.append(discord.LoginFailure("Improper token has been passed."))
    assert entry.main(files) == entry.EXIT_BAD_TOKEN
    assert len(recorded) == 1


def test_token_revoked_while_connecting_is_a_token_exit(starts, files):
    recorded, outcomes = starts

    class Socket:
        close_code = 4004

    outcomes.append(discord.ConnectionClosed(Socket(), shard_id=None))
    assert entry.main(files) == entry.EXIT_BAD_TOKEN
    assert len(recorded) == 1


def test_unexpected_error_is_a_crash_exit(starts, files):
    recorded, outcomes = starts
    outcomes.append(RuntimeError("boom"))
    assert entry.main(files) == entry.EXIT_CRASH
    assert len(recorded) == 1


def test_missing_config_never_connects(starts, tmp_path):
    recorded, _ = starts
    assert entry.main(["--config", str(tmp_path / "absent.json")]) == entry.EXIT_BAD_CONFIG
    assert recorded == []


def test_broken_settings_file_never_connects(starts, files, tmp_path):
    recorded, _ = starts
    settings = tmp_path / "data" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{ not json", encoding="utf-8")
    assert entry.main(files) == entry.EXIT_BAD_CONFIG
    assert recorded == []


def test_first_start_imports_the_legacy_config(starts, files, tmp_path):
    recorded, _ = starts
    assert entry.main(files) == entry.EXIT_OK
    assert recorded[0].settings.get("verified_role") == 2
    saved = (tmp_path / "data" / "settings.json").read_text(encoding="utf-8")
    assert "placeholder" not in saved


def test_exit_codes_are_distinct_and_listed_in_the_service_file():
    codes = {entry.EXIT_BAD_CONFIG, entry.EXIT_BAD_TOKEN, entry.EXIT_INTENTS_REFUSED}
    assert len(codes) == 3 and entry.EXIT_OK not in codes and entry.EXIT_CRASH not in codes

    with open("deploy/verificationbot.service", encoding="utf-8") as stream:
        unit = stream.read()
    line = next(row for row in unit.splitlines() if row.startswith("RestartPreventExitStatus="))
    assert {int(code) for code in line.split("=", 1)[1].split()} == codes
    assert "Restart=on-failure" in unit
    assert "Restart=always" not in unit


def test_config_in_the_wrong_text_encoding_never_connects_or_restarts(starts, tmp_path):
    """Saved as UTF-16 by a Windows editor: a restart cannot fix it, so exit code 2."""
    recorded, _ = starts
    config = tmp_path / "config.json"
    config.write_bytes('{"token": "placeholder", "homeserver_id": "1"}'.encode("utf-16"))
    code = entry.main(
        ["--config", str(config), "--settings", str(tmp_path / "data" / "settings.json")]
    )
    assert code == entry.EXIT_BAD_CONFIG
    assert recorded == []


def test_a_cog_that_fails_to_load_does_not_restart(starts, files):
    from discord.ext import commands

    recorded, outcomes = starts
    outcomes.append(commands.ExtensionFailed("verification_bot.cogs.x", RuntimeError("boom")))
    assert entry.main(files) == entry.EXIT_BAD_CONFIG
    assert len(recorded) == 1
