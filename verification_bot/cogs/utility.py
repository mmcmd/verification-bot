"""General-purpose utility commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..client import VerificationBot
from ..embeds import NEUTRAL, base_embed, stamp_requester
from ..utils import format_timedelta, respond

log = logging.getLogger(__name__)

SOURCE_URL = "https://github.com/mmcmd/verification-bot"
AUTHOR_AVATAR = "https://avatars1.githubusercontent.com/u/36875145"

STEVE_EMOJI = (
    "<:steve1:418736567373266955>",
    "<:steve2:418736568145149952>",
    "<:steve3:418736567922851851>",
    "<:steve4:418736568040292352>",
    "<:steve5:418736568057069569>",
)


class Utility(commands.Cog):
    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's gateway latency.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def ping(self, interaction: discord.Interaction) -> None:
        embed = base_embed(title=":ping_pong: Pong")
        embed.add_field(name="Gateway latency", value=f"{self.bot.latency * 1000:.0f} ms")
        await respond(interaction, embed=stamp_requester(embed, interaction.user))

    @app_commands.command(name="uptime", description="Show how long the bot has been running.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def uptime(self, interaction: discord.Interaction) -> None:
        elapsed = discord.utils.utcnow() - self.bot.started_at
        embed = base_embed(title="Uptime", colour=NEUTRAL)
        embed.add_field(name="Running for", value=format_timedelta(elapsed))
        embed.add_field(
            name="Online since",
            value=discord.utils.format_dt(self.bot.started_at, "F"),
            inline=False,
        )
        await respond(interaction, embed=stamp_requester(embed, interaction.user))

    @app_commands.command(name="github", description="Link to the bot's source code.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def github(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            title="Source code", description=f"This bot is open source: {SOURCE_URL}"
        )
        embed.set_author(name="github.com/mmcmd", icon_url=AUTHOR_AVATAR, url=SOURCE_URL)
        await respond(interaction, embed=stamp_requester(embed, interaction.user))

    @app_commands.command(name="steve", description="Summon Steve.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def steve(self, interaction: discord.Interaction) -> None:
        await respond(interaction, embed=base_embed(description="\n".join(STEVE_EMOJI)))


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Utility(bot))
