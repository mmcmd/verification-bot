from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from verification_bot.client import GLOBAL_COMMANDS, VerificationBot, build_intents
from verification_bot.config import load_messages
from verification_bot.settings import SettingsError


def fake_user(user_id=50):
    return SimpleNamespace(
        id=user_id,
        mention=f"<@{user_id}>",
        display_avatar=SimpleNamespace(url="https://example.invalid/avatar.png"),
        __str__=lambda self: "user",
    )


def test_only_members_intent_is_privileged():
    """Guards the Discord intent application: no Presence or Message Content."""
    intents = build_intents()
    assert intents.members is True
    assert intents.presences is False
    assert intents.message_content is False
    assert intents.guilds is True
    assert intents.dm_messages is True
    allowed = discord.Intents.none()
    allowed.guilds = allowed.members = allowed.dm_messages = True
    assert intents.value == allowed.value


def test_reduced_mode_asks_for_no_privileged_intent(reduced_bot):
    assert reduced_bot.reduced_mode is True
    assert reduced_bot.intents.members is False
    assert reduced_bot.intents.presences is False
    assert reduced_bot.intents.message_content is False
    assert reduced_bot._connection._chunk_guilds is False


def test_full_mode_loads_the_whole_member_list(bot):
    """Boost tracking and /boosters read the member list, so it must be complete."""
    assert bot.reduced_mode is False
    assert bot.intents.members is True
    assert bot._connection._chunk_guilds is True


def test_roles_are_never_pinged_by_default(bot):
    assert bot.allowed_mentions.roles is False
    assert bot.allowed_mentions.everyone is False


def test_status_text_comes_from_the_settings(bot):
    assert bot.activity.name == "/verify to get access"


def test_dm_capable_commands_are_global():
    assert GLOBAL_COMMANDS == {"verify", "help", "privacy"}


def test_messages_are_rendered_with_defaults(bot):
    rendered = bot.message("verification.already_verified")
    assert "<@3>" in rendered
    success = bot.message("verification.success")
    assert "<#8>" in success and "<#9>" in success
    assert "<#12>" in bot.message("boost.thank_you")


def test_messages_accept_extra_params(bot):
    rendered = bot.message("verification.too_young", required_days=5, account_age_days=1)
    assert "**5 days**" in rendered
    assert "**1 days**" in rendered


def test_unknown_message_path_raises(bot):
    with pytest.raises(KeyError):
        bot.message("verification.does_not_exist")


def test_messages_render_on_a_fresh_install(config, empty_settings):
    """Nothing chosen yet: no broken mentions like <#None> may appear."""
    bot = VerificationBot(config, load_messages(), empty_settings)
    for path in ("verification.success", "verification.dm_hint", "boost.thank_you",
                 "verification.not_configured"):
        rendered = bot.message(path)
        assert "None" not in rendered
        assert "{" not in rendered


def test_contact_falls_back_to_the_owner(config, empty_settings):
    bot = VerificationBot(config, load_messages(), empty_settings)
    assert bot.contact == "a moderator"
    bot.owner_user_id = 77
    assert bot.contact.startswith("<@77>")
    empty_settings.set("moderator_mail_user", 3)
    assert bot.contact.startswith("<@3>")


def test_every_template_renders(bot):
    assert bot.message(
        "emergency.prompt",
        caller="<@1>",
        reason="db down",
        approvals=0,
        approval_threshold=3,
        denials=0,
        deny_threshold=2,
    )
    assert bot.message(
        "emergency.approved", caller="<@1>", reason="db down", link="l", role="<@&2>"
    )
    assert bot.message("emergency.denied", caller="<@1>")
    assert bot.message("emergency.timed_out", caller="<@1>", link="l")
    assert bot.message("emergency.already_active", link="l")
    assert bot.message("emergency.reminder", link="l")
    assert bot.message("emergency.bypass", caller="<@1>", reason="db down", role="<@&2>")
    assert bot.message("boost.thank_you")
    assert bot.message("boost.unavailable")
    assert bot.message("verification.dm_hint")
    assert bot.message("verification.success")


# -- mod-log ----------------------------------------------------------------


@pytest.fixture
def mod_log(bot, monkeypatch):
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    monkeypatch.setattr(bot, "get_channel", lambda channel_id: channel if channel_id == 6 else None)
    return channel


async def test_audit_reports_whether_it_posted(bot, mod_log):
    assert await bot.audit(discord.Embed(title="x")) is True
    mod_log.send.assert_awaited_once()


async def test_audit_without_a_channel_does_not_raise(config, empty_settings):
    bot = VerificationBot(config, load_messages(), empty_settings)
    assert await bot.audit(discord.Embed(title="x")) is False


