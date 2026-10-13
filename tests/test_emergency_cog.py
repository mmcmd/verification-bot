import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from verification_bot.cogs.emergency import Emergency, EmergencyView
from verification_bot.emergency import EmergencyStatus

from .conftest import HOME_SERVER_ID

REASON = "Production database is down and customers cannot log in"
CHANNEL_ID = 30
CALLER_ID = 50
#: Discord stops accepting an interaction token after 15 minutes.
INTERACTION_TOKEN_LIFETIME = 15 * 60


class FakeRole:
    """Just enough of a role: an ID, a mention and a place in the hierarchy."""

    def __init__(self, role_id, position=0):
        self.id = role_id
        self.position = position
        self.mention = f"<@&{role_id}>"

    def __gt__(self, other):
        return self.position > other.position


EVERYONE = FakeRole(HOME_SERVER_ID, 0)
VERIFIED = FakeRole(2, 1)
STAFF = FakeRole(90, 5)  # above verified, but not a sudo voter role
SUDO_VOTER = FakeRole(17, 3)
BYPASS = FakeRole(15, 8)
EMERGENCY_ROLE = FakeRole(14, 2)


def make_member(member_id, *roles):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.mention = f"<@{member_id}>"
    member.roles = [EVERYONE, *roles]
    member.top_role = max(member.roles, key=lambda role: role.position)
    member.display_avatar.url = "https://example.invalid/a.png"
    member.guild.id = HOME_SERVER_ID
    return member


def make_interaction(member, world):
    """A slash-command or button interaction that tracks whether it was answered."""
    interaction = MagicMock()
    interaction.user = member
    interaction.guild = world.guild
    interaction.guild_id = HOME_SERVER_ID
    interaction.channel = world.channel
    state = {"done": False}

    async def answer(*args, **kwargs):
        state["done"] = True

    interaction.response.is_done.side_effect = lambda: state["done"]
    interaction.response.defer = AsyncMock(side_effect=answer)
    interaction.response.send_message = AsyncMock(side_effect=answer)
    interaction.response.edit_message = AsyncMock(side_effect=answer)
    interaction.followup.send = AsyncMock()
    interaction.original_response = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.message.edit = AsyncMock()
    return interaction


def replies_of(interaction):
    """Every private text the interaction was answered with, in order."""
    calls = [
        *interaction.response.send_message.await_args_list,
        *interaction.followup.send.await_args_list,
    ]
    for call in calls:
        assert call.kwargs["ephemeral"] is True
    return [call.kwargs["content"] for call in calls]


class World:
    """A home server with one on-topic channel (30) and a mod-log channel (6)."""

    def __init__(self, bot, monkeypatch):
        self.bot = bot
        self.roles = {
            role.id: role for role in (VERIFIED, STAFF, SUDO_VOTER, BYPASS, EMERGENCY_ROLE)
        }
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = HOME_SERVER_ID
        self.guild.get_role.side_effect = lambda role_id: self.roles.get(role_id)
        # Nothing in the feature may need the member list.
        self.guild.get_member.return_value = None

        self.sent = []  # every message posted in the channel, as mocks
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id = CHANNEL_ID
        self.channel.send = AsyncMock(side_effect=self._send)
        self.mod_log = MagicMock(spec=discord.TextChannel)
        self.mod_log.send = AsyncMock()

        monkeypatch.setattr(bot, "get_guild", lambda guild_id: self.guild)
        monkeypatch.setattr(bot, "get_channel", lambda cid: self.mod_log if cid == 6 else None)

        self.cog = Emergency(bot)
        self.sleeps = []
        self.cog._sleep = self._sleep_forever

    async def _send(self, content=None, **kwargs):
        message = MagicMock(spec=discord.Message)
        message.id = 1000 + len(self.sent)
        message.channel = self.channel
        message.content = content
        message.edit = AsyncMock()
        self.sent.append(message)
        return message

    async def _sleep_forever(self, seconds):
        self.sleeps.append(seconds)
        await asyncio.Event().wait()

    async def _sleep_instantly(self, seconds):
        self.sleeps.append(seconds)
        await asyncio.sleep(0)

    def run_clock_instantly(self):
        self.cog._sleep = self._sleep_instantly

    # -- actions -----------------------------------------------------------

    async def call(self, member=None, reason=REASON):
        member = member or make_member(CALLER_ID, VERIFIED)
        interaction = make_interaction(member, self)
        await self.cog.emergency.callback(self.cog, interaction, reason)
        return interaction

    async def press(self, member, button="approve"):
        """Press a button on the open request the way discord.py would."""
        view = self.cog._view
        interaction = make_interaction(member, self)
        interaction.message = self.prompt
        if await view.interaction_check(interaction):
            await getattr(view, button).callback(interaction)
        return interaction

    # -- observations ------------------------------------------------------

    @property
    def prompt(self):
        return self.sent[0]

    def send_call(self, index):
        return self.channel.send.await_args_list[index]

    def logged_titles(self):
        return [call.kwargs["embed"].title for call in self.mod_log.send.await_args_list]

    def logged(self, title):
        for call in self.mod_log.send.await_args_list:
            if call.kwargs["embed"].title == title:
                return call.kwargs["embed"]
        raise AssertionError(f"no mod-log entry titled {title!r}: {self.logged_titles()}")


