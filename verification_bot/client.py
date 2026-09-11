"""The bot client, command tree and startup wiring."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from . import checks
from .config import BotConfig
from .utils import respond

log = logging.getLogger(__name__)

EXTENSIONS: tuple[str, ...] = (
    "verification_bot.cogs.verification",
    "verification_bot.cogs.emergency",
    "verification_bot.cogs.community",
    "verification_bot.cogs.utility",
    "verification_bot.cogs.infrastructure",
)

#: Commands that must stay global so members can run them from their DMs.
GLOBAL_COMMANDS: frozenset[str] = frozenset({"verify"})

#: When set, the bot touches this file while connected so a container healthcheck
#: can distinguish a live gateway session from a hung process.
HEARTBEAT_ENV_VAR = "HEARTBEAT_FILE"
HEARTBEAT_INTERVAL_SECONDS = 30


def build_intents() -> discord.Intents:
    """The minimum set of gateway intents the bot actually needs.

    ``members`` is the only privileged intent requested: it powers join-time
    verification and Nitro boost tracking. Message Content and Presence are
    deliberately left disabled.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.dm_messages = True
    return intents


class VerificationCommandTree(app_commands.CommandTree):
    """Command tree with a single, user-friendly error handler."""

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        command = interaction.command.qualified_name if interaction.command else "unknown"

        if isinstance(error, app_commands.CommandOnCooldown):
            await respond(
                interaction,
                f"That command is on cooldown. Try again in {error.retry_after:.0f} seconds.",
                ephemeral=True,
            )
            return

        if isinstance(error, checks.WrongCategory):
            await respond(
                interaction,
                "This command can only be used in channels under "
                f"<#{error.category_id}>'s category.",
                ephemeral=True,
            )
            return

        if isinstance(error, (checks.MissingModeratorRole, checks.MissingVerifiedRole,
                              app_commands.MissingAnyRole, app_commands.MissingRole,
                              app_commands.MissingPermissions)):
            await respond(
                interaction,
                str(error) or "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        if isinstance(error, app_commands.NoPrivateMessage):
            await respond(interaction, "This command can only be used in a server.", ephemeral=True)
            return

        if isinstance(error, app_commands.CheckFailure):
            await respond(interaction, str(error) or "You cannot use this command here.",
                          ephemeral=True)
            return

        log.exception("Unhandled error in /%s", command, exc_info=error)
        await respond(
            interaction,
            "Something went wrong while running that command. The moderators have been notified.",
            ephemeral=True,
        )


class VerificationBot(commands.Bot):
    """Application-command bot for the /r/sysadmin server."""

    def __init__(self, config: BotConfig, messages: dict[str, Any]) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            help_command=None,
            intents=build_intents(),
            activity=discord.Activity(type=discord.ActivityType.playing, name=config.status),
            allowed_mentions=discord.AllowedMentions(
                everyone=False, users=True, roles=True, replied_user=True
            ),
            tree_cls=VerificationCommandTree,
            max_messages=None,
            chunk_guilds_at_startup=False,
        )
        self.config = config
        self.messages = messages
        self.started_at = discord.utils.utcnow()
        heartbeat_file = os.environ.get(HEARTBEAT_ENV_VAR)
        self.heartbeat_path = Path(heartbeat_file) if heartbeat_file else None

    # -- lifecycle ---------------------------------------------------------

    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
            except commands.ExtensionError:
                log.exception("Failed to load extension %s", extension)
                raise
            log.info("Loaded extension %s", extension)

        await self._sync_commands()

        if self.heartbeat_path is not None:
            self.heartbeat.start()

    async def close(self) -> None:
        if self.heartbeat.is_running():
            self.heartbeat.cancel()
        await super().close()

    @tasks.loop(seconds=HEARTBEAT_INTERVAL_SECONDS)
    async def heartbeat(self) -> None:
        if self.heartbeat_path is None or self.is_closed() or not self.is_ready():
            return
        try:
            self.heartbeat_path.write_text(str(int(discord.utils.utcnow().timestamp())))
        except OSError:
            log.warning("Could not write the heartbeat file", exc_info=True)

    async def _sync_commands(self) -> None:
        """Register guild commands instantly and keep DM-capable ones global."""
        guild = discord.Object(id=self.config.home_server_id)

        for command in list(self.tree.get_commands()):
            if command.name in GLOBAL_COMMANDS:
                continue
            self.tree.remove_command(command.name)
            self.tree.add_command(command, guild=guild)

        guild_commands = await self.tree.sync(guild=guild)
        global_commands = await self.tree.sync()
        log.info(
            "Synced %d guild command(s) and %d global command(s)",
            len(guild_commands),
            len(global_commands),
        )

    # -- message templates -------------------------------------------------

    def message(self, path: str, **params: Any) -> str:
        """Look up a dotted template path in ``resources/messages.json``.

        ``moderator_mail_id``, ``rules_channel_id`` and ``roles_channel_id`` are
        always available to templates without being passed explicitly.
        """
        node: Any = self.messages
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Unknown message template: {path!r}")
            node = node[part]
        if not isinstance(node, str):
            raise KeyError(f"Message template {path!r} is not a string")

        defaults = {
            "moderator_mail_id": self.config.moderator_mail_id,
            "rules_channel_id": self.config.rules_channel_id,
            "roles_channel_id": self.config.roles_channel_id,
        }
        return node.format(**{**defaults, **params})

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "unknown"))
        if self.home_guild is None:
            log.error(
                "Home server %s is not reachable. Check homeserver_id and that the bot "
                "has been invited.",
                self.config.home_server_id,
            )

    # -- convenience accessors --------------------------------------------

    @property
    def home_guild(self) -> discord.Guild | None:
        return self.get_guild(self.config.home_server_id)

    @property
    def verified_role(self) -> discord.Role | None:
        guild = self.home_guild
        return guild.get_role(self.config.verified_role_id) if guild else None

    def _text_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self.get_channel(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        return None

    @property
    def log_channel(self) -> discord.abc.Messageable | None:
        return self._text_channel(self.config.log_channel_id)

    @property
    def unboost_channel(self) -> discord.abc.Messageable | None:
        return self._text_channel(self.config.unboost_announcement_channel_id)

    async def audit(self, embed: discord.Embed) -> None:
        """Post an entry to the log channel, never raising into the caller."""
        channel = self.log_channel
        if channel is None:
            log.warning("Log channel %s is unavailable", self.config.log_channel_id)
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Failed to write to the log channel")

    async def fetch_home_member(self, user_id: int) -> discord.Member | None:
        """Resolve a member of the home guild, falling back to an API call."""
        guild = self.home_guild
        if guild is None:
            return None
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException:
            log.exception("Failed to fetch member %s", user_id)
            return None
