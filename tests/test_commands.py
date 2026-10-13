from verification_bot import checks
from verification_bot.client import GLOBAL_COMMANDS

EXPECTED_COMMANDS = {
    "boosters",
    "clearemergency",
    "config",
    "emergency",
    "github",
    "help",
    "ping",
    "privacy",
    "steve",
    "uptime",
    "verify",
}


def all_commands(bot):
    """Every registered command, whether global or scoped to the home server."""
    return {command.name: command for command in bot.all_app_commands()}


async def test_every_command_is_registered(loaded_bot):
    assert EXPECTED_COMMANDS <= set(all_commands(loaded_bot))


async def test_no_prefix_commands_remain(loaded_bot):
    """Everything is a slash command now; prefix commands would need message content."""
    assert list(loaded_bot.commands) == []


async def test_commands_have_descriptions(loaded_bot):
    for command in all_commands(loaded_bot).values():
        assert command.description and command.description != "…"


async def test_emergency_requires_a_reason(loaded_bot):
    emergency = loaded_bot.tree.get_command("emergency")
    reason = next(param for param in emergency.parameters if param.name == "reason")
    assert reason.required


async def test_only_dm_capable_commands_stay_global(loaded_bot):
    loaded_bot._assign_command_scopes()
    global_names = {command.name for command in loaded_bot.tree.get_commands()}
    assert global_names <= GLOBAL_COMMANDS
    assert "verify" in global_names
    assert {"emergency", "clearemergency", "boosters", "ping"} <= set(all_commands(loaded_bot))


async def test_audience_follows_the_permission_checks(loaded_bot):
    commands = all_commands(loaded_bot)
    assert checks.audience_of(commands["verify"]) is checks.Audience.EVERYONE
    assert checks.audience_of(commands["emergency"]) is checks.Audience.VERIFIED
    assert checks.audience_of(commands["clearemergency"]) is checks.Audience.MODERATOR
