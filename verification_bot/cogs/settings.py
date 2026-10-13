"""The ``/config`` command: administrators change the bot's settings from Discord.

Every value is chosen with one of Discord's pickers (a role, a channel, a
member), so nobody has to copy an ID. Every change goes through
``bot.change_setting``, which checks the value, saves the settings file, applies
the change at once and records who changed what in the mod-log channel.
"""

from __future__ import annotations

import logging
from typing import Any, Union

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import FAILURE, SUCCESS, base_embed
from ..settings import (
    SETTINGS,
    STATUS_TEXT_MAX_LENGTH,
    SettingKind,
    SettingsError,
    SettingSpec,
    format_value,
    normalise,
)

log = logging.getLogger(__name__)

#: Roles the bot hands out or takes away itself. Discord only lets a bot do that
#: with ordinary roles that sit below the bot's own highest role.
ASSIGNED_ROLE_SETTINGS = frozenset({"verified_role", "booster_role", "colour_roles"})

#: Which subcommand sets each kind of setting; used in hints to the administrator.
SET_COMMANDS: dict[SettingKind, str] = {
    SettingKind.ROLE: "/config role",
    SettingKind.ROLE_LIST: "/config role-add",
    SettingKind.CHANNEL: "/config channel",
    SettingKind.CATEGORY: "/config category",
    SettingKind.USER: "/config user",
    SettingKind.INTEGER: "/config number",
    SettingKind.TEXT: "/config status",
}

# Discord's limits, with some room to spare.
CHOICE_NAME_LIMIT = 100
MESSAGE_LIMIT = 2_000
PAGE_LIMIT = 3_800  # an embed description may hold 4096 characters
BLOCK_LIMIT = 1_000  # one setting never takes more than this much of a page
MAX_PAGES = 10
MAX_LISTED_ROLES = 20
MAX_LISTED_PROBLEM_IDS = 10

NO_PINGS = discord.AllowedMentions.none()


def _specs(*kinds: SettingKind) -> list[SettingSpec]:
    return [spec for spec in SETTINGS.values() if not kinds or spec.kind in kinds]


def _range_text(spec: SettingSpec) -> str:
    if spec.minimum is not None and spec.maximum is not None:
        return f"{spec.minimum} to {spec.maximum}"
    if spec.minimum is not None:
        return f"{spec.minimum} or more"
    if spec.maximum is not None:
        return f"{spec.maximum} or less"
    return "any whole number"


def _choices(*kinds: SettingKind) -> list[app_commands.Choice[str]]:
    """The settings of the given kinds as a pick-list, built from ``SETTINGS``."""
    choices = []
    for spec in _specs(*kinds):
        name = spec.label
        if kinds == (SettingKind.INTEGER,):
            name = f"{name} [{_range_text(spec)}]"
        choices.append(app_commands.Choice(name=name[:CHOICE_NAME_LIMIT], value=spec.key))
    return choices


def _number_bounds() -> tuple[int, int]:
    """The widest range any number setting allows.

    One ``value`` option serves every number setting, so Discord can only
    enforce the widest range; the settings store enforces each setting's own.
    """
    numbers = _specs(SettingKind.INTEGER)
    lows = [spec.minimum for spec in numbers]
    highs = [spec.maximum for spec in numbers]
    safe = 2**53 - 1  # the largest whole number Discord accepts in an option
    low = -safe if not lows or None in lows else min(lows)
    high = safe if not highs or None in highs else max(highs)
    return low, high


NUMBER_MIN, NUMBER_MAX = _number_bounds()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _id_list(ids: list[int]) -> str:
    shown = ", ".join(f"`{item}`" for item in ids[:MAX_LISTED_PROBLEM_IDS])
    extra = len(ids) - MAX_LISTED_PROBLEM_IDS
    return f"{shown} and {extra} more" if extra > 0 else shown


def _role_refusal(spec: SettingSpec, role: discord.Role) -> str | None:
    """Why ``role`` cannot be stored in ``spec``, or ``None`` when it can."""
    if role.is_default():
        return (
            "`@everyone` cannot be used here. It is not a real role: every member has it, "
            "so it would apply to the whole server."
        )
    if spec.key in ASSIGNED_ROLE_SETTINGS and role.managed:
        return (
            f"{role.mention} is managed by Discord or by another bot, so this bot cannot "
            "give it to members or take it away. Choose an ordinary role instead."
        )
    return None


