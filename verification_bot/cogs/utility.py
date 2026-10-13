"""General-purpose utility commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import NEUTRAL, base_embed, stamp_requester
from ..utils import format_timedelta, respond

log = logging.getLogger(__name__)

SOURCE_URL = "https://github.com/mmcmd/verification-bot"
PRIVACY_URL = "https://github.com/mmcmd/verification-bot/blob/master/PRIVACY.md"
AUTHOR_AVATAR = "https://avatars1.githubusercontent.com/u/36875145"

STEVE_EMOJI = (
    "<:steve1:418736567373266955>",
    "<:steve2:418736568145149952>",
    "<:steve3:418736567922851851>",
    "<:steve4:418736568040292352>",
    "<:steve5:418736568057069569>",
)

#: Discord's embed limits.
FIELD_VALUE_LIMIT = 1024
MAX_FIELDS = 25
EMBED_TOTAL_LIMIT = 6000

SECTION_TITLES = {
    checks.Audience.EVERYONE: "Everyone",
    checks.Audience.VERIFIED: "Verified members",
    checks.Audience.MODERATOR: "Moderators",
    checks.Audience.ADMINISTRATOR: "Administrators",
}


def _command_lines(command: app_commands.Command | app_commands.Group) -> list[str]:
    """One ``/name - description`` line per runnable command (groups list their subcommands)."""
    if isinstance(command, app_commands.Group):
        children = [c for c in command.walk_commands() if isinstance(c, app_commands.Command)]
        children.sort(key=lambda c: c.qualified_name)
    else:
        children = [command]
    lines = []
    for child in children:
        line = f"`/{child.qualified_name}` - {child.description}"
        lines.append(line[: FIELD_VALUE_LIMIT - 1])
    return lines


def chunk_lines(lines: list[str], limit: int = FIELD_VALUE_LIMIT) -> list[str]:
    """Join lines into blocks no longer than ``limit``, never splitting a line."""
    blocks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            blocks.append(current)
            current = line
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def build_help_sections(
    commands_: list[app_commands.Command | app_commands.Group],
) -> list[tuple[str, list[str]]]:
    """Sections (title, field texts) in audience order, omitting empty ones."""
    by_audience: dict[checks.Audience, list[str]] = {a: [] for a in SECTION_TITLES}
    for command in sorted(commands_, key=lambda c: c.name):
        by_audience[checks.audience_of(command)].extend(_command_lines(command))
    sections = []
    for audience, title in SECTION_TITLES.items():
        lines = by_audience[audience]
        if lines:
            sections.append((title, chunk_lines(lines)))
    return sections


def build_help_embeds(
    sections: list[tuple[str, list[str]]], intro: str, footer: str
) -> list[discord.Embed]:
    """Pack the sections into as many embeds as the 25-field and 6000-character limits need."""
    embeds: list[discord.Embed] = []
    embed = base_embed(title="Help", description=intro, colour=NEUTRAL)
    size = len("Help") + len(intro) + len(footer)
    for title, blocks in sections:
        for index, block in enumerate(blocks):
            name = title if index == 0 else f"{title} (continued)"
            cost = len(name) + len(block)
            if len(embed.fields) >= MAX_FIELDS or size + cost > EMBED_TOTAL_LIMIT:
                embeds.append(embed)
                embed = base_embed(colour=NEUTRAL)
                size = len(footer)
            embed.add_field(name=name, value=block, inline=False)
            size += cost
    embeds.append(embed)
    embeds[-1].set_footer(text=footer)
    return embeds


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

    @app_commands.command(name="help", description="List the bot's commands.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def help_command(self, interaction: discord.Interaction) -> None:
        sections = build_help_sections(self.bot.all_app_commands())
        embeds = build_help_embeds(
            sections, self.bot.message("help.intro"), self.bot.message("help.footer")
        )
        await respond(interaction, embed=embeds[0], ephemeral=True)
        for extra in embeds[1:]:
            await interaction.followup.send(embed=extra, ephemeral=True)

    @app_commands.command(name="privacy", description="How the bot handles your data.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def privacy(self, interaction: discord.Interaction) -> None:
        text = "\n\n".join(
            (
                self.bot.message("privacy.summary"),
                self.bot.message("privacy.deletion"),
                self.bot.message("privacy.policy", url=PRIVACY_URL),
            )
        )
        await respond(
            interaction, embed=base_embed(title="Privacy", description=text), ephemeral=True
        )

    @app_commands.command(name="steve", description="Summon Steve.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda interaction: interaction.user.id)
    async def steve(self, interaction: discord.Interaction) -> None:
        await respond(interaction, embed=base_embed(description="\n".join(STEVE_EMOJI)))


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Utility(bot))
