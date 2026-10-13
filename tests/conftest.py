"""Shared fixtures: a bot that never connects, backed by a temporary settings file."""

import pytest

from verification_bot.client import EXTENSIONS, VerificationBot
from verification_bot.config import BotConfig, load_messages
from verification_bot.settings import SettingsStore

HOME_SERVER_ID = 1

#: A complete set of settings with small, recognisable IDs.
SETTINGS_VALUES = {
    "verified_role": 2,
    "moderator_mail_user": 3,
    "moderator_roles": (4, 5),
    "mod_log_channel": 6,
    "unboost_channel": 7,
    "rules_channel": 8,
    "roles_channel": 9,
    "colour_roles": (10, 11),
    "booster_channel": 12,
    "ontopic_category": 13,
    "emergency_role": 14,
    "emergency_bypass_roles": (15,),
    "booster_role": 16,
    "sudo_voter_roles": (17,),
}


@pytest.fixture
def config(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    return BotConfig(token="token-value", home_server_id=HOME_SERVER_ID, irc_relay_id=None)


@pytest.fixture
def settings(tmp_path):
    """A fully filled-in settings store saved under ``tmp_path``."""
    return SettingsStore(tmp_path / "settings.json", SETTINGS_VALUES)


@pytest.fixture
def empty_settings(tmp_path):
    """A settings store as a fresh install has it: nothing chosen yet."""
    return SettingsStore(tmp_path / "empty-settings.json")


@pytest.fixture
def bot(config, settings):
    """A bot in full mode with no cogs loaded. It is never connected."""
    return VerificationBot(config, load_messages(), settings)


@pytest.fixture
def reduced_bot(config, settings):
    """The same bot as it runs when Discord refuses the Server Members intent."""
    return VerificationBot(config, load_messages(), settings, reduced_mode=True)


@pytest.fixture
async def loaded_bot(bot):
    """A bot with every cog loaded, as after startup but without a connection."""
    for extension in EXTENSIONS:
        await bot.load_extension(extension)
    try:
        yield bot
    finally:
        for extension in reversed(EXTENSIONS):
            if extension in bot.extensions:
                await bot.unload_extension(extension)
        await bot.close()