async def test_failure_report_carries_the_real_mention(bot, mod_log):
    posted = await bot.report_failure("Broken", "<@50> needs help", member=fake_user())
    assert posted is True
    embed = mod_log.send.await_args.kwargs["embed"]
    assert embed.title == "Broken"
    assert "<@50>" in embed.description
    assert "50" in embed.author.name


async def test_repeating_failures_are_reported_once(bot, mod_log):
    assert await bot.report_failure("Broken", "role deleted", dedupe_key="k") is True
    assert await bot.report_failure("Broken", "role deleted", dedupe_key="k") is False
    assert mod_log.send.await_count == 1


async def test_change_setting_applies_and_is_logged(bot, mod_log):
    stored = await bot.change_setting("approval_threshold", 4, actor=fake_user())
    assert stored == 4
    assert bot.settings.get("approval_threshold") == 4
    embed = mod_log.send.await_args.kwargs["embed"]
    assert "<@50>" in embed.description
    assert "**Before:** 3" in embed.description
    assert "**After:** 4" in embed.description


async def test_change_setting_rejects_bad_values_without_logging(bot, mod_log):
    with pytest.raises(SettingsError):
        await bot.change_setting("approval_threshold", 0, actor=fake_user())
    assert bot.settings.get("approval_threshold") == 3
    mod_log.send.assert_not_awaited()


async def test_status_change_updates_presence(bot, mod_log, monkeypatch):
    change_presence = AsyncMock()
    monkeypatch.setattr(bot, "change_presence", change_presence)
    await bot.change_setting("status_text", "new status", actor=fake_user())
    assert change_presence.await_args.kwargs["activity"].name == "new status"


# -- startup announcements --------------------------------------------------


async def test_reduced_mode_posts_one_warning(reduced_bot, monkeypatch):
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    monkeypatch.setattr(reduced_bot, "get_channel", lambda channel_id: channel)
    monkeypatch.setattr(reduced_bot, "get_guild", lambda guild_id: None)

    await reduced_bot.on_ready()
    await reduced_bot.on_ready()  # a reconnect must not repeat the warning

    assert channel.send.await_count == 1
    text = channel.send.await_args.kwargs["embed"].description
    for feature in ("automatic verification", "thank-you", "stops boosting", "/boosters"):
        assert feature in text


async def test_full_mode_posts_no_warning(bot, mod_log, monkeypatch):
    monkeypatch.setattr(bot, "get_guild", lambda guild_id: None)
    await bot.on_ready()
    mod_log.send.assert_not_awaited()


# -- unexpected command errors ----------------------------------------------


def failing_interaction(bot):
    interaction = MagicMock()
    interaction.client = bot
    interaction.command.qualified_name = "ping"
    interaction.user = fake_user()
    interaction.channel.mention = "<#99>"
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    return interaction


async def test_unhandled_error_notifies_the_moderators(bot, mod_log):
    interaction = failing_interaction(bot)
    error = discord.app_commands.CommandInvokeError(MagicMock(), RuntimeError("boom"))
    await bot.tree.on_error(interaction, error)

    embed = mod_log.send.await_args.kwargs["embed"]
    assert "/ping" in embed.title and "RuntimeError" in embed.description
    reply = interaction.response.send_message.await_args.kwargs["content"]
    assert "moderators have been notified" in reply


async def test_error_text_is_honest_when_nobody_was_notified(config, empty_settings):
    bot = VerificationBot(config, load_messages(), empty_settings)
    interaction = failing_interaction(bot)
    error = discord.app_commands.CommandInvokeError(MagicMock(), RuntimeError("boom"))
    await bot.tree.on_error(interaction, error)

    reply = interaction.response.send_message.await_args.kwargs["content"]
    assert "have been notified" not in reply


# -- message text is never read ----------------------------------------------


async def test_bot_never_looks_inside_a_message(bot, monkeypatch):
    """No prefix-command parsing: that would read the text of every DM."""
    process_commands = AsyncMock()
    monkeypatch.setattr(bot, "process_commands", process_commands)
    message = MagicMock()
    type(message).content = property(
        lambda self: (_ for _ in ()).throw(AssertionError("the message text was read"))
    )
    await bot.on_message(message)
    process_commands.assert_not_awaited()


async def test_failed_command_registration_is_not_fatal(bot, monkeypatch):
    """A wrong server ID or a missing invite scope must not crash the bot into a restart."""
    error = discord.HTTPException(MagicMock(status=404), "unknown guild")
    monkeypatch.setattr(bot.tree, "sync", AsyncMock(side_effect=error))
    await bot._sync_commands()  # logs the problem and carries on


async def test_status_change_is_kept_for_the_next_reconnect(bot, mod_log, monkeypatch):
    monkeypatch.setattr(bot, "change_presence", AsyncMock())
    await bot.change_setting("status_text", "new status", actor=fake_user())
    assert bot.activity.name == "new status"
