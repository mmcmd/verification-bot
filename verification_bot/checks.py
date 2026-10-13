"""Reusable application-command checks and small permission helpers.

The predicates read the settings from ``interaction.client`` at call time, so a
change made with ``/config`` applies to the very next command.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable

import discord
from discord import app_commands


class Audience(enum.IntEnum):
    """Who a command is meant for, from least to most privileged."""

    EVERYONE = 0
    VERIFIED = 1
    MODERATOR = 2
    ADMINISTRATOR = 3


class MissingModeratorRole(app_commands.CheckFailure):
    """Raised when a moderator-only command is used by a non-moderator."""


class MissingAdministrator(app_commands.CheckFailure):
    """Raised when an administrator-only command is used by anyone else."""


class MissingVerifiedRole(app_commands.CheckFailure):
    """Raised when a command requires the verified role."""


class SettingNotConfigured(app_commands.CheckFailure):
    """Raised when a command depends on a setting nobody has filled in yet."""

    def __init__(self, label: str) -> None:
        super().__init__(
            f"This command is not set up yet: the {label} has not been chosen. "
            "An administrator has to run `/config`."
        )
        self.label = label


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


def _settings(interaction: discord.Interaction):
    return interaction.client.settings  # type: ignore[attr-defined]


def _home_server_id(interaction: discord.Interaction) -> int:
    return interaction.client.config.home_server_id  # type: ignore[attr-defined]


def is_moderator(interaction: discord.Interaction) -> bool:
    """True for administrators and holders of a moderator role, in the home server."""
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return has_any_role_id(member, _settings(interaction).get("moderator_roles"))


def is_administrator(interaction: discord.Interaction) -> bool:
    """True for members with the Administrator permission in the home server."""
    member = interaction.user
    return (
        isinstance(member, discord.Member)
        and interaction.guild_id == _home_server_id(interaction)
        and member.guild_permissions.administrator
    )


def moderator_only():
    """Limit a command to the moderator roles from the settings (or administrators)."""

    def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            raise MissingModeratorRole("This command can only be used inside the server.")
        if is_moderator(interaction):
            return True
        raise MissingModeratorRole("You do not have permission to use this command.")

    predicate.audience = Audience.MODERATOR  # type: ignore[attr-defined]
    return app_commands.check(predicate)


def administrator_only():
    """Limit a command to administrators, and to the home server."""

    def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or (
            interaction.guild_id != _home_server_id(interaction)
        ):
            raise MissingAdministrator("This command can only be used inside the server.")
        if is_administrator(interaction):
            return True
        raise MissingAdministrator("Only administrators can use this command.")

    predicate.audience = Audience.ADMINISTRATOR  # type: ignore[attr-defined]
    return app_commands.check(predicate)


def verified_only():
    """Limit a command to members who have completed verification."""

    def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            raise MissingVerifiedRole("This command can only be used inside the server.")
        verified_role_id = _settings(interaction).get("verified_role")
        if verified_role_id is None:
            raise SettingNotConfigured("verified role")
        if has_any_role_id(member, (verified_role_id,)):
            return True
        raise MissingVerifiedRole("You must be verified before you can use this command.")

    predicate.audience = Audience.VERIFIED  # type: ignore[attr-defined]
    return app_commands.check(predicate)


def ontopic_only():
    """Limit a command to channels inside the on-topic category from the settings."""

    def predicate(interaction: discord.Interaction) -> bool:
        category_id = _settings(interaction).get("ontopic_category")
        if category_id is None:
            raise SettingNotConfigured("on-topic category")
        channel = interaction.channel
        if channel is None or isinstance(channel, (discord.DMChannel, discord.GroupChannel)):
            raise WrongCategory(category_id)
        if in_category(channel, category_id):
            return True
        raise WrongCategory(category_id)

    return app_commands.check(predicate)


def audience_of(command: app_commands.Command | app_commands.Group) -> Audience:
    """Who may use a command, worked out from the checks attached to it.

    ``/help`` uses this to sort commands into sections, so the help text follows
    the real permission checks and cannot drift from them. A command group
    belongs to the least privileged audience among its subcommands.
    """
    if isinstance(command, app_commands.Group):
        audiences = [
            audience_of(child)
            for child in command.walk_commands()
            if isinstance(child, app_commands.Command)
        ]
        return min(audiences) if audiences else Audience.EVERYONE
    return max(
        (getattr(check, "audience", Audience.EVERYONE) for check in command.checks),
        default=Audience.EVERYONE,
    )