@pytest.fixture
def world(bot, monkeypatch):
    return World(bot, monkeypatch)


def voter(member_id):
    return make_member(member_id, VERIFIED, SUDO_VOTER)


def assert_only_caller_can_be_mentioned(allowed):
    data = allowed.to_dict()
    assert "everyone" not in data["parse"] and "roles" not in data["parse"]
    assert data.get("roles", []) == []
    assert "users" not in data["parse"]
    assert data.get("users", []) in ([], [CALLER_ID])


def assert_pings_exactly(allowed, role):
    assert allowed.everyone is False
    assert allowed.users is True
    assert allowed.roles == [role]
    assert allowed.to_dict()["roles"] == [role.id]
    assert "everyone" not in allowed.to_dict()["parse"]


# -- opening a request ---------------------------------------------------------


async def test_the_prompt_is_a_channel_message_not_an_interaction_reply(world):
    interaction = await world.call()

    # The request with its buttons went out through channel.send ...
    assert world.channel.send.await_count == 1
    call = world.send_call(0)
    assert REASON in call.args[0]
    assert isinstance(call.kwargs["view"], EmergencyView)
    assert_only_caller_can_be_mentioned(call.kwargs["allowed_mentions"])
    assert world.cog._message is world.prompt

    # ... and the slash command only got a short private acknowledgement.
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    (ack,) = replies_of(interaction)
    assert f"/channels/{HOME_SERVER_ID}/{CHANNEL_ID}/{world.prompt.id}" in ack
    interaction.original_response.assert_not_awaited()
    interaction.edit_original_response.assert_not_awaited()

    entry = world.logged("Emergency requested")
    assert REASON in entry.description and f"<@{CALLER_ID}>" in entry.description


async def test_later_edits_go_through_the_message_object(world):
    interaction = await world.call()
    await world.press(voter(60))

    world.prompt.edit.assert_awaited_once()
    edit = world.prompt.edit.await_args.kwargs
    assert "Approved: 1/3" in edit["content"]
    assert edit["view"] is world.cog._view
    interaction.original_response.assert_not_awaited()
    interaction.edit_original_response.assert_not_awaited()
    assert interaction.followup.send.await_count == 1  # the acknowledgement, nothing since


async def test_the_buttons_have_no_clock_of_their_own(world):
    await world.call()
    assert world.cog._view.timeout is None


async def test_a_second_request_is_refused_while_one_is_active(world):
    await world.call()
    second = await world.call(make_member(51, VERIFIED))

    assert world.channel.send.await_count == 1
    (reply,) = replies_of(second)
    assert "already an active emergency request" in reply
    assert str(world.prompt.id) in reply
    assert world.cog._request.caller_id == CALLER_ID


async def test_unset_emergency_role_points_at_config(bot, world):
    bot.settings.reset("emergency_role")
    interaction = await world.call()

    (reply,) = replies_of(interaction)
    assert "/config" in reply and "administrator" in reply
    world.channel.send.assert_not_awaited()
    assert world.cog._request is None