def _role_position_problem(
    spec: SettingSpec, role: discord.Role, guild: discord.Guild | None
) -> str | None:
    """A sentence when the bot cannot hand out ``role`` because of the role order."""
    if spec.key not in ASSIGNED_ROLE_SETTINGS or guild is None:
        return None
    me = guild.me
    if me is None:
        return None
    if me.top_role <= role:
        return (
            f"the bot cannot give or remove {role.mention} yet, because that role is not "
            "below the bot's own highest role. In Server Settings > Roles, drag the bot's "
            "role above it."
        )
    return None


def _mod_log_problem(channel: Any, guild: discord.Guild | None) -> str | None:
    """A sentence when the bot cannot post in the mod-log channel."""
    me = guild.me if guild is not None else None
    if me is None:
        return None
    permissions = channel.permissions_for(me)
    missing = [
        name
        for name, allowed in (
            ("View Channel", permissions.view_channel),
            ("Send Messages", permissions.send_messages),
            ("Embed Links", permissions.embed_links),
        )
        if not allowed
    ]
    if not missing:
        return None
    return (
        f"the bot cannot post in {channel.mention}: it is missing {', '.join(missing)} "
        "there. Until that is fixed, nothing is recorded in the mod-log."
    )


def _inspect(
    spec: SettingSpec, value: Any, guild: discord.Guild | None
) -> tuple[str, list[str]]:
    """How a setting's value is shown in ``/config show``, and what is wrong with it."""
    problems: list[str] = []
    command = SET_COMMANDS[spec.kind]

    if spec.kind is SettingKind.ROLE_LIST:
        if not value:
            return "*none chosen*", problems
        shown = ", ".join(f"<@&{role_id}>" for role_id in value[:MAX_LISTED_ROLES])
        if len(value) > MAX_LISTED_ROLES:
            shown += f" and {len(value) - MAX_LISTED_ROLES} more"
        if guild is None:
            return shown, problems
        missing = [role_id for role_id in value if guild.get_role(role_id) is None]
        if missing:
            problems.append(
                f"{len(missing)} of these roles no longer exist{'s' if len(missing) == 1 else ''} "
                f"in this server: {_id_list(missing)}. Run `/config role-prune` to drop "
                "them from the list."
            )
        blocked = []
        for role_id in value:
            role = guild.get_role(role_id)
            if role is not None and _role_position_problem(spec, role, guild):
                blocked.append(role_id)
        if blocked:
            problems.append(
                f"the bot cannot give or remove {len(blocked)} of these roles, because "
                "they are not below the bot's own highest role: "
                + ", ".join(f"<@&{role_id}>" for role_id in blocked[:MAX_LISTED_PROBLEM_IDS])
                + ". In Server Settings > Roles, drag the bot's role above them."
            )
        return shown, problems

    if spec.kind in (SettingKind.INTEGER, SettingKind.TEXT):
        return format_value(spec, value), problems

    if value is None:
        problems.append(
            f"nothing has been chosen yet, so the part of the bot that uses it does not "
            f"work. Choose one with `{command}`."
        )
        return format_value(spec, value), problems

    shown = format_value(spec, value)
    if spec.kind is SettingKind.USER or guild is None:
        # A user is not looked up: that would need a request to Discord.
        return shown, problems

    if spec.kind is SettingKind.ROLE:
        role = guild.get_role(value)
        if role is None:
            problems.append(
                f"the role with ID `{value}` does not exist in this server (it was deleted, "
                f"or it belongs to another server). Choose a new one with `{command}`."
            )
        else:
            position = _role_position_problem(spec, role, guild)
            if position:
                problems.append(position)
        return shown, problems

    channel = guild.get_channel_or_thread(value)
    if spec.kind is SettingKind.CATEGORY:
        if channel is None:
            problems.append(
                f"the category with ID `{value}` does not exist in this server (it was "
                f"deleted, or it belongs to another server). Choose a new one with `{command}`."
            )
        elif not isinstance(channel, discord.CategoryChannel):
            problems.append(
                f"{shown} is not a channel category. Choose a category with `{command}`."
            )
        return shown, problems

    if channel is None:
        problems.append(
            f"ID `{value}` is not a channel in this server (the channel was deleted, belongs "
            f"to another server, or the ID is not a channel at all). Choose a new one with "
            f"`{command}`."
        )
    elif not isinstance(channel, (discord.TextChannel, discord.Thread)):
        problems.append(
            f"{shown} is not a text channel, so the bot cannot post there. Choose a text "
            f"channel with `{command}`."
        )
    elif spec.key == "mod_log_channel":
        permission = _mod_log_problem(channel, guild)
        if permission:
            problems.append(permission)
    return shown, problems


