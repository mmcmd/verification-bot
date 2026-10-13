"""The bot client, command tree and startup wiring."""

from __future__ import annotations

import datetime
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from . import checks
from .config import BotConfig
from .embeds import FAILURE, NEUTRAL, actor_embed, base_embed
from .settings import SETTINGS, SettingKind, SettingsStore, format_value
from .utils import respond

log = logging.getLogger(__name__)

EXTENSIONS: tuple[str, ...] = (
    "verification_bot.cogs.verification",
    "verification_bot.cogs.emergency",
    "verification_bot.cogs.community",
    "verification_bot.cogs.utility",
    "verification_bot.cogs.infrastructure",
    "verification_bot.cogs.settings",
)

#: Commands that must stay global so members can run them from their DMs.
GLOBAL_COMMANDS: frozenset[str] = frozenset({"verify", "help", "privacy"})

#: The same configuration problem is reported to the mod-log at most this often.
FAILURE_REPORT_COOLDOWN = datetime.timedelta(minutes=10)

REDUCED_MODE_WARNING = (
    "Discord did not allow the **Server Members** intent, so the bot started in "
    "**reduced mode**. The Server Members intent is the permission that lets the bot "
    "see members joining and boosting. Until Discord allows it, these are off:\n"
    "- automatic verification when someone joins\n"
    "- the boost thank-you message and the booster role\n"
    "- removing booster and colour roles when someone stops boosting\n"
    "- `/boosters`\n\n"
    "Every command still works, including `/verify`. Once Discord approves the "
    "intent, restart the bot and everything comes back. No settings need to change."
)


