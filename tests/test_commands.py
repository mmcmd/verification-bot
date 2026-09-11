import pytest

from verification_bot.client import EXTENSIONS, VerificationBot
from verification_bot.config import config_from_mapping, load_messages

from .test_config import VALID

EXPECTED_COMMANDS = {
    "boosters",
    "clearemergency",
    "emergency",
    "github",
    "irc",
    "ping",
    "steve",
    "uptime",
    "verify",
}


@pytest.fixture
async def loaded_bot(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    bot = VerificationBot(config_from_mapping(VALID), load_messages())
    for extension in EXTENSIONS:
        await bot.load_extension(extension)
    try:
        yield bot
    finally:
        for extension in reversed(EXTENSIONS):
            if extension in bot.extensions:
                await bot.unload_extension(extension)
        await bot.close()


async def test_every_command_is_registered(loaded_bot):
    names = {command.name for command in loaded_bot.tree.get_commands()}
    assert EXPECTED_COMMANDS <= names


async def test_no_prefix_commands_remain(loaded_bot):
    """Everything is a slash command now; prefix commands would need message content."""
    assert list(loaded_bot.commands) == []


async def test_commands_have_descriptions(loaded_bot):
    for command in loaded_bot.tree.get_commands():
        assert command.description and command.description != "…"


async def test_emergency_requires_a_reason(loaded_bot):
    emergency = loaded_bot.tree.get_command("emergency")
    reason = next(param for param in emergency.parameters if param.name == "reason")
    assert reason.required
