"""Community features: Nitro boost tracking."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..client import VerificationBot
from ..embeds import FAILURE, NEUTRAL, actor_embed, base_embed, stamp_requester
from ..utils import respond

log = logging.getLogger(__name__)

EMBED_DESCRIPTION_LIMIT = 3_800
MAX_BOOSTER_EMBEDS = 8


class Community(commands.Cog):
    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot

    # -- boost tracking ----------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild.id != self.bot.config.home_server_id:
            return
        if before.premium_since == after.premium_since:
            return

        if before.premium_since is None and after.premium_since is not None:
            await self._on_boost(after)
        elif before.premium_since is not None and after.premium_since is None:
            await self._on_unboost(after)

    async def _on_boost(self, member: discord.Member) -> None:
        log.info("Member %s boosted the server", member.id)

        role = self._nitro_role(member.guild)
        if role is not None and role not in member.roles:
            try:
                await member.add_roles(
                    role, reason="User boosted the server; granting the Nitro Booster role."
                )
            except discord.HTTPException:
                log.exception("Failed to grant the Nitro Booster role to %s", member.id)

        try:
            await member.send(self.bot.message("boost.thank_you"))
        except discord.Forbidden:
            log.info("Could not DM member %s a boost thank-you: DMs closed", member.id)
        except discord.HTTPException:
            log.exception("Failed to DM %s a boost thank-you", member.id)

    async def _on_unboost(self, member: discord.Member) -> None:
        log.info("Member %s unboosted the server", member.id)

        channel = self.bot.unboost_channel
        if channel is not None:
            try:
                await channel.send(
                    embed=actor_embed(
                        member,
                        title="Server unboosted",
                        description=f"{member.mention} ({member.id}) unboosted the server.",
                        colour=FAILURE,
                    )
                )
            except discord.HTTPException:
                log.exception("Failed to announce the unboost of %s", member.id)

        revocable = set(self.bot.config.colored_role_ids)
        nitro_role = self._nitro_role(member.guild)
        if nitro_role is not None:
            revocable.add(nitro_role.id)

        # Members may have self-removed the booster role, so only strip what they hold.
        roles = [role for role in member.roles if role.id in revocable]
        if not roles:
            return
        try:
            await member.remove_roles(
                *roles, reason="User unboosted the server; booster roles removed."
            )
        except discord.HTTPException:
            log.exception("Failed to remove booster roles from %s", member.id)

    def _nitro_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = self.bot.config.nitro_role_id
        if role_id is None:
            return None
        role = guild.get_role(role_id)
        if role is None:
            log.error("Nitro Booster role %s is missing from the guild", role_id)
        return role

    # -- commands ----------------------------------------------------------

    @app_commands.command(
        name="boosters", description="List everyone currently boosting the server."
    )
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 15.0, key=lambda interaction: interaction.channel_id)
    async def boosters(self, interaction: discord.Interaction) -> None:
        guild = self.bot.home_guild
        if guild is None:
            await respond(interaction, "The server is not available right now.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        boosters = sorted(
            guild.premium_subscribers,
            key=lambda member: member.premium_since or discord.utils.utcnow(),
        )
        header = (
            f"**{guild.premium_subscription_count}** boost(s) from **{len(boosters)}** member(s). "
            f"Current tier: **{guild.premium_tier}**."
        )

        if not boosters:
            embed = base_embed(title="Server boosters", description=header, colour=NEUTRAL)
            await respond(interaction, embed=stamp_requester(embed, interaction.user))
            return

        lines = [
            f"{index}. {member.mention} — boosting since "
            f"{discord.utils.format_dt(member.premium_since, 'D')}"
            for index, member in enumerate(boosters, start=1)
            if member.premium_since is not None
        ]

        for page, chunk in enumerate(self._paginate(lines)):
            embed = base_embed(
                title="Server boosters" if page == 0 else None,
                description=(header + "\n\n" if page == 0 else "") + "\n".join(chunk),
                colour=NEUTRAL,
            )
            if guild.icon is not None:
                embed.set_thumbnail(url=guild.icon.url)
            stamp_requester(embed, interaction.user)
            await interaction.followup.send(embed=embed)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _paginate(lines: list[str]) -> list[list[str]]:
        pages: list[list[str]] = []
        current: list[str] = []
        length = 0
        for line in lines:
            if current and length + len(line) + 1 > EMBED_DESCRIPTION_LIMIT:
                pages.append(current)
                if len(pages) == MAX_BOOSTER_EMBEDS:
                    return pages
                current, length = [], 0
            current.append(line)
            length += len(line) + 1
        if current:
            pages.append(current)
        return pages


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Community(bot))
