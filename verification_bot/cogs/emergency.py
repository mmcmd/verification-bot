"""Emergency ping requests, gated behind a staff vote with Approve/Deny buttons.

How a request runs:

* ``/emergency`` is acknowledged with a short private reply. The request itself
  is an ordinary channel message carrying the buttons. Every later change to it
  goes through that ``discord.Message`` object, which is edited with the bot's
  own credentials. Nothing depends on the slash command's interaction token,
  which Discord expires after 15 minutes.
* One clock (``_run_clock``) drives the whole request: a reminder after every
  interval and, one interval after the last reminder, the timeout. The buttons
  have no timeout of their own.
* However a request ends (approved, denied, cancelled, timed out), ``conclude``
  removes the buttons from the request message.
* Only the messages that are meant to ping the emergency role name that role in
  ``allowed_mentions``. Every other message can mention the caller at most.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import FAILURE, NEUTRAL, SUCCESS, actor_embed
from ..emergency import EmergencyRequest, EmergencyStatus, Vote, VoteOutcome, clock_schedule
from ..utils import message_link, respond

log = logging.getLogger(__name__)

REASON_MIN_LENGTH = 20
REASON_MAX_LENGTH = 500

#: How long the bot waits, while shutting down, for the buttons to be removed.
UNLOAD_EDIT_TIMEOUT = 5.0

OUTCOME_TEXT = {
    EmergencyStatus.APPROVED: "approved",
    EmergencyStatus.DENIED: "denied",
    EmergencyStatus.CANCELLED: "cancelled by a moderator",
    EmergencyStatus.TIMED_OUT: "timed out without enough votes",
}
RESTART_OUTCOME_TEXT = (
    "cancelled because the bot is restarting. Run `/emergency` again if it is still needed"
)


def role_ping(role: discord.Role) -> discord.AllowedMentions:
    """Mention settings for a message that is meant to ping the emergency role."""
    return discord.AllowedMentions(everyone=False, users=True, roles=[role])


def caller_only(caller_id: int) -> discord.AllowedMentions:
    """Mention settings for every other message: the caller at most, never a role."""
    return discord.AllowedMentions(
        everyone=False, users=[discord.Object(id=caller_id)], roles=False
    )


def defuse_mentions(text: str) -> str:
    """Make ``text`` unable to mention a user, a role, @everyone or @here.

    ``discord.utils.escape_mentions`` only catches well-formed mentions, so on
    top of it a zero-width space is put after every remaining "@". The text
    looks the same to a reader.
    """
    escaped = discord.utils.escape_mentions(text)
    return escaped.replace("@\u200b", "@").replace("@", "@\u200b")


class EmergencyView(discord.ui.View):
    """Approve/Deny buttons attached to a pending emergency request.

    The view never times out by itself: the cog's clock is the only timer, and
    the cog removes the buttons when the request ends.
    """

    def __init__(self, cog: Emergency, request: EmergencyRequest) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.request = request

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # The member comes with the button press itself, so this works without
        # the member list (reduced mode).
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if member.id == self.request.caller_id:
            await self.cog.reply(interaction, self.cog.bot.message("emergency.self_vote"))
            return False
        if not self.cog.can_vote(member):
            await self.cog.reply(interaction, self.cog.bot.message("emergency.not_a_voter"))
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.handle_vote(interaction, self.request, Vote.APPROVE)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.handle_vote(interaction, self.request, Vote.DENY)


class Emergency(commands.Cog):
    """A single emergency request may be active at a time, matching prior behaviour."""

    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self._request: EmergencyRequest | None = None
        self._view: EmergencyView | None = None
        self._message: discord.Message | None = None
        self._clock_task: asyncio.Task[None] | None = None
        #: Replaceable so tests can run the clock without waiting.
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def cog_unload(self) -> None:
        """Stop the clock and, if a request is open, take its buttons away.

        The request lives in memory only, so after a restart nothing would
        answer the buttons any more.
        """
        request, view, message, clock = (
            self._request,
            self._view,
            self._message,
            self._clock_task,
        )
        self._request = self._view = self._message = self._clock_task = None
        if clock is not None:
            clock.cancel()
        if view is not None:
            view.stop()
        if request is None or message is None or not request.cancel():
            return
        try:
            await asyncio.wait_for(
                message.edit(
                    content=self._render_closed(request, RESTART_OUTCOME_TEXT),
                    view=None,
                    allowed_mentions=discord.AllowedMentions.none(),
                ),
                timeout=UNLOAD_EDIT_TIMEOUT,
            )
        except Exception as error:  # shutting down: never let this stop the unload
            log.warning(
                "Could not remove the buttons of emergency request %s while unloading (%s)",
                request.message_id,
                type(error).__name__,
            )

    # -- who may vote ------------------------------------------------------

    def can_vote(self, member: discord.Member) -> bool:
        """Holders of a sudo voter role; while none is chosen, anyone above verified."""
        voter_roles = self.bot.settings.get("sudo_voter_roles")
        if voter_roles:
            return checks.has_any_role_id(member, voter_roles)
        return checks.outranks_role(member, self.bot.verified_role)

    # -- commands ----------------------------------------------------------

    @app_commands.command(
        name="emergency",
        description="Request an emergency ping for a time-critical production incident.",
    )
    @app_commands.describe(
        reason="What is broken, what have you already tried, and why is it urgent?"
    )
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 120.0, key=lambda interaction: interaction.guild_id)
    @checks.verified_only()
    @checks.ontopic_only()
    async def emergency(
        self,
        interaction: discord.Interaction,
        reason: app_commands.Range[str, REASON_MIN_LENGTH, REASON_MAX_LENGTH],
    ) -> None:
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if (
            guild is None
            or not isinstance(member, discord.Member)
            or not isinstance(channel, discord.abc.Messageable)
        ):
            await respond(interaction, "This command can only be used in a server.", ephemeral=True)
            return

        role_id = self.bot.settings.get("emergency_role")
        if role_id is None:
            await respond(
                interaction, str(checks.SettingNotConfigured("emergency role")), ephemeral=True
            )
            return
        emergency_role = guild.get_role(role_id)
        if emergency_role is None:
            log.error("Emergency role %s no longer exists", role_id)
            await respond(interaction, self.bot.message("emergency.role_missing"), ephemeral=True)
            await self.bot.report_failure(
                "Emergency role is missing",
                f"{member.mention} tried to use `/emergency` in <#{channel.id}>, but the "
                f"emergency role (ID `{role_id}`) no longer exists, so nobody could be pinged. "
                "An administrator has to choose a new emergency role with `/config`.",
                member=member,
                dedupe_key="emergency-role-missing",
            )
            return

        # The reason is text typed by a member and is repeated in messages that
        # ping. Break every "@" in it so it can never mention anyone or anything;
        # the ``allowed_mentions`` on each message are a second lock on top.
        reason = defuse_mentions(reason.strip())

        # Acknowledge within Discord's 3 seconds. From here on the interaction is
        # only used for one short private reply; the request is a channel message.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as error:
            log.warning("Could not acknowledge /emergency (HTTP %s)", error.status)

        if self.bot.has_setting_role(member, "emergency_bypass_roles"):
            await self._announce_bypass(interaction, member, channel, emergency_role, reason)
            return

        request: EmergencyRequest | None = None
        send_error: discord.HTTPException | None = None
        active_link: str | None = None
        async with self._lock:
            # Any request still in the slot counts, even one that was just settled
            # and is about to be announced: replacing it here would silently drop
            # that announcement (and, for an approval, the role ping).
            if self._request is not None:
                active_link = self._request.message_link or "unavailable"
            else:
                request = EmergencyRequest(
                    caller_id=member.id,
                    channel_id=channel.id,
                    guild_id=guild.id,
                    reason=reason,
                    approval_threshold=self.bot.settings.get("approval_threshold"),
                    deny_threshold=self.bot.settings.get("denial_threshold"),
                )
                view = EmergencyView(self, request)
                try:
                    sent = await channel.send(
                        self._render(request),
                        view=view,
                        allowed_mentions=caller_only(member.id),
                    )
                except discord.HTTPException as error:
                    # Nothing was stored yet, so no request is left "active".
                    view.stop()
                    send_error = error
                else:
                    request.message_id = sent.id
                    request.message_link = message_link(guild.id, channel.id, sent.id)
                    self._request = request
                    self._view = view
                    self._message = sent
                    self._clock_task = asyncio.create_task(
                        self._run_clock(
                            request,
                            channel,
                            interval=self.bot.settings.get("reminder_interval_seconds"),
                            reminders=self.bot.settings.get("reminder_count"),
                        )
                    )

        if active_link is not None:
            await self.reply(
                interaction, self.bot.message("emergency.already_active", link=active_link)
            )
            return
        assert request is not None
        if send_error is not None:
            await self._report_send_failure(interaction, member, channel, reason, send_error)
            return

        await self.reply(
            interaction,
            self.bot.message(
                "emergency.requested",
                link=request.message_link,
                approval_threshold=request.approval_threshold,
            ),
        )
        await self.bot.audit(
            actor_embed(
                member,
                title="Emergency requested",
                description=(
                    f"{member.mention} opened an emergency request in <#{channel.id}>.\n\n"
                    f"**Reason:** {reason}\n\n[Jump to request]({request.message_link})"
                ),
                colour=NEUTRAL,
            )
        )
        log.info("Emergency request %s opened by member %s", request.message_id, member.id)

    @app_commands.command(
        name="clearemergency", description="Cancel the currently pending emergency request."
    )
    @app_commands.guild_only()
    @checks.moderator_only()
    async def clear_emergency(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            request = self._request
            if request is None or not request.is_pending:
                request = None
            else:
                request.cancel()

        if request is None:
            await respond(interaction, self.bot.message("emergency.no_active"), ephemeral=True)
            return

        try:
            await respond(interaction, self.bot.message("emergency.cancelled"))
        except discord.HTTPException as error:
            log.warning("Could not answer /clearemergency (HTTP %s)", error.status)
        finally:
            # Always runs, so the buttons are removed even if the reply failed.
            await self.conclude(request, actor=interaction.user)
        log.info(
            "Emergency request %s cancelled by member %s",
            request.message_id,
            interaction.user.id,
        )

    # -- voting ------------------------------------------------------------

    async def handle_vote(
        self, interaction: discord.Interaction, request: EmergencyRequest, vote: Vote
    ) -> None:
        voter = interaction.user
        async with self._lock:
            if self._request is request:
                outcome = request.cast(voter.id, vote)
            else:
                outcome = VoteOutcome.CLOSED

        if outcome is VoteOutcome.SELF_VOTE:
            await self.reply(interaction, self.bot.message("emergency.self_vote"))
            return
        if outcome is VoteOutcome.CLOSED:
            await self.reply(interaction, self.bot.message("emergency.vote_closed"))
            # The buttons should already be gone. If an earlier edit failed and
            # they are still there, take them away now.
            stale = interaction.message
            if stale is not None and stale.components:
                try:
                    await stale.edit(view=None)
                except discord.HTTPException:
                    pass
            return
        if outcome is VoteOutcome.DUPLICATE:
            await self.reply(
                interaction, self.bot.message("emergency.vote_duplicate", vote=vote.value)
            )
            return

        # A vote that settles the request must always reach ``conclude``, whatever
        # happens to the private reply, the tally edit or the mod-log entry.
        try:
            await self.reply(
                interaction, self.bot.message("emergency.vote_recorded", vote=vote.value)
            )
            if request.is_pending:
                await self._update_message(request)
            await self.bot.audit(
                actor_embed(
                    voter,
                    title=f"Emergency request {vote.value}d",
                    description=(
                        f"{voter.mention} voted to {vote.value} emergency request "
                        f"`{request.message_id}` "
                        f"({request.approvals}/{request.approval_threshold} approvals, "
                        f"{request.denials}/{request.deny_threshold} denials).\n\n"
                        f"[Jump to request]({request.message_link})"
                    ),
                    colour=SUCCESS if vote is Vote.APPROVE else FAILURE,
                )
            )
            log.info(
                "Member %s voted %s on emergency request %s",
                voter.id,
                vote.value,
                request.message_id,
            )
        finally:
            if not request.is_pending:
                await self.conclude(request)

    # -- lifecycle helpers -------------------------------------------------

    async def conclude(
        self, request: EmergencyRequest, *, actor: discord.abc.User | None = None
    ) -> None:
        """Finish a resolved request: remove the buttons, announce it, clean up."""
        # Detach the request before awaiting anything, so a request opened while the
        # announcements are in flight is never clobbered by this conclusion.
        async with self._lock:
            if self._request is not request:
                return
            view, message, clock = self._view, self._message, self._clock_task
            self._request = None
            self._view = None
            self._message = None
            self._clock_task = None

        if clock is not None and clock is not asyncio.current_task():
            clock.cancel()
        if view is not None:
            view.stop()

        caller_mention = f"<@{request.caller_id}>"

        if message is not None:
            try:
                # Edited through the message object (bot credentials), so this
                # works no matter how long the request has been open.
                await message.edit(
                    content=self._render_closed(request, OUTCOME_TEXT[request.status]),
                    view=None,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.NotFound:
                # The request message was deleted, so its buttons are gone too.
                log.info("Emergency request message %s no longer exists", request.message_id)
            except Exception as error:
                # Also network errors and timeouts, which are not HTTPException:
                # whatever happens here, the outcome below must still be announced.
                status = getattr(error, "status", type(error).__name__)
                log.warning(
                    "Could not remove the buttons of emergency request %s (%s)",
                    request.message_id,
                    status,
                )
                await self.bot.report_failure(
                    "Emergency request message could not be updated",
                    f"The emergency request by {caller_mention} ended as "
                    f"**{request.status.value}**, but the bot could not edit its message "
                    f"({status}), so the Approve/Deny buttons may still be showing. "
                    "They no longer do anything; you can delete the message.\n\n"
                    f"[Jump to request]({request.message_link})",
                    dedupe_key=f"emergency-edit-{request.message_id}",
                )

        if message is not None:
            await self._announce_outcome(request, message.channel, caller_mention)

        if request.status is EmergencyStatus.CANCELLED and actor is not None:
            ending = f"was **cancelled** by {actor.mention}"
        else:
            ending = f"ended as **{request.status.value}**"
        await self.bot.audit(
            discord.Embed(
                title=f"Emergency request {request.status.value}",
                description=(
                    f"Request `{request.message_id}` by {caller_mention} {ending} "
                    f"({request.approvals} approvals / {request.denials} denials).\n\n"
                    f"[Jump to request]({request.message_link})"
                ),
                colour=SUCCESS if request.status is EmergencyStatus.APPROVED else FAILURE,
                timestamp=discord.utils.utcnow(),
            )
        )
        log.info("Emergency request %s concluded as %s", request.message_id, request.status.value)

    async def _announce_outcome(
        self,
        request: EmergencyRequest,
        channel: discord.abc.Messageable,
        caller_mention: str,
    ) -> None:
        """Post the result in the channel. Only an approval pings the emergency role."""
        mentions = caller_only(request.caller_id)
        if request.status is EmergencyStatus.APPROVED:
            # Looked up now, not when the request was opened: the role may have
            # been changed or deleted while the vote was running.
            role = self.bot.setting_role("emergency_role")
            if role is not None:
                mentions = role_ping(role)
                text = self.bot.message(
                    "emergency.approved",
                    caller=caller_mention,
                    reason=request.reason,
                    link=request.message_link,
                    role=role.mention,
                )
            else:
                text = self.bot.message(
                    "emergency.approved_no_role",
                    caller=caller_mention,
                    reason=request.reason,
                    link=request.message_link,
                )
                await self.bot.report_failure(
                    "Emergency approved but nobody was pinged",
                    f"The emergency request by {caller_mention} was approved, but the "
                    "emergency role is not set or no longer exists, so nobody was pinged. "
                    "An administrator has to choose an emergency role with `/config`.\n\n"
                    f"[Jump to request]({request.message_link})",
                )
        elif request.status is EmergencyStatus.DENIED:
            text = self.bot.message("emergency.denied", caller=caller_mention)
        elif request.status is EmergencyStatus.TIMED_OUT:
            text = self.bot.message(
                "emergency.timed_out", caller=caller_mention, link=request.message_link
            )
        else:
            # Cancelled: the reply to /clearemergency is the announcement.
            return

        try:
            await channel.send(text, allowed_mentions=mentions)
        except Exception as error:
            status = getattr(error, "status", type(error).__name__)
            log.warning(
                "Could not announce the outcome of emergency request %s (%s)",
                request.message_id,
                status,
            )
            await self.bot.report_failure(
                "Emergency outcome could not be announced",
                f"The emergency request by {caller_mention} ended as "
                f"**{request.status.value}**, but the bot could not post that in "
                f"<#{request.channel_id}> ({status})."
                + (
                    " **The emergency role was not pinged.**"
                    if request.status is EmergencyStatus.APPROVED
                    else ""
                )
                + f"\n\n[Jump to request]({request.message_link})",
            )

    async def _run_clock(
        self,
        request: EmergencyRequest,
        channel: discord.abc.Messageable,
        *,
        interval: int,
        reminders: int,
    ) -> None:
        """The only timer of a request.

        Sends a reminder after every ``interval`` seconds, ``reminders`` times,
        then waits one more interval and times the request out, exactly as the
        old bot did. With the defaults (180 seconds, 5 reminders) the reminders
        go out at 3, 6, 9, 12 and 15 minutes and the request ends at 18 minutes.
        """
        try:
            for is_reminder in clock_schedule(reminders):
                await self._sleep(interval)
                if not request.is_pending:
                    return
                if not is_reminder:
                    break
                request.reminders_sent += 1
                try:
                    await channel.send(
                        self.bot.message("emergency.reminder", link=request.message_link),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # A reminder that fails must not stop the clock, or the
                    # request would never time out.
                    log.warning(
                        "Could not send a reminder for emergency request %s (%s)",
                        request.message_id,
                        type(error).__name__,
                    )

            async with self._lock:
                timed_out = request.time_out()
            if timed_out:
                await self.conclude(request)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Emergency clock failed for request %s", request.message_id)

    async def _announce_bypass(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        channel: discord.abc.Messageable,
        emergency_role: discord.Role,
        reason: str,
    ) -> None:
        """Ping the emergency role straight away for a holder of a bypass role."""
        try:
            sent = await channel.send(
                self.bot.message(
                    "emergency.bypass",
                    caller=member.mention,
                    reason=reason,
                    role=emergency_role.mention,
                ),
                allowed_mentions=role_ping(emergency_role),
            )
        except discord.HTTPException as error:
            await self._report_send_failure(interaction, member, channel, reason, error)
            return

        link = message_link(member.guild.id, channel.id, sent.id)
        await self.reply(interaction, self.bot.message("emergency.bypass_sent", link=link))
        await self.bot.audit(
            actor_embed(
                member,
                title="Emergency called (approval bypassed)",
                description=(
                    f"{member.mention} called an emergency directly in <#{channel.id}>.\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"[Jump to message]({link})"
                ),
                colour=NEUTRAL,
            )
        )
        log.info("Member %s called an emergency using a bypass role", member.id)

    async def _report_send_failure(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        channel: discord.abc.Messageable,
        reason: str,
        error: discord.HTTPException,
    ) -> None:
        """The emergency message could not be posted: tell the caller and the moderators."""
        log.warning(
            "Could not post an emergency message in channel %s for member %s (HTTP %s)",
            channel.id,
            member.id,
            error.status,
        )
        await self.reply(interaction, self.bot.message("emergency.send_failed"))
        await self.bot.report_failure(
            "Emergency could not be posted",
            f"{member.mention} used `/emergency` in <#{channel.id}>, but the bot could not "
            f"post there (HTTP {error.status}), so **nobody was pinged**. Check that the bot "
            "may send messages in that channel.\n\n"
            f"**Reason given:** {reason}",
            member=member,
        )

    async def reply(self, interaction: discord.Interaction, text: str) -> None:
        """Send a private reply. Never raises, so the flow around it always continues."""
        try:
            await respond(interaction, text, ephemeral=True)
        except discord.HTTPException as error:
            log.warning("Could not send a private emergency reply (HTTP %s)", error.status)

    def _render(self, request: EmergencyRequest) -> str:
        return self.bot.message(
            "emergency.prompt",
            caller=f"<@{request.caller_id}>",
            reason=request.reason,
            approvals=request.approvals,
            approval_threshold=request.approval_threshold,
            denials=request.denials,
            deny_threshold=request.deny_threshold,
        )

    def _render_closed(self, request: EmergencyRequest, outcome: str) -> str:
        return self.bot.message(
            "emergency.closed",
            caller=f"<@{request.caller_id}>",
            reason=request.reason,
            outcome=outcome,
            approvals=request.approvals,
            approval_threshold=request.approval_threshold,
            denials=request.denials,
            deny_threshold=request.deny_threshold,
        )

    async def _update_message(self, request: EmergencyRequest) -> None:
        """Show the new tally on the request message while it is still open."""
        async with self._lock:
            if self._request is not request or self._message is None:
                return
            message, view = self._message, self._view
        try:
            await message.edit(
                content=self._render(request),
                view=view,
                allowed_mentions=caller_only(request.caller_id),
            )
        except Exception as error:
            # The vote itself is recorded and the clock still ends the request;
            # only the tally shown on the message is out of date. Network errors
            # and timeouts are caught too, so a vote never fails because of them.
            status = getattr(error, "status", type(error).__name__)
            log.warning(
                "Could not update emergency request message %s (%s)",
                request.message_id,
                status,
            )
            await self.bot.report_failure(
                "Emergency request message could not be updated",
                f"A vote on the emergency request by <@{request.caller_id}> was counted "
                f"({request.approvals}/{request.approval_threshold} approvals, "
                f"{request.denials}/{request.deny_threshold} denials), but the bot could not "
                f"update the tally on the message ({status}).\n\n"
                f"[Jump to request]({request.message_link})",
                dedupe_key=f"emergency-edit-{request.message_id}",
            )


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Emergency(bot))
