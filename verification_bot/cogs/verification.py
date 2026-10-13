"""Account-age based verification.

Verification is entirely driven by the ``/verify`` application command, which is
registered globally so members can run it from a DM with the bot. No message
content is ever read.
"""

from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..client import VerificationBot
from ..embeds import FAILURE, SUCCESS, actor_embed
from ..utils import account_age_days, respond

log = logging.getLogger(__name__)

#: How long to wait before answering the same user's DM again.
DM_HINT_COOLDOWN = datetime.timedelta(minutes=10)


class Verification(commands.Cog):
    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot
        # In memory only, and pruned so it cannot grow without bound.
        self._dm_hint_sent: dict[int, datetime.datetime] = {}
        self._dm_hints_pruned_at = discord.utils.utcnow()

    # -- commands ----------------------------------------------------------

    @app_commands.command(
        name="verify",
        description="Get access to the server without sharing a phone number.",
    )
    @app_commands.checks.cooldown(2, 60.0, key=lambda interaction: interaction.user.id)
    async def verify(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = self.bot.home_guild
        if not self.bot.settings.is_set("verified_role"):
            await respond(
                interaction, self.bot.message("verification.not_configured"), ephemeral=True
            )
            return
        role = self.bot.verified_role
        if guild is None or role is None:
            log.error("Verification unavailable: guild or verified role could not be resolved")
            await self.bot.report_failure(
                "Verification is broken",
                "A member ran `/verify`, but the verified role from the settings no longer "
                "exists (or the server is unreachable). Choose the role again with `/config`.",
                dedupe_key="verified-role-missing",
            )
            await respond(
                interaction, self.bot.message("verification.role_missing"), ephemeral=True
            )
            return

        member = await self.bot.fetch_home_member(interaction.user.id)
        if member is None:
            await respond(
                interaction, self.bot.message("verification.not_a_member"), ephemeral=True
            )
            return

        if role in member.roles or member.top_role != guild.default_role:
            await respond(
                interaction, self.bot.message("verification.already_verified"), ephemeral=True
            )
            log.info("Member %s is already verified; request ignored", member.id)
            return

        age_days = account_age_days(member)
        required = self.bot.settings.get("verify_age_days")
        if age_days < required:
            await respond(
                interaction,
                self.bot.message(
                    "verification.too_young", required_days=required, account_age_days=age_days
                ),
                ephemeral=True,
            )
            await self.bot.audit(
                actor_embed(
                    member,
                    title="Verification refused",
                    description=(
                        f"{member.mention} tried to verify but the account is only "
                        f"**{age_days}** days old (minimum {required})."
                    ),
                    colour=FAILURE,
                )
            )
            log.info(
                "Member %s failed verification: account age %d days (< %d)",
                member.id,
                age_days,
                required,
            )
            return

        try:
            await member.add_roles(
                role,
                reason=f"Verified via /verify. Account age: {age_days} days.",
            )
        except discord.Forbidden:
            log.exception("Missing permissions to assign the verified role to %s", member.id)
            await self._report_role_failure(member, role, "`/verify`", permissions=True)
            await respond(interaction, self.bot.message("verification.forbidden"), ephemeral=True)
            return
        except discord.HTTPException:
            log.exception("Failed to assign the verified role to %s", member.id)
            await self._report_role_failure(member, role, "`/verify`", permissions=False)
            await respond(
                interaction, self.bot.message("verification.role_missing"), ephemeral=True
            )
            return

        await respond(interaction, self.bot.message("verification.success"), ephemeral=True)
        await self.bot.audit(
            actor_embed(
                member,
                title="Member verified",
                description=(
                    f"{member.mention} was verified via `/verify` "
                    f"(account age: {age_days} days)."
                ),
                colour=SUCCESS,
            )
        )
        log.info(
            "Member %s verified via /verify; account age %d days", member.id, age_days
        )

    async def _report_role_failure(
        self, member: discord.Member, role: discord.Role, source: str, *, permissions: bool
    ) -> None:
        cause = (
            "the bot lacks the permission. Check that it has **Manage Roles** and that its "
            "own role sits above the verified role."
            if permissions
            else "Discord returned an error."
        )
        await self.bot.report_failure(
            "Could not assign the verified role",
            f"{member.mention} should have been verified ({source}), but {role.mention} "
            f"could not be assigned: {cause} Please give them the role by hand.",
            member=member,
        )

    # -- listeners ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Verify old-enough accounts as they join.

        Discord only sends join events with the Server Members intent, so this
        never runs in reduced mode.
        """
        if member.guild.id != self.bot.config.home_server_id or member.bot:
            return

        threshold = self.bot.settings.get("join_age_days")
        age_days = account_age_days(member)
        if age_days <= threshold:
            return

        if not self.bot.settings.is_set("verified_role"):
            return
        role = self.bot.verified_role
        if role is None:
            log.error("Cannot auto-verify %s: verified role is missing", member.id)
            await self.bot.report_failure(
                "Automatic verification is broken",
                "Members are joining, but the verified role from the settings no longer "
                "exists. Choose the role again with `/config`.",
                dedupe_key="verified-role-missing",
            )
            return

        try:
            await member.add_roles(
                role,
                reason=(
                    f"Auto-verified on join: account age {age_days} days exceeds the "
                    f"{threshold} day threshold."
                ),
            )
        except discord.HTTPException as error:
            log.exception("Failed to auto-verify %s on join", member.id)
            await self._report_role_failure(
                member, role, "automatically on join",
                permissions=isinstance(error, discord.Forbidden),
            )
            return

        await self.bot.audit(
            actor_embed(
                member,
                title="Member auto-verified",
                description=(
                    f"{member.mention} was verified on join because the account is "
                    f"**{age_days}** days old."
                ),
                colour=SUCCESS,
            )
        )
        log.info(
            "Member %s auto-verified on join; account age %d days", member.id, age_days
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Point people who DM the bot at ``/verify``.

        The message body is never inspected, so this works without the
        Message Content intent.
        """
        if message.guild is not None or message.author.bot:
            return

        now = discord.utils.utcnow()
        self._prune_dm_hints(now)
        last_sent = self._dm_hint_sent.get(message.author.id)
        if last_sent is not None and now - last_sent < DM_HINT_COOLDOWN:
            return
        self._dm_hint_sent[message.author.id] = now

        try:
            await message.channel.send(self.bot.message("verification.dm_hint"))
        except discord.HTTPException:
            log.debug("Could not reply to a DM from %s", message.author.id, exc_info=True)

    def _prune_dm_hints(self, now: datetime.datetime) -> None:
        """Forget cooldowns that have run out, at most once per cooldown period."""
        if now - self._dm_hints_pruned_at < DM_HINT_COOLDOWN:
            return
        self._dm_hints_pruned_at = now
        self._dm_hint_sent = {
            user_id: sent
            for user_id, sent in self._dm_hint_sent.items()
            if now - sent < DM_HINT_COOLDOWN
        }


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Verification(bot))