async def test_deleted_emergency_role_is_reported_to_the_moderators(world):
    del world.roles[EMERGENCY_ROLE.id]
    first = await world.call()
    await world.call()

    (reply,) = replies_of(first)
    assert "no longer exists" in reply
    world.channel.send.assert_not_awaited()
    assert world.cog._request is None
    # Reported once: the dedupe key stops it repeating on every attempt.
    assert world.logged_titles() == ["Emergency role is missing"]
    assert f"<@{CALLER_ID}>" in world.logged("Emergency role is missing").description


async def test_a_prompt_that_cannot_be_sent_leaves_nothing_active(world):
    world.channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "no access")
    interaction = await world.call()

    assert world.cog._request is None
    assert world.cog._clock_task is None
    (reply,) = replies_of(interaction)
    assert "could not post" in reply
    assert world.logged_titles() == ["Emergency could not be posted"]

    # The next request is not refused as "already active".
    world.channel.send.side_effect = world._send
    await world.call()
    assert world.cog._request is not None


async def test_the_reason_cannot_ping_anyone(world):
    await world.call(
        reason="All down @everyone @here <@&14> <@99> <@&385498779471839233> <@562349906648629259>"
    )
    content = world.send_call(0).args[0]
    reason_line = next(line for line in content.splitlines() if line.startswith("**Reason:**"))

    for mention in ("@everyone", "@here", "<@&", "<@9", "<@5"):
        assert mention not in reason_line
    assert "@" not in reason_line.replace("@\u200b", "")
    assert_only_caller_can_be_mentioned(world.send_call(0).kwargs["allowed_mentions"])


# -- the clock -----------------------------------------------------------------


@pytest.mark.parametrize(("interval", "count"), [(180, 5), (15, 1), (60, 3)])
async def test_n_reminders_then_a_timeout(bot, world, interval, count):
    bot.settings.set("reminder_interval_seconds", interval)
    bot.settings.set("reminder_count", count)
    world.run_clock_instantly()

    interaction = await world.call()
    request, view, clock = world.cog._request, world.cog._view, world.cog._clock_task
    await clock

    # One clock: a wait before each reminder, then one more before the timeout.
    assert world.sleeps == [interval] * (count + 1)
    texts = [call.args[0] for call in world.channel.send.await_args_list]
    assert len(texts) == 1 + count + 1  # prompt, reminders, timeout notice
    assert all("awaiting approval" in text for text in texts[1 : 1 + count])
    assert "timed out" in texts[-1]
    assert request.reminders_sent == count
    assert request.status is EmergencyStatus.TIMED_OUT

    # The buttons are gone, removed through the message object.
    world.prompt.edit.assert_awaited_once()
    assert world.prompt.edit.await_args.kwargs["view"] is None
    assert "timed out" in world.prompt.edit.await_args.kwargs["content"]
    assert view.is_finished()
    interaction.original_response.assert_not_awaited()
    interaction.edit_original_response.assert_not_awaited()
    assert interaction.followup.send.await_count == 1

    assert world.cog._request is None and world.cog._clock_task is None
    assert world.logged_titles() == ["Emergency requested", "Emergency request timed_out"]


async def test_production_timings_outlive_the_interaction_token_and_still_clean_up(world):
    """180 s x 5: the request ends after 18 minutes, past the token's 15."""
    world.run_clock_instantly()
    interaction = await world.call()
    await world.cog._clock_task

    assert world.sleeps == [180] * 6
    assert sum(world.sleeps) > INTERACTION_TOKEN_LIFETIME
    assert world.prompt.edit.await_args.kwargs["view"] is None
    interaction.edit_original_response.assert_not_awaited()
    interaction.original_response.assert_not_awaited()


async def test_reminders_and_notices_ping_no_role(world):
    world.run_clock_instantly()
    await world.call()
    await world.cog._clock_task

    for call in world.channel.send.await_args_list:
        assert_only_caller_can_be_mentioned(call.kwargs["allowed_mentions"])


async def test_a_failed_reminder_does_not_stop_the_clock(world):
    world.run_clock_instantly()
    await world.call()
    real_send = world._send

    async def flaky(content=None, **kwargs):
        if "awaiting approval" in content:
            raise discord.HTTPException(MagicMock(status=500), "server error")
        return await real_send(content, **kwargs)

    world.channel.send.side_effect = flaky
    await world.cog._clock_task

    assert world.sleeps == [180] * 6
    assert world.prompt.edit.await_args.kwargs["view"] is None
    assert world.cog._request is None


