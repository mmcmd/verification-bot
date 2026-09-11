"""Emergency ping requests, gated behind staff approval via message components."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import FAILURE, NEUTRAL, SUCCESS, actor_embed
from ..emergency import EmergencyRequest, EmergencyStatus, Vote, VoteOutcome
from ..utils import message_link, respond

log = logging.getLogger(__name__)

REASON_MIN_LENGTH = 20
REASON_MAX_LENGTH = 500


class EmergencyView(discord.ui.View):
    """Approve/deny buttons attached to a pending emergency request."""

    def __init__(self, cog: Emergency, request: EmergencyRequest, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.request = request

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if not checks.outranks_role(member, self.cog.bot.verified_role):
            await interaction.response.send_message(
                "Only staff ranked above the verified role can vote on emergency requests.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="\u2705")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.handle_vote(interaction, self.request, Vote.APPROVE)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="\u274c")
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.handle_vote(interaction, self.request, Vote.DENY)

    async def on_timeout(self) -> None:
        if self.request.time_out():
            await self.cog.conclude(self.request)


class Emergency(commands.Cog):
    """A single emergency request may be active at a time, matching prior behaviour."""

    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self._request: EmergencyRequest | None = None
        self._view: EmergencyView | None = None
        self._message: discord.Message | None = None
        self._reminder_task: asyncio.Task[None] | None = None

    async def cog_unload(self) -> None:
        if self._reminder_task is not None:
            self._reminder_task.cancel()
        if self._view is not None:
            self._view.stop()

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
        if guild is None or not isinstance(member, discord.Member) or channel is None:
            await respond(interaction, "This command can only be used in a server.", ephemeral=True)
            return

        emergency_role = guild.get_role(self.bot.config.emergency_role_id)
        if emergency_role is None:
            log.error("Emergency role %s is missing", self.bot.config.emergency_role_id)
            await respond(
                interaction, "The emergency role is not configured correctly.", ephemeral=True
            )
            return

        reason = discord.utils.escape_mentions(reason.strip())

        if checks.has_any_role_id(member, self.bot.config.emergency_top_role_bypass_ids):
            await self._announce_bypass(interaction, member, emergency_role, reason)
            return

        async with self._lock:
            if self._request is not None and self._request.is_pending:
                await respond(
                    interaction,
                    self.bot.message(
                        "emergency.already_active", link=self._request.message_link or "unavailable"
                    ),
                    ephemeral=True,
                )
                return

            request = EmergencyRequest(
                caller_id=member.id,
                channel_id=channel.id,
                guild_id=guild.id,
                reason=reason,
                approval_threshold=self.bot.config.emergency_request_approval_threshold,
                deny_threshold=self.bot.config.emergency_request_deny_threshold,
            )
            view = EmergencyView(
                self, request, timeout=float(self.bot.config.emergency_total_timeout_seconds + 60)
            )

            await interaction.response.send_message(self._render(request, member))
            sent = await interaction.original_response()

            request.message_id = sent.id
            request.message_link = message_link(guild.id, channel.id, sent.id)
            await sent.edit(content=self._render(request, member), view=view)

            self._request = request
            self._view = view
            self._message = sent
            self._reminder_task = asyncio.create_task(self._reminder_loop(request))

        await self.bot.audit(
            actor_embed(
                member,
                title="Emergency requested",
                description=(
                    f"{member.mention} opened an emergency request in {channel.mention}.\n\n"
                    f"**Reason:** {reason}\n\n[Jump to request]({request.message_link})"
                ),
                colour=NEUTRAL,
            )
        )
        log.info("Emergency request %s opened by %s (%s)", request.message_id, member, member.id)

    @app_commands.command(
        name="clearemergency", description="Cancel the currently pending emergency request."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @checks.moderator_only()
    async def clear_emergency(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            request = self._request
            if request is None or not request.is_pending:
                await respond(interaction, self.bot.message("emergency.no_active"), ephemeral=True)
                return
            request.cancel()

        await respond(interaction, self.bot.message("emergency.cancelled"))
        await self.conclude(request)
        log.info(
            "Emergency request %s cancelled by %s (%s)",
            request.message_id,
            interaction.user,
            interaction.user.id,
        )

    # -- voting ------------------------------------------------------------

    async def handle_vote(
        self, interaction: discord.Interaction, request: EmergencyRequest, vote: Vote
    ) -> None:
        async with self._lock:
            outcome = request.cast(interaction.user.id, vote)

        if outcome is VoteOutcome.SELF_VOTE:
            await interaction.response.send_message(
                "You cannot vote on your own emergency request.", ephemeral=True
            )
            return
        if outcome is VoteOutcome.CLOSED:
            await interaction.response.send_message(
                "This emergency request has already been resolved.", ephemeral=True
            )
            return
        if outcome is VoteOutcome.DUPLICATE:
            await interaction.response.send_message(
                f"You have already voted to {vote.value} this request.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Your vote to **{vote.value}** has been recorded.", ephemeral=True
        )

        caller = await self._resolve_caller(request)
        await self._update_message(request, caller)
        await self.bot.audit(
            actor_embed(
                interaction.user,
                title=f"Emergency request {vote.value}d",
                description=(
                    f"{interaction.user.mention} voted to {vote.value} emergency request "
                    f"`{request.message_id}` "
                    f"({request.approvals}/{request.approval_threshold} approvals, "
                    f"{request.denials}/{request.deny_threshold} denials).\n\n"
                    f"[Jump to request]({request.message_link})"
                ),
                colour=SUCCESS if vote is Vote.APPROVE else FAILURE,
            )
        )
        log.info(
            "%s (%s) voted %s on emergency request %s",
            interaction.user,
            interaction.user.id,
            vote.value,
            request.message_id,
        )

        if not request.is_pending:
            await self.conclude(request)

    # -- lifecycle helpers -------------------------------------------------

    async def conclude(self, request: EmergencyRequest) -> None:
        """Finish a resolved request: announce the outcome and clean up state."""
        if self._request is not request:
            return

        if self._reminder_task is not None and self._reminder_task is not asyncio.current_task():
            self._reminder_task.cancel()
        if self._view is not None:
            self._view.stop()

        caller = await self._resolve_caller(request)
        await self._update_message(request, caller, disable=True)

        channel = self.bot.get_channel(request.channel_id)
        caller_mention = caller.mention if caller else f"<@{request.caller_id}>"

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                if request.status is EmergencyStatus.APPROVED:
                    guild = self.bot.get_guild(request.guild_id)
                    role = guild.get_role(self.bot.config.emergency_role_id) if guild else None
                    await channel.send(
                        self.bot.message(
                            "emergency.approved",
                            caller=caller_mention,
                            reason=request.reason,
                            link=request.message_link,
                            role=role.mention if role else "",
                        )
                    )
                elif request.status is EmergencyStatus.DENIED:
                    await channel.send(
                        self.bot.message("emergency.denied", caller=caller_mention)
                    )
                elif request.status is EmergencyStatus.TIMED_OUT:
                    await channel.send(
                        self.bot.message(
                            "emergency.timed_out",
                            caller=caller_mention,
                            link=request.message_link,
                        )
                    )
            except discord.HTTPException:
                log.exception("Failed to announce the outcome of request %s", request.message_id)

        await self.bot.audit(
            discord.Embed(
                title=f"Emergency request {request.status.value}",
                description=(
                    f"Request `{request.message_id}` by {caller_mention} ended as "
                    f"**{request.status.value}** "
                    f"({request.approvals} approvals / {request.denials} denials)."
                ),
                colour=SUCCESS if request.status is EmergencyStatus.APPROVED else FAILURE,
                timestamp=discord.utils.utcnow(),
            )
        )
        log.info("Emergency request %s concluded as %s", request.message_id, request.status.value)

        self._request = None
        self._view = None
        self._message = None
        self._reminder_task = None

    async def _reminder_loop(self, request: EmergencyRequest) -> None:
        interval = self.bot.config.emergency_role_reminder
        limit = self.bot.config.emergency_role_timeout
        channel = self.bot.get_channel(request.channel_id)
        try:
            while request.is_pending:
                await asyncio.sleep(interval)
                if not request.is_pending:
                    return
                if request.reminders_sent >= limit:
                    request.time_out()
                    await self.conclude(request)
                    return
                request.reminders_sent += 1
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    await channel.send(
                        self.bot.message("emergency.reminder", link=request.message_link)
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Emergency reminder loop failed for request %s", request.message_id)

    async def _announce_bypass(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        emergency_role: discord.Role,
        reason: str,
    ) -> None:
        await interaction.response.send_message(
            self.bot.message(
                "emergency.bypass",
                caller=member.mention,
                reason=reason,
                role=emergency_role.mention,
            )
        )
        sent = await interaction.original_response()
        await self.bot.audit(
            actor_embed(
                member,
                title="Emergency called (approval bypassed)",
                description=(
                    f"{member.mention} called an emergency directly in "
                    f"{getattr(interaction.channel, 'mention', 'an unknown channel')}.\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"[Jump to message]({message_link(member.guild.id, sent.channel.id, sent.id)})"
                ),
                colour=NEUTRAL,
            )
        )
        log.info("%s (%s) called an emergency using a bypass role", member, member.id)

    async def _resolve_caller(self, request: EmergencyRequest) -> discord.Member | None:
        guild = self.bot.get_guild(request.guild_id)
        return guild.get_member(request.caller_id) if guild else None

    def _render(self, request: EmergencyRequest, caller: discord.Member | None) -> str:
        return self.bot.message(
            "emergency.prompt",
            caller=caller.mention if caller else f"<@{request.caller_id}>",
            reason=request.reason,
            approvals=request.approvals,
            approval_threshold=request.approval_threshold,
            denials=request.denials,
            deny_threshold=request.deny_threshold,
        )

    async def _update_message(
        self, request: EmergencyRequest, caller: discord.Member | None, *, disable: bool = False
    ) -> None:
        if self._message is None:
            return
        view: discord.ui.View | None = self._view
        if disable:
            view = None
        try:
            await self._message.edit(content=self._render(request, caller), view=view)
        except discord.HTTPException:
            log.exception("Failed to update emergency request message %s", request.message_id)


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Emergency(bot))
