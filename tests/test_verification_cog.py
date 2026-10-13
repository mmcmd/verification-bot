import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from verification_bot.client import VerificationBot
from verification_bot.cogs.verification import DM_HINT_COOLDOWN, Verification
from verification_bot.config import load_messages

from .conftest import HOME_SERVER_ID


def make_role(role_id):
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.mention = f"<@&{role_id}>"
    return role


def make_member(member_id=50, *, age_days=100, roles=()):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.bot = False
    member.mention = f"<@{member_id}>"
    member.created_at = discord.utils.utcnow() - datetime.timedelta(days=age_days, hours=1)
    member.roles = list(roles)
    member.display_avatar.url = "https://example.invalid/a.png"
    member.guild.id = HOME_SERVER_ID
    member.add_roles = AsyncMock()
    return member


def make_interaction(user_id=50):
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response.defer = AsyncMock()
    interaction.response.is_done.return_value = True
    interaction.followup.send = AsyncMock()
    return interaction


def reply_of(interaction):
    return interaction.followup.send.await_args.kwargs["content"]


@pytest.fixture
def world(bot, monkeypatch):
    """A home server with a verified role (2) and a mod-log channel (6)."""
    verified = make_role(2)
    guild = MagicMock(spec=discord.Guild)
    guild.id = HOME_SERVER_ID
    guild.default_role = make_role(HOME_SERVER_ID)
    guild.get_role.side_effect = lambda role_id: verified if role_id == 2 else None
    mod_log = MagicMock(spec=discord.TextChannel)
    mod_log.send = AsyncMock()
    monkeypatch.setattr(bot, "get_guild", lambda guild_id: guild)
    monkeypatch.setattr(bot, "get_channel", lambda cid: mod_log if cid == 6 else None)

    def add_member(member):
        member.top_role = guild.default_role
        guild.get_member.return_value = member
        return member

    return MagicMock(guild=guild, verified=verified, mod_log=mod_log, add_member=add_member)


def logged_titles(world):
    return [call.kwargs["embed"].title for call in world.mod_log.send.await_args_list]


# -- /verify ----------------------------------------------------------------


async def test_verify_grants_the_role_and_logs_it(bot, world):
    member = world.add_member(make_member(age_days=30))
    interaction = make_interaction()
    cog = Verification(bot)

    await cog.verify.callback(cog, interaction)

    member.add_roles.assert_awaited_once()
    assert member.add_roles.await_args.args[0] is world.verified
    assert "You have been verified" in reply_of(interaction)
    assert logged_titles(world) == ["Member verified"]


async def test_verify_refuses_accounts_that_are_too_new(bot, world):
    member = world.add_member(make_member(age_days=2))
    interaction = make_interaction()
    cog = Verification(bot)

    await cog.verify.callback(cog, interaction)

    member.add_roles.assert_not_awaited()
    assert "**5 days**" in reply_of(interaction)
    assert logged_titles(world) == ["Verification refused"]


async def test_verify_uses_the_threshold_from_the_settings(bot, world):
    bot.settings.set("verify_age_days", 60)
    member = world.add_member(make_member(age_days=30))
    cog = Verification(bot)
    await cog.verify.callback(cog, make_interaction())
    member.add_roles.assert_not_awaited()


async def test_verify_for_someone_already_verified(bot, world):
    member = world.add_member(make_member(roles=[world.verified]))
    interaction = make_interaction()
    cog = Verification(bot)
    await cog.verify.callback(cog, interaction)
    member.add_roles.assert_not_awaited()
    assert "already have access" in reply_of(interaction)


async def test_verify_for_someone_not_in_the_server(bot, world):
    world.guild.get_member.return_value = None
    world.guild.fetch_member = AsyncMock(
        side_effect=discord.NotFound(MagicMock(status=404), "unknown member")
    )
    interaction = make_interaction()
    cog = Verification(bot)
    await cog.verify.callback(cog, interaction)
    assert "need to join" in reply_of(interaction)


async def test_verify_works_without_the_member_list(reduced_bot, monkeypatch):
    """Reduced mode: the member is not cached, so it is looked up by ID."""
    verified = make_role(2)
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = make_role(HOME_SERVER_ID)
    guild.get_role.side_effect = lambda role_id: verified if role_id == 2 else None
    member = make_member(age_days=30)
    member.top_role = guild.default_role
    guild.get_member.return_value = None
    guild.fetch_member = AsyncMock(return_value=member)
    monkeypatch.setattr(reduced_bot, "get_guild", lambda guild_id: guild)
    monkeypatch.setattr(reduced_bot, "get_channel", lambda cid: None)

    cog = Verification(reduced_bot)
    await cog.verify.callback(cog, make_interaction())

    guild.fetch_member.assert_awaited_once_with(50)
    member.add_roles.assert_awaited_once()