def build_intents(*, members: bool = True) -> discord.Intents:
    """The minimum set of gateway intents the bot actually needs.

    ``members`` is the only privileged intent requested: it powers join-time
    verification and Nitro boost tracking. Message Content and Presence are
    deliberately left disabled. Pass ``members=False`` for reduced mode, which
    asks Discord for no privileged intent at all.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = members
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

        if isinstance(error, app_commands.NoPrivateMessage):
            await respond(interaction, "This command can only be used in a server.", ephemeral=True)
            return

        if isinstance(error, app_commands.CheckFailure):
            await respond(
                interaction,
                str(error) or "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        original = getattr(error, "original", error)
        log.error("Unhandled error in /%s", command, exc_info=original)

        bot: VerificationBot = interaction.client  # type: ignore[assignment]
        channel = getattr(interaction.channel, "mention", None) or "a direct message"
        notified = await bot.report_failure(
            f"/{command} failed",
            f"{interaction.user.mention} ran `/{command}` in {channel} and the bot hit an "
            f"unexpected error:\n`{type(original).__name__}: {str(original)[:300]}`",
            member=interaction.user,
        )
        if notified:
            text = (
                "Something went wrong while running that command. "
                "The moderators have been notified."
            )
        else:
            text = (
                "Something went wrong while running that command. "
                f"Please let {bot.contact} know."
            )
        try:
            await respond(interaction, text, ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not tell the user that /%s failed", command)


class VerificationBot(commands.Bot):
    """Application-command bot for the /r/sysadmin server."""

    def __init__(
        self,
        config: BotConfig,
        messages: dict[str, Any],
        settings: SettingsStore,
        *,
        reduced_mode: bool = False,
        sync_commands: bool = True,
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            help_command=None,
            intents=build_intents(members=not reduced_mode),
            activity=discord.Game(name=settings.get("status_text")),
            # Roles are never pinged by accident: a message that should ping a role
            # passes its own ``allowed_mentions`` naming that role.
            allowed_mentions=discord.AllowedMentions(
                everyone=False, users=True, roles=False, replied_user=True
            ),
            tree_cls=VerificationCommandTree,
            max_messages=None,
            # Boost tracking and /boosters need the full member list, which Discord
            # only hands out together with the Server Members intent.
            chunk_guilds_at_startup=not reduced_mode,
        )
        self.config = config
        self.messages = messages
        self.settings = settings
        #: True when Discord refused the Server Members intent and the bot is
        #: running without it. Join and boost events never arrive in this mode.
        self.reduced_mode = reduced_mode
        self.started_at = discord.utils.utcnow()
        self.owner_user_id: int | None = None
        self._sync_commands_on_start = sync_commands
        self._startup_announced = False
        self._failure_reports: dict[str, datetime.datetime] = {}

    # -- lifecycle ---------------------------------------------------------

    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
            except commands.ExtensionError:
                log.exception("Failed to load extension %s", extension)
                raise
            log.info("Loaded extension %s", extension)

        self._assign_command_scopes()
        if self._sync_commands_on_start:
            await self._sync_commands()

        try:
            application = self.application or await self.application_info()
        except discord.HTTPException:
            log.warning("Could not look up the bot's owner")
        else:
            team = application.team
            self.owner_user_id = team.owner_id if team is not None else application.owner.id

    def _assign_command_scopes(self) -> None:
        """Move every command that is not DM-capable to the home server."""
        guild = discord.Object(id=self.config.home_server_id)
        for command in list(self.tree.get_commands()):
            if command.name in GLOBAL_COMMANDS:
                continue
            self.tree.remove_command(command.name)
            self.tree.add_command(command, guild=guild)

    def all_app_commands(self) -> list[app_commands.Command | app_commands.Group]:
        """Every slash command: the global ones plus those of the home server."""
        guild = discord.Object(id=self.config.home_server_id)
        return [*self.tree.get_commands(), *self.tree.get_commands(guild=guild)]

    async def _sync_commands(self) -> None:
        """Register the commands with Discord."""
        guild = discord.Object(id=self.config.home_server_id)
        try:
            guild_commands = await self.tree.sync(guild=guild)
        except discord.HTTPException as error:
            # Not fatal: the bot still runs, and a restart would not fix it.
            log.error(
                "Could not register commands in the home server %s (HTTP %s). Check "
                "homeserver_id and that the bot was invited with the "
                "applications.commands scope.",
                self.config.home_server_id,
                error.status,
            )
            guild_commands = []
        try:
            global_commands = await self.tree.sync()
        except discord.HTTPException as error:
            log.error("Could not register the global commands (HTTP %s)", error.status)
            global_commands = []
        log.info(
            "Registered %d server command(s) and %d global command(s)",
            len(guild_commands),
            len(global_commands),
        )

    async def on_message(self, message: discord.Message) -> None:
        """Deliberately does nothing.

        The default handler would look inside every message for a prefix
        command. This bot has none, and it must never read message text. The
        verification cog still gets its own ``on_message`` call for DMs.
        """

    async def on_ready(self) -> None:
        log.info("Logged in as bot %s", getattr(self.user, "id", "unknown"))
        guild = self.home_guild
        if guild is None:
            log.error(
                "Home server %s is not reachable. Check homeserver_id and that the bot "
                "has been invited.",
                self.config.home_server_id,
            )

        # on_ready fires again after some reconnects; announce the mode only once.
        if self._startup_announced:
            return
        self._startup_announced = True

        if not self.reduced_mode:
            log.info(
                "Running in FULL mode: Server Members intent granted, %d member(s) loaded",
                len(guild.members) if guild else 0,
            )
            return

        log.warning(
            "Running in REDUCED mode: Discord refused the Server Members intent. "
            "Auto-verify on join, boost tracking and /boosters are off."
        )
        await self.audit(
            base_embed(
                title="Bot started in reduced mode",
                description=REDUCED_MODE_WARNING,
                colour=FAILURE,
            )
        )

    # -- message templates -------------------------------------------------

    def message(self, path: str, **params: Any) -> str:
        """Look up a dotted template path in ``resources/messages.json``.

        ``contact``, ``rules_channel``, ``roles_channel`` and ``booster_channel``
        are always available to templates without being passed explicitly.
        """
        node: Any = self.messages
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Unknown message template: {path!r}")
            node = node[part]
        if not isinstance(node, str):
            raise KeyError(f"Message template {path!r} is not a string")

        defaults = {
            "contact": self.contact,
            "rules_channel": self._channel_reference("rules_channel", "the rules channel"),
            "roles_channel": self._channel_reference("roles_channel", "the roles channel"),
            "booster_channel": self._channel_reference("booster_channel", "the boosters channel"),
        }
        return node.format(**{**defaults, **params})

    def _channel_reference(self, key: str, fallback: str) -> str:
        channel_id = self.settings.get(key)
        return f"<#{channel_id}>" if channel_id else fallback

    @property
    def contact(self) -> str:
        """Who a member is told to contact: Moderator Mail, else the bot's owner."""
        moderator_mail = self.settings.get("moderator_mail_user")
        if moderator_mail:
            return f"<@{moderator_mail}> (Moderator Mail, at the top of the member list)"
        if self.owner_user_id:
            return f"<@{self.owner_user_id}> (the bot's owner)"
        return "a moderator"

    # -- convenience accessors --------------------------------------------

    @property
    def home_guild(self) -> discord.Guild | None:
        return self.get_guild(self.config.home_server_id)

    def setting_role(self, key: str) -> discord.Role | None:
        """The role a single-role setting points at, or ``None`` if unset or deleted."""
        guild = self.home_guild
        role_id = self.settings.get(key)
        return guild.get_role(role_id) if guild and role_id else None

    def setting_channel(self, key: str) -> discord.TextChannel | discord.Thread | None:
        """The text channel a channel setting points at, or ``None`` if unusable."""
        channel_id = self.settings.get(key)
        channel = self.get_channel(channel_id) if channel_id else None
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        return None

    def has_setting_role(self, member: discord.Member, key: str) -> bool:
        """True when ``member`` holds the role (or one of the roles) in a setting."""
        value = self.settings.get(key)
        if not value:
            return False
        wanted = value if isinstance(value, tuple) else (value,)
        return checks.has_any_role_id(member, wanted)

    @property
    def verified_role(self) -> discord.Role | None:
        return self.setting_role("verified_role")

    @property
    def log_channel(self) -> discord.TextChannel | discord.Thread | None:
        return self.setting_channel("mod_log_channel")

    # -- mod-log -----------------------------------------------------------

    async def audit(self, embed: discord.Embed) -> bool:
        """Post an entry to the mod-log channel, never raising into the caller.

        Returns whether the entry was actually posted.
        """
        channel = self.log_channel
        if channel is None:
            log.warning("The mod-log channel is not set or not reachable; entry not posted")
            return False
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Failed to write to the mod-log channel")
            return False
        return True

    async def report_failure(
        self,
        title: str,
        description: str,
        *,
        member: discord.abc.User | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """Tell the moderators, in the mod-log channel, about something they must fix.

        The service log only shows scrambled IDs, so anything a moderator has to
        act on is posted here with the real member mention. Pass ``dedupe_key``
        for problems that would otherwise repeat on every join (a deleted role,
        for example); the same key is posted at most once per ten minutes.
        Returns whether the report was posted.
        """
        if dedupe_key is not None:
            now = discord.utils.utcnow()
            last = self._failure_reports.get(dedupe_key)
            if last is not None and now - last < FAILURE_REPORT_COOLDOWN:
                return False
            self._failure_reports[dedupe_key] = now

        if member is not None:
            embed = actor_embed(member, title=title, description=description, colour=FAILURE)
        else:
            embed = base_embed(title=title, description=description, colour=FAILURE)
        embed.set_footer(text="Needs a moderator's attention")
        return await self.audit(embed)

    # -- settings ----------------------------------------------------------

    async def change_setting(self, key: str, value: Any, *, actor: discord.abc.User) -> Any:
        """Store a new value for a setting and record who changed it.

        The change takes effect immediately and is posted to the mod-log
        channel. ``None`` clears the setting. Raises ``SettingsError`` for a
        value that does not fit and ``OSError`` if the file cannot be written.
        Returns the stored value.
        """
        spec = SETTINGS[key]
        before = self.settings.get(key)
        after = self.settings.set(key, value)

        if spec.kind is SettingKind.TEXT and key == "status_text" and not self.is_closed():
            # Also remembered for the next reconnect, not only the current session.
            self.activity = discord.Game(name=after)
            try:
                await self.change_presence(activity=self.activity)
            except Exception:
                log.warning("Could not update the status text right away", exc_info=True)

        log.info("Setting %s was changed by member %s", key, actor.id)
        await self.audit(
            actor_embed(
                actor,
                title="Setting changed",
                description=(
                    f"{actor.mention} changed **{spec.label}**.\n"
                    f"**Before:** {format_value(spec, before)}\n"
                    f"**After:** {format_value(spec, after)}"
                ),
                colour=NEUTRAL,
            )
        )
        return after

    # -- members -----------------------------------------------------------

    async def fetch_home_member(self, user_id: int) -> discord.Member | None:
        """Resolve a member of the home guild, falling back to an API call.

        Looking up one member by ID needs no privileged intent, so this works
        in reduced mode too.
        """
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