def _block(spec: SettingSpec, shown: str, problems: list[str]) -> str:
    lines = [f"**{spec.label}:** {shown}"]
    lines.extend(f"**Needs attention:** {problem}" for problem in problems)
    lines.append(f"*{spec.description}*")
    return _clip("\n".join(lines), BLOCK_LIMIT)


def _pages(blocks: list[str]) -> list[str]:
    """Pack the per-setting blocks into as few embed descriptions as possible."""
    pages: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > PAGE_LIMIT and current:
            pages.append(current)
            current = block
        else:
            current = candidate
    if current:
        pages.append(current)
    if len(pages) > MAX_PAGES:
        pages = pages[:MAX_PAGES]
        pages[-1] = _clip(pages[-1], PAGE_LIMIT - 60) + "\n\n*The list was cut off here.*"
    return pages


class Settings(commands.Cog):
    """``/config``: look at the bot's settings and change them."""

    def __init__(self, bot: VerificationBot) -> None:
        self.bot = bot

    # Discord hides the command from members without Administrator. That is a
    # convenience only (a server can override it under Integrations); the real
    # protection is the administrator check on every subcommand below.
    config = app_commands.Group(
        name="config",
        description="Look at the bot's settings and change them (administrators only).",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """A second lock on the whole cog, in case a subcommand ever lacks its check."""
        if not checks.is_administrator(interaction):
            raise checks.MissingAdministrator("Only administrators can use this command.")
        return True

    # -- helpers -----------------------------------------------------------

    async def _reply(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.followup.send(
            content=_clip(text, MESSAGE_LIMIT), ephemeral=True, allowed_mentions=NO_PINGS
        )

    async def _spec(
        self, interaction: discord.Interaction, key: str, *kinds: SettingKind
    ) -> SettingSpec | None:
        """The setting ``key``, if it exists and is one of ``kinds``."""
        spec = SETTINGS.get(key)
        if spec is None or (kinds and spec.kind not in kinds):
            await self._reply(
                interaction,
                "That setting cannot be changed with this command. Pick one from the list "
                "that appears while you type the command. Nothing was changed.",
            )
            return None
        return spec

    async def _apply(
        self,
        interaction: discord.Interaction,
        spec: SettingSpec,
        value: Any,
        *,
        notes: tuple[str, ...] = (),
    ) -> bool:
        """Store ``value`` (``None`` clears) and tell the administrator what happened."""
        bot = self.bot
        before = bot.settings.get(spec.key)

        if value is not None:
            try:
                unchanged = normalise(spec, value) == before
            except SettingsError:
                unchanged = False  # change_setting reports the reason below
            if unchanged:
                await self._reply(
                    interaction,
                    f"**{spec.label}** is already {format_value(spec, before)}. "
                    "Nothing was changed.",
                )
                return False

        try:
            after = await bot.change_setting(spec.key, value, actor=interaction.user)
        except SettingsError as error:
            text = f"Nothing was changed. {error}"
            if spec.kind is SettingKind.INTEGER:
                text += f" Allowed for this setting: {_range_text(spec)}."
            await self._reply(interaction, text)
            return False
        except OSError:
            log.exception("Could not write the settings file")
            await self._reply(
                interaction,
                "Nothing was changed: the bot could not write its settings file. Check on "
                "the server that the bot is allowed to write to its `data` folder and that "
                "the disk is not full, then try again.",
            )
            return False

        lines = [
            f"**{spec.label}** was changed.",
            f"**Before:** {format_value(spec, before)}",
            f"**After:** {format_value(spec, after)}",
            f"*{spec.description}*",
        ]
        lines.extend(f"**Note:** {note}" for note in notes)
        if bot.log_channel is None:
            lines.append(
                "**Note:** this change could not be recorded in the mod-log, because the "
                "mod-log channel is not set or cannot be reached. Set it with "
                "`/config channel`."
            )
        else:
            lines.append("The change takes effect now and was recorded in the mod-log.")
        await self._reply(interaction, "\n".join(lines))
        return True

    # -- /config show ------------------------------------------------------

    @config.command(
        name="show", description="List every setting and point out any that need fixing."
    )
    @checks.administrator_only()
    async def show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        bot = self.bot
        guild = interaction.guild

        blocks: list[str] = []
        flagged = 0
        for spec in SETTINGS.values():
            shown, problems = _inspect(spec, bot.settings.get(spec.key), guild)
            flagged += bool(problems)
            blocks.append(_block(spec, shown, problems))

        if flagged == 0:
            summary = "**All settings look good.**"
        elif flagged == 1:
            summary = "**1 setting needs attention.** Look for \"Needs attention\" below."
        else:
            summary = (
                f"**{flagged} settings need attention.** Look for \"Needs attention\" below."
            )
        if guild is None:
            summary += (
                "\nThe bot could not see the server just now, so it did not check whether "
                "the roles and channels still exist."
            )
        if bot.reduced_mode:
            mode = (
                "**Mode: reduced.** Discord has not allowed the bot to see members joining "
                "and boosting (the Server Members intent), so automatic verification on "
                "join, boost tracking and `/boosters` are off. Every command still works."
            )
        else:
            mode = (
                "**Mode: full.** Discord allows the bot to see members joining and "
                "boosting, so every feature is on."
            )
        header = f"{summary}\n{mode}\nChange a setting with the other `/config` commands."

        pages = _pages(blocks)
        colour = SUCCESS if flagged == 0 else FAILURE
        for index, page in enumerate(pages):
            title = "Bot settings"
            if len(pages) > 1:
                title += f" ({index + 1} of {len(pages)})"
            embed = base_embed(title=title, description=page, colour=colour)
            # One embed per message keeps every message far below Discord's limit
            # of 6000 characters across all embeds of a message.
            await interaction.followup.send(
                content=header if index == 0 else None,
                embed=embed,
                ephemeral=True,
                allowed_mentions=NO_PINGS,
            )

    # -- single values -----------------------------------------------------

    @config.command(name="role", description="Choose the role for a setting that holds one role.")
    @app_commands.describe(setting="Which setting to change.", role="The role to use.")
    @app_commands.choices(setting=_choices(SettingKind.ROLE))
    @checks.administrator_only()
    async def role(
        self, interaction: discord.Interaction, setting: str, role: discord.Role
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.ROLE)
        if spec is None:
            return
        refusal = _role_refusal(spec, role)
        if refusal:
            await self._reply(interaction, f"Nothing was changed. {refusal}")
            return
        warning = _role_position_problem(spec, role, interaction.guild)
        await self._apply(interaction, spec, role.id, notes=(warning,) if warning else ())

    @config.command(
        name="channel", description="Choose the text channel for a setting that holds a channel."
    )
    @app_commands.describe(setting="Which setting to change.", channel="The text channel to use.")
    @app_commands.choices(setting=_choices(SettingKind.CHANNEL))
    @checks.administrator_only()
    async def channel(
        self, interaction: discord.Interaction, setting: str, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.CHANNEL)
        if spec is None:
            return
        warning = None
        if spec.key == "mod_log_channel":
            warning = _mod_log_problem(channel, interaction.guild)
        await self._apply(interaction, spec, channel.id, notes=(warning,) if warning else ())

    @config.command(
        name="category", description="Choose the channel category for a setting that holds one."
    )
    @app_commands.describe(setting="Which setting to change.", category="The category to use.")
    @app_commands.choices(setting=_choices(SettingKind.CATEGORY))
    @checks.administrator_only()
    async def category(
        self, interaction: discord.Interaction, setting: str, category: discord.CategoryChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.CATEGORY)
        if spec is None:
            return
        await self._apply(interaction, spec, category.id)

    @config.command(name="user", description="Choose the user for a setting that holds a user.")
    @app_commands.describe(setting="Which setting to change.", user="The user or bot to use.")
    @app_commands.choices(setting=_choices(SettingKind.USER))
    @checks.administrator_only()
    async def user(
        self,
        interaction: discord.Interaction,
        setting: str,
        user: Union[discord.Member, discord.User],  # noqa: UP007 - evaluated by discord.py
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.USER)
        if spec is None:
            return
        await self._apply(interaction, spec, user.id)

    @config.command(
        name="number", description="Change a number, such as an age limit or a vote count."
    )
    @app_commands.describe(
        setting="Which number to change. The allowed range is shown in brackets.",
        value="The new number. Each setting has its own allowed range, shown next to its name.",
    )
    @app_commands.choices(setting=_choices(SettingKind.INTEGER))
    @checks.administrator_only()
    async def number(
        self,
        interaction: discord.Interaction,
        setting: str,
        value: app_commands.Range[int, NUMBER_MIN, NUMBER_MAX],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.INTEGER)
        if spec is None:
            return
        await self._apply(interaction, spec, value)

    @config.command(
        name="status", description="Change the \"Playing ...\" text shown under the bot's name."
    )
    @app_commands.describe(text=f"The new text, at most {STATUS_TEXT_MAX_LENGTH} characters.")
    @checks.administrator_only()
    async def status(
        self,
        interaction: discord.Interaction,
        text: app_commands.Range[str, 1, STATUS_TEXT_MAX_LENGTH],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._apply(interaction, SETTINGS["status_text"], text)

    # -- role lists --------------------------------------------------------

    @config.command(
        name="role-add", description="Add a role to a setting that holds a list of roles."
    )
    @app_commands.describe(setting="Which list to add to.", role="The role to add.")
    @app_commands.choices(setting=_choices(SettingKind.ROLE_LIST))
    @checks.administrator_only()
    async def role_add(
        self, interaction: discord.Interaction, setting: str, role: discord.Role
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.ROLE_LIST)
        if spec is None:
            return
        refusal = _role_refusal(spec, role)
        if refusal:
            await self._reply(interaction, f"Nothing was changed. {refusal}")
            return
        current: tuple[int, ...] = self.bot.settings.get(spec.key)
        if role.id in current:
            await self._reply(
                interaction,
                f"{role.mention} is already in **{spec.label}**. Nothing was changed.",
            )
            return
        warning = _role_position_problem(spec, role, interaction.guild)
        await self._apply(
            interaction, spec, (*current, role.id), notes=(warning,) if warning else ()
        )

    @config.command(
        name="role-remove", description="Take a role out of a setting that holds a list of roles."
    )
    @app_commands.describe(setting="Which list to remove from.", role="The role to remove.")
    @app_commands.choices(setting=_choices(SettingKind.ROLE_LIST))
    @checks.administrator_only()
    async def role_remove(
        self, interaction: discord.Interaction, setting: str, role: discord.Role
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.ROLE_LIST)
        if spec is None:
            return
        current: tuple[int, ...] = self.bot.settings.get(spec.key)
        if role.id not in current:
            await self._reply(
                interaction, f"{role.mention} is not in **{spec.label}**. Nothing was changed."
            )
            return
        remaining = tuple(role_id for role_id in current if role_id != role.id)
        # ``None`` clears the setting; an empty list means the same thing.
        await self._apply(interaction, spec, remaining or None)

    @config.command(
        name="role-prune",
        description="Drop roles that were deleted from the server out of a list of roles.",
    )
    @app_commands.describe(setting="Which list to tidy up.")
    @app_commands.choices(setting=_choices(SettingKind.ROLE_LIST))
    @checks.administrator_only()
    async def role_prune(self, interaction: discord.Interaction, setting: str) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting, SettingKind.ROLE_LIST)
        if spec is None:
            return
        guild = interaction.guild
        # Without the server's role list every role would look deleted.
        if guild is None or len(guild.roles) <= 1:
            await self._reply(
                interaction,
                "Nothing was changed: the bot cannot see the server's roles right now, so "
                "it cannot tell which ones were deleted. Try again in a minute.",
            )
            return
        current: tuple[int, ...] = self.bot.settings.get(spec.key)
        remaining = tuple(role_id for role_id in current if guild.get_role(role_id) is not None)
        if remaining == current:
            await self._reply(
                interaction,
                f"Every role in **{spec.label}** still exists. Nothing was changed.",
            )
            return
        dropped = len(current) - len(remaining)
        await self._apply(
            interaction,
            spec,
            remaining or None,
            notes=(f"{dropped} deleted role{'' if dropped == 1 else 's'} dropped from the list.",),
        )

    # -- clearing ----------------------------------------------------------

    @config.command(
        name="clear", description="Unset a setting, so it goes back to its default (or to nothing)."
    )
    @app_commands.describe(setting="Which setting to unset.")
    @app_commands.choices(setting=_choices())
    @checks.administrator_only()
    async def clear(self, interaction: discord.Interaction, setting: str) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = await self._spec(interaction, setting)
        if spec is None:
            return
        if not self.bot.settings.is_set(spec.key):
            current = format_value(spec, self.bot.settings.get(spec.key))
            await self._reply(
                interaction,
                f"**{spec.label}** has no value of its own (it is {current}). "
                "Nothing was changed.",
            )
            return
        note = None
        if spec.default not in (None, ()):
            note = f"It is back to its default, {format_value(spec, spec.default)}."
        await self._apply(interaction, spec, None, notes=(note,) if note else ())


async def setup(bot: VerificationBot) -> None:
    await bot.add_cog(Settings(bot))