async def test_a_settled_request_stops_the_clock(world):
    await world.call()
    clock = world.cog._clock_task
    await asyncio.sleep(0)  # let the clock start its first wait
    for member_id in (60, 61, 62):
        await world.press(voter(member_id))
    await asyncio.sleep(0)

    assert clock.cancelled()
    assert world.sleeps == [180]


# -- who may vote --------------------------------------------------------------


async def test_a_sudo_voter_role_holder_may_vote(world):
    await world.call()
    interaction = await world.press(voter(60))

    assert world.cog._request.approvals == 1
    assert "recorded" in replies_of(interaction)[0]
    assert "Emergency request approved" in world.logged_titles()


async def test_staff_without_a_voter_role_may_not_vote_when_the_list_is_set(world):
    await world.call()
    interaction = await world.press(make_member(60, VERIFIED, STAFF))

    assert world.cog._request.approvals == 0
    assert "sudo level 1" in replies_of(interaction)[0]
    world.prompt.edit.assert_not_awaited()


async def test_with_no_voter_roles_anyone_above_verified_may_vote(bot, world):
    bot.settings.reset("sudo_voter_roles")
    await world.call()

    await world.press(make_member(60, VERIFIED, STAFF))
    assert world.cog._request.approvals == 1

    # Top role equal to the verified role is not "above" it.
    refused = await world.press(make_member(61, VERIFIED))
    assert world.cog._request.approvals == 1
    assert "sudo level 1" in replies_of(refused)[0]


async def test_with_no_voter_roles_and_no_verified_role_nobody_may_vote(bot, world):
    bot.settings.reset("sudo_voter_roles")
    await world.call()
    del world.roles[VERIFIED.id]

    await world.press(make_member(60, VERIFIED, STAFF))
    assert world.cog._request.approvals == 0


async def test_the_caller_cannot_vote_on_their_own_request(world):
    caller = make_member(CALLER_ID, VERIFIED, SUDO_VOTER)
    await world.call(caller)

    for button in ("approve", "deny"):
        interaction = await world.press(caller, button)
        assert "your own" in replies_of(interaction)[0]
    assert (world.cog._request.approvals, world.cog._request.denials) == (0, 0)


async def test_a_repeated_vote_is_counted_once(world):
    await world.call()
    member = voter(60)
    await world.press(member)
    again = await world.press(member)

    assert world.cog._request.approvals == 1
    assert "already voted" in replies_of(again)[0]


# -- outcomes ------------------------------------------------------------------


async def test_approval_pings_exactly_the_emergency_role(world):
    await world.call()
    for member_id in (60, 61, 62):
        await world.press(voter(member_id))

    assert world.channel.send.await_count == 2
    ping = world.send_call(1)
    assert EMERGENCY_ROLE.mention in ping.args[0]
    assert f"<@{CALLER_ID}>" in ping.args[0] and REASON in ping.args[0]
    assert_pings_exactly(ping.kwargs["allowed_mentions"], EMERGENCY_ROLE)

    # Buttons removed, state cleared, everything in the mod-log.
    final_edit = world.prompt.edit.await_args.kwargs
    assert final_edit["view"] is None and "approved" in final_edit["content"]
    assert world.cog._request is None
    assert world.logged_titles() == [
        "Emergency requested",
        "Emergency request approved",
        "Emergency request approved",
        "Emergency request approved",
        "Emergency request approved",
    ]
    assert "ended as **approved**" in world.mod_log.send.await_args.kwargs["embed"].description


async def test_approval_when_the_role_vanished_during_the_vote(world):
    await world.call()
    del world.roles[EMERGENCY_ROLE.id]
    for member_id in (60, 61, 62):
        await world.press(voter(member_id))

    notice = world.send_call(1)
    assert "nobody could be pinged" in notice.args[0]
    assert_only_caller_can_be_mentioned(notice.kwargs["allowed_mentions"])
    assert "Emergency approved but nobody was pinged" in world.logged_titles()


