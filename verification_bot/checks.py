"""Reusable application-command checks and small permission helpers.

The predicates read configuration from ``interaction.client`` at call time so
that decorators do not need the config object at import time.
"""

from __future__ import annotations

from collections.abc import Iterable

import discord
from discord import app_commands


class MissingModeratorRole(app_commands.CheckFailure):
    """Raised when a moderator-only command is used by a non-moderator."""


class MissingVerifiedRole(app_commands.CheckFailure):
    """Raised when a command requires the verified role."""


class WrongCategory(app_commands.CheckFailure):
    """Raised when a command is used outside of its permitted category."""

    def __init__(self, category_id: int) -> None:
        super().__init__("This command can only be used in the on-topic category.")
        self.category_id = category_id


def has_any_role_id(member: discord.Member, role_ids: Iterable[int]) -> bool:
    wanted = set(role_ids)
    return any(role.id in wanted for role in member.roles)


def outranks_role(member: discord.Member, role: discord.Role | None) -> bool:
    """True when the member's highest role sits strictly above ``role``."""
    if role is None:
        return False
    return member.top_role > role


def in_category(channel: discord.abc.GuildChannel | discord.Thread, category_id: int) -> bool:
    category = getattr(channel, "category", None)
    return category is not None and category.id == category_id


def _config(interaction: discord.Interaction):
    return interaction.client.config  # type: ignore[attr-defined]


def moderator_only():
    """Limit a command to the configured moderator roles (or administrators)."""

    def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            raise MissingModeratorRole("This command can only be used inside the server.")
        if member.guild_permissions.administrator:
            return True
        if has_any_role_id(member, _config(interaction).moderator_role_ids):
            return True
        raise MissingModeratorRole("You do not have permission to use this command.")

    return app_commands.check(predicate)


def verified_only():
    """Limit a command to members who have completed verification."""

    def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            raise MissingVerifiedRole("This command can only be used inside the server.")
        if has_any_role_id(member, (_config(interaction).verified_role_id,)):
            return True
        raise MissingVerifiedRole("You must be verified before you can use this command.")

    return app_commands.check(predicate)


def ontopic_only():
    """Limit a command to channels inside the configured on-topic category."""

    def predicate(interaction: discord.Interaction) -> bool:
        category_id = _config(interaction).ontopic_category_id
        channel = interaction.channel
        if channel is None or isinstance(channel, (discord.DMChannel, discord.GroupChannel)):
            raise WrongCategory(category_id)
        if in_category(channel, category_id):
            return True
        raise WrongCategory(category_id)

    return app_commands.check(predicate)
