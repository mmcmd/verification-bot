"""Shared embed helpers so every response in the bot looks consistent."""

from __future__ import annotations

import random

import discord

ACCENT_COLOURS: tuple[discord.Colour, ...] = (
    discord.Colour.purple(),
    discord.Colour.blue(),
    discord.Colour.red(),
    discord.Colour.green(),
    discord.Colour.orange(),
)

SUCCESS = discord.Colour.green()
FAILURE = discord.Colour.red()
NEUTRAL = discord.Colour.blurple()


def random_colour() -> discord.Colour:
    return random.choice(ACCENT_COLOURS)


def base_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    colour: discord.Colour | None = None,
) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        colour=colour if colour is not None else random_colour(),
        timestamp=discord.utils.utcnow(),
    )


def actor_embed(
    actor: discord.abc.User,
    *,
    title: str | None = None,
    description: str | None = None,
    colour: discord.Colour | None = None,
) -> discord.Embed:
    """An embed whose author block identifies the user the entry is about."""
    embed = base_embed(title=title, description=description, colour=colour)
    embed.set_author(name=f"{actor} ({actor.id})", icon_url=actor.display_avatar.url)
    return embed


def stamp_requester(embed: discord.Embed, requester: discord.abc.User) -> discord.Embed:
    embed.set_footer(text=f"Requested by {requester}", icon_url=requester.display_avatar.url)
    return embed