async def test_denial_closes_the_request_without_a_role_ping(world):
    await world.call()
    await world.press(voter(60), "deny")
    await world.press(voter(61), "deny")

    notice = world.send_call(1)
    assert "has been denied" in notice.args[0]
    assert EMERGENCY_ROLE.mention not in notice.args[0]
    assert_only_caller_can_be_mentioned(notice.kwargs["allowed_mentions"])
    assert world.prompt.edit.await_args.kwargs["view"] is None
    assert world.cog._request is None
    assert world.logged_titles()[-1] == "Emergency request denied"


async def test_a_vote_still_settles_the_request_when_its_reply_fails(world):
    """An expired button interaction must not leave the request stuck."""
    await world.call()
    await world.press(voter(60), "deny")

    view = world.cog._view
    interaction = make_interaction(voter(61), world)
    interaction.response.send_message.side_effect = discord.NotFound(
        MagicMock(status=404), "unknown interaction"
    )
    assert await view.interaction_check(interaction)
    await view.deny.callback(interaction)

    assert world.cog._request is None
    assert world.prompt.edit.await_args.kwargs["view"] is None


async def test_a_press_on_a_closed_request_removes_leftover_buttons(world):
    await world.call()
    view = world.cog._view
    await world.press(voter(60), "deny")
    await world.press(voter(61), "deny")

    late = make_interaction(voter(62), world)
    await view.approve.callback(late)

    assert "already been resolved" in replies_of(late)[0]
    late.message.edit.assert_awaited_once_with(view=None)


async def test_a_failed_final_edit_is_reported_and_state_is_still_cleared(world):
    await world.call()
    world.prompt.edit.side_effect = discord.HTTPException(MagicMock(status=500), "server error")
    await world.press(voter(60), "deny")
    await world.press(voter(61), "deny")

    assert world.cog._request is None
    assert "Emergency request message could not be updated" in world.logged_titles()
    assert "has been denied" in world.send_call(1).args[0]


# -- /clearemergency -----------------------------------------------------------


async def test_clearemergency_cancels_and_removes_the_buttons(world):
    await world.call()
    clock = world.cog._clock_task
    moderator = make_member(70, VERIFIED)
    interaction = make_interaction(moderator, world)

    await world.cog.clear_emergency.callback(world.cog, interaction)
    await asyncio.sleep(0)

    assert "cancelled" in interaction.response.send_message.await_args.kwargs["content"]
    edit = world.prompt.edit.await_args.kwargs
    assert edit["view"] is None and "cancelled by a moderator" in edit["content"]
    assert world.cog._request is None
    assert clock.cancelled()
    assert world.channel.send.await_count == 1  # no ping, no extra notice
    entry = world.logged("Emergency request cancelled")
    assert "<@70>" in entry.description

    # A new request can be opened straight away.
    await world.call(make_member(51, VERIFIED))
    assert world.cog._request.caller_id == 51


async def test_clearemergency_with_nothing_active(world):
    interaction = make_interaction(make_member(70, VERIFIED), world)
    await world.cog.clear_emergency.callback(world.cog, interaction)

    (reply,) = replies_of(interaction)
    assert "no active emergency" in reply
    world.mod_log.send.assert_not_awaited()


async def test_clearemergency_is_moderator_only(loaded_bot):
    from verification_bot import checks

    command = loaded_bot.tree.get_command("clearemergency")
    assert checks.audience_of(command) is checks.Audience.MODERATOR


# -- bypass --------------------------------------------------------------------


async def test_a_bypass_role_pings_immediately_and_opens_no_vote(world):
    caller = make_member(CALLER_ID, VERIFIED, BYPASS)
    interaction = await world.call(caller)

    assert world.channel.send.await_count == 1
    ping = world.send_call(0)
    assert EMERGENCY_ROLE.mention in ping.args[0] and REASON in ping.args[0]
    assert "view" not in ping.kwargs
    assert_pings_exactly(ping.kwargs["allowed_mentions"], EMERGENCY_ROLE)

    assert world.cog._request is None and world.cog._clock_task is None
    (ack,) = replies_of(interaction)
    assert "has been sent" in ack
    assert world.logged_titles() == ["Emergency called (approval bypassed)"]
    assert REASON in world.logged("Emergency called (approval bypassed)").description


