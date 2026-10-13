import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from verification_bot.cogs.community import Community

from .conftest import HOME_SERVER_ID


def make_role(role_id):
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.mention = f"<@&{role_id}>"
    return role


BOOSTER, COLOUR, OTHER = make_role(16), make_role(10), make_role(99)


def make_member(*, boosting, roles=()):
    member = MagicMock(spec=discord.Member)
    member.id = 50
    member.mention = "<@50>"
    member.display_avatar.url = "https://example.invalid/a.png"
    member.premium_since = discord.utils.utcnow() if boosting else None
    member.roles = list(roles)
    member.guild.id = HOME_SERVER_ID
    member.guild.get_role.side_effect = lambda role_id: BOOSTER if role_id == 16 else None
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    member.send = AsyncMock()
    return member


@pytest.fixture
def channels(bot, monkeypatch):
    mod_log = MagicMock(spec=discord.TextChannel)
    mod_log.send = AsyncMock()
    unboost = MagicMock(spec=discord.TextChannel)
    unboost.send = AsyncMock()
    lookup = {6: mod_log, 7: unboost}
    monkeypatch.setattr(bot, "get_channel", lookup.get)
    return MagicMock(mod_log=mod_log, unboost=unboost)


def make_interaction():
    interaction = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.display_avatar.url = "https://example.invalid/a.png"
    return interaction


async def test_boost_grants_the_role_and_thanks_the_member(bot, channels):
    cog = Community(bot)
    await cog.on_member_update(make_member(boosting=False), after := make_member(boosting=True))
    after.add_roles.assert_awaited_once()
    assert after.add_roles.await_args.args[0] is BOOSTER
    thanks = after.send.await_args.args[0]
    assert "<#12>" in thanks and "<#9>" in thanks  # booster and roles channels


async def test_unboost_announces_and_removes_booster_roles_only(bot, channels):
    cog = Community(bot)
    after = make_member(boosting=False, roles=[BOOSTER, COLOUR, OTHER])
    await cog.on_member_update(make_member(boosting=True), after)

    assert channels.unboost.send.await_args.kwargs["embed"].title == "Server unboosted"
    assert set(after.remove_roles.await_args.args) == {BOOSTER, COLOUR}


async def test_other_member_updates_are_ignored(bot, channels):
    cog = Community(bot)
    after = make_member(boosting=False)
    await cog.on_member_update(make_member(boosting=False), after)
    after.add_roles.assert_not_awaited()
    after.remove_roles.assert_not_awaited()
    channels.unboost.send.assert_not_awaited()


async def test_failed_booster_role_is_reported_to_the_mod_log(bot, channels):
    cog = Community(bot)
    after = make_member(boosting=True)
    after.add_roles.side_effect = discord.Forbidden(MagicMock(status=403), "nope")
    await cog.on_member_update(make_member(boosting=False), after)

    embed = channels.mod_log.send.await_args.kwargs["embed"]
    assert embed.title == "Could not assign the booster role"
    assert "<@50>" in embed.description
    after.send.assert_awaited_once()  # the thank-you still goes out


async def test_failed_role_removal_is_reported_to_the_mod_log(bot, channels):
    cog = Community(bot)
    after = make_member(boosting=False, roles=[BOOSTER])
    after.remove_roles.side_effect = discord.HTTPException(MagicMock(status=500), "oops")
    await cog.on_member_update(make_member(boosting=True), after)
    assert channels.mod_log.send.await_args.kwargs["embed"].title == (
        "Could not remove booster roles"
    )


async def test_boosters_is_unavailable_in_reduced_mode(reduced_bot):
    cog = Community(reduced_bot)
    interaction = make_interaction()
    await cog.boosters.callback(cog, interaction)

    kwargs = interaction.response.send_message.await_args.kwargs
    assert "temporarily unavailable" in kwargs["content"]
    assert kwargs["ephemeral"] is True
    interaction.response.defer.assert_not_awaited()


async def test_boosters_lists_members_oldest_first(bot, monkeypatch):
    now = discord.utils.utcnow()
    older, newer = MagicMock(), MagicMock()
    older.mention, older.premium_since = "<@1>", now - datetime.timedelta(days=30)
    newer.mention, newer.premium_since = "<@2>", now - datetime.timedelta(days=1)
    guild = MagicMock()
    guild.premium_subscribers = [newer, older]
    guild.premium_subscription_count = 3
    guild.premium_tier = 1
    guild.icon = None
    monkeypatch.setattr(bot, "get_guild", lambda guild_id: guild)

    cog = Community(bot)
    interaction = make_interaction()
    await cog.boosters.callback(cog, interaction)

    description = interaction.followup.send.await_args.kwargs["embed"].description
    assert description.index("<@1>") < description.index("<@2>")
    assert "**3** boost(s) from **2** member(s)" in description
