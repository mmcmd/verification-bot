"""Small helpers shared between cogs."""

from __future__ import annotations

import datetime

import discord

DISCORD_EPOCH_LINK = "https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def account_age(
    user: discord.abc.User, *, now: datetime.datetime | None = None
) -> datetime.timedelta:
    reference = now or discord.utils.utcnow()
    return reference - user.created_at


def account_age_days(user: discord.abc.User, *, now: datetime.datetime | None = None) -> int:
    return account_age(user, now=now).days


def message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return DISCORD_EPOCH_LINK.format(
        guild_id=guild_id, channel_id=channel_id, message_id=message_id
    )


def format_timedelta(delta: datetime.timedelta) -> str:
    """Render a timedelta as ``Xd Yh Zm Ws``, skipping leading zero units."""
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def chunked(items: list, size: int) -> list[list]:
    """Split ``items`` into lists of at most ``size`` elements."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[index : index + size] for index in range(0, len(items), size)]


async def respond(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = False,
    view: discord.ui.View | None = None,
) -> None:
    """Reply to an interaction regardless of whether it was already deferred."""
    kwargs: dict = {"ephemeral": ephemeral}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)