async def test_the_bypass_reads_a_role_list_not_digits(bot, world):
    """The old bot split one role ID into digits, so the bypass never matched."""
    bot.settings.set("emergency_bypass_roles", [362980050527715329])
    production_bypass = FakeRole(362980050527715329, 9)

    await world.call(make_member(CALLER_ID, VERIFIED, production_bypass))
    assert world.cog._request is None
    assert_pings_exactly(world.send_call(0).kwargs["allowed_mentions"], EMERGENCY_ROLE)


async def test_a_bypass_does_not_disturb_an_open_request(world):
    await world.call()
    await world.call(make_member(51, VERIFIED, BYPASS))

    assert world.cog._request.caller_id == CALLER_ID
    assert world.channel.send.await_count == 2


async def test_a_bypass_ping_that_cannot_be_sent_is_reported(world):
    world.channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "no access")
    interaction = await world.call(make_member(CALLER_ID, VERIFIED, BYPASS))

    assert "could not post" in replies_of(interaction)[0]
    assert world.logged_titles() == ["Emergency could not be posted"]


# -- reduced mode and shutdown -------------------------------------------------


async def test_the_whole_flow_works_without_the_member_list(reduced_bot, monkeypatch):
    world = World(reduced_bot, monkeypatch)
    assert reduced_bot.reduced_mode
    await world.call()
    for member_id in (60, 61, 62):
        await world.press(voter(member_id))

    world.guild.get_member.assert_not_called()
    world.guild.fetch_member.assert_not_called()
    ping = world.send_call(1)
    assert f"<@{CALLER_ID}>" in ping.args[0]
    assert_pings_exactly(ping.kwargs["allowed_mentions"], EMERGENCY_ROLE)
    assert world.prompt.edit.await_args.kwargs["view"] is None


async def test_unloading_the_cog_removes_the_buttons(world):
    await world.call()
    clock = world.cog._clock_task
    await world.cog.cog_unload()
    await asyncio.sleep(0)

    edit = world.prompt.edit.await_args.kwargs
    assert edit["view"] is None and "restarting" in edit["content"]
    assert clock.cancelled()
    assert world.cog._request is None


# -- logging -------------------------------------------------------------------


async def test_logs_carry_ids_only(world, caplog):
    caplog.set_level("DEBUG")
    world.run_clock_instantly()
    await world.call()
    await world.press(voter(60))
    await world.cog._clock_task

    assert caplog.records
    for record in caplog.records:
        text = record.getMessage()
        assert "database" not in text  # the reason
        assert "<@" not in text


# -- found in review: the request slot and non-HTTP failures -----------------


async def test_new_request_cannot_replace_one_that_is_about_to_be_announced(world):
    """A second /emergency during the deciding vote must not drop the approval ping."""
    await world.call()
    await world.press(voter(101))
    await world.press(voter(102))
    first = world.cog._request

    # Hold the private reply to the deciding vote, as a slow network would.
    gate = asyncio.Event()
    original_reply = world.cog.reply

    async def slow_reply(interaction, text):
        if "recorded" in text:
            await gate.wait()
        await original_reply(interaction, text)

    world.cog.reply = slow_reply
    deciding = asyncio.create_task(world.press(voter(103)))
    await asyncio.sleep(0.01)
    assert first.status is EmergencyStatus.APPROVED

    second = await world.call(member=make_member(77, VERIFIED))
    assert world.cog._request is first  # refused: the slot is still taken
    assert "already an active emergency request" in replies_of(second)[-1]

    gate.set()
    await deciding
    pings = [
        call for call in world.channel.send.await_args_list
        if EMERGENCY_ROLE in (call.kwargs["allowed_mentions"].roles or [])
    ]
    assert len(pings) == 1
    assert world.cog._request is None


async def test_network_error_on_the_final_edit_still_pings_the_role(world):
    """Timeouts are not HTTPException; they must not skip the announcement."""
    await world.call()
    world.prompt.edit.side_effect = asyncio.TimeoutError()
    for member_id in (101, 102, 103):
        await world.press(voter(member_id))

    last = world.channel.send.await_args_list[-1]
    assert last.kwargs["allowed_mentions"].roles == [EMERGENCY_ROLE]
    assert world.cog._request is None
    assert "Emergency request message could not be updated" in world.logged_titles()