async def test_verify_on_a_fresh_install_points_at_config(config, empty_settings, monkeypatch):
    bot = VerificationBot(config, load_messages(), empty_settings)
    monkeypatch.setattr(bot, "get_guild", lambda guild_id: MagicMock(spec=discord.Guild))
    interaction = make_interaction()
    cog = Verification(bot)
    await cog.verify.callback(cog, interaction)
    assert "/config" in reply_of(interaction)


async def test_failed_role_assignment_is_reported_with_the_real_mention(bot, world):
    member = world.add_member(make_member(age_days=30))
    member.add_roles.side_effect = discord.Forbidden(MagicMock(status=403), "missing permissions")
    interaction = make_interaction()
    cog = Verification(bot)

    await cog.verify.callback(cog, interaction)

    assert "permissions problem" in reply_of(interaction)
    embed = world.mod_log.send.await_args.kwargs["embed"]
    assert embed.title == "Could not assign the verified role"
    assert "<@50>" in embed.description and "Manage Roles" in embed.description


async def test_deleted_verified_role_is_reported(bot, world):
    world.guild.get_role.side_effect = lambda role_id: None
    world.add_member(make_member(age_days=30))
    interaction = make_interaction()
    cog = Verification(bot)
    await cog.verify.callback(cog, interaction)
    assert "temporarily unavailable" in reply_of(interaction)
    assert logged_titles(world) == ["Verification is broken"]


# -- join -------------------------------------------------------------------


async def test_old_accounts_are_verified_on_join(bot, world):
    member = make_member(age_days=200)
    cog = Verification(bot)
    await cog.on_member_join(member)
    member.add_roles.assert_awaited_once()
    assert logged_titles(world) == ["Member auto-verified"]


async def test_new_accounts_are_left_alone_on_join(bot, world):
    member = make_member(age_days=90)  # the threshold itself does not count
    cog = Verification(bot)
    await cog.on_member_join(member)
    member.add_roles.assert_not_awaited()
    world.mod_log.send.assert_not_awaited()


async def test_bots_and_other_servers_are_ignored_on_join(bot, world):
    cog = Verification(bot)
    robot = make_member(age_days=200)
    robot.bot = True
    elsewhere = make_member(age_days=200)
    elsewhere.guild.id = 999
    await cog.on_member_join(robot)
    await cog.on_member_join(elsewhere)
    robot.add_roles.assert_not_awaited()
    elsewhere.add_roles.assert_not_awaited()


async def test_failed_auto_verify_is_reported(bot, world):
    member = make_member(age_days=200)
    member.add_roles.side_effect = discord.HTTPException(MagicMock(status=500), "oops")
    cog = Verification(bot)
    await cog.on_member_join(member)
    assert logged_titles(world) == ["Could not assign the verified role"]


async def test_deleted_role_on_join_is_reported_once_not_per_join(bot, world):
    world.guild.get_role.side_effect = lambda role_id: None
    cog = Verification(bot)
    for member_id in range(60, 65):
        await cog.on_member_join(make_member(member_id, age_days=200))
    assert logged_titles(world) == ["Automatic verification is broken"]


# -- direct messages --------------------------------------------------------


def make_dm(author_id=50):
    message = MagicMock()
    message.guild = None
    message.author.id = author_id
    message.author.bot = False
    message.channel.send = AsyncMock()
    return message


async def test_dm_gets_a_hint_at_most_once_per_cooldown(bot):
    cog = Verification(bot)
    first, second = make_dm(), make_dm()
    await cog.on_message(first)
    await cog.on_message(second)
    first.channel.send.assert_awaited_once()
    assert "/verify" in first.channel.send.await_args.args[0]
    second.channel.send.assert_not_awaited()


async def test_dm_text_is_never_read(bot):
    cog = Verification(bot)
    message = make_dm()
    content = MagicMock(side_effect=AssertionError("the DM text was read"))
    type(message).content = property(lambda self: content())
    await cog.on_message(message)
    message.channel.send.assert_awaited_once()


async def test_server_messages_and_bots_get_no_hint(bot):
    cog = Verification(bot)
    in_server = make_dm()
    in_server.guild = MagicMock()
    from_bot = make_dm()
    from_bot.author.bot = True
    await cog.on_message(in_server)
    await cog.on_message(from_bot)
    in_server.channel.send.assert_not_awaited()
    from_bot.channel.send.assert_not_awaited()


async def test_expired_dm_cooldowns_are_forgotten(bot):
    cog = Verification(bot)
    long_ago = discord.utils.utcnow() - DM_HINT_COOLDOWN * 3
    cog._dm_hint_sent = {user_id: long_ago for user_id in range(1000, 1500)}
    cog._dm_hints_pruned_at = long_ago

    await cog.on_message(make_dm(author_id=50))

    assert list(cog._dm_hint_sent) == [50]
