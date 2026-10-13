"""Moderator control of the IRC relay Docker container.

``/irc`` is registered whenever ``irc_relay_id`` is set, even if Docker cannot be
reached at startup, so moderators get an explanation instead of a missing command.
The connection to Docker is made on first use and again after a failure.

The Docker work lives in :func:`connect_docker` and :func:`run_action`, which take
plain arguments and know nothing about Discord, so the same code can be tested with
a fake client and exercised against a real container.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import FAILURE, NEUTRAL, SUCCESS, base_embed, stamp_requester
from ..utils import respond

log = logging.getLogger(__name__)

ACTIONS = ("status", "start", "stop", "restart")

NO_PACKAGE_MESSAGE = (
    "The IRC relay cannot be controlled because the `docker` Python package is not "
    "installed on the machine the bot runs on. Install the bot's requirements again "
    "(`pip install -r requirements.txt`) and restart the bot."
)
UNREACHABLE_MESSAGE = (
    "The bot could not reach the Docker daemon on its host. Either Docker is not "
    "running, or the user running the bot is not allowed to use it (that user must be "
    "in the `docker` group). Nothing was changed."
)


class RelayError(Exception):
    """A failure whose message is safe and useful to show to the moderator."""

    def __init__(self, message: str, *, drop_client: bool = False) -> None:
        super().__init__(message)
        self.message = message
        #: True when the Docker connection should be thrown away and retried next time.
        self.drop_client = drop_client


@dataclass(frozen=True)
class RelayResult:
    action: str
    #: The status Docker reported after the action (re-read with ``reload()``).
    status: str
    #: False when nothing needed doing ("already running" / "already stopped").
    changed: bool
    message: str


def connect_docker() -> Any:
    """Create a Docker client from the environment and check the daemon answers."""
    try:
        import docker
    except ImportError as exc:
        raise RelayError(NO_PACKAGE_MESSAGE) from exc

    client = None
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        raise RelayError(UNREACHABLE_MESSAGE, drop_client=True) from exc
    return client


def run_action(client: Any, reference: str, action: str) -> RelayResult:
    """Run one action against the container called ``reference`` (a name or an ID).

    Blocking; call it from a thread. Raises :class:`RelayError` with a message for
    the moderator on every expected failure.
    """
    try:
        import docker.errors as docker_errors
    except ImportError as exc:
        raise RelayError(NO_PACKAGE_MESSAGE) from exc

    try:
        container = client.containers.get(reference)
        status = str(container.status)

        if action == "status":
            return RelayResult(action, status, False, f"The IRC relay is `{status}`.")
        if action == "start" and status == "running":
            return RelayResult(action, status, False, "The IRC relay is already running.")
        # Only states in which there is nothing to stop. A container that is
        # restarting or paused must still be stopped.
        if action == "stop" and status in ("exited", "created", "dead"):
            return RelayResult(
                action, status, False, f"The IRC relay is already stopped (`{status}`)."
            )

        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        elif action == "restart":
            container.restart()
        else:
            raise ValueError(f"unknown action {action!r}")

        container.reload()
        status = str(container.status)
        verb = {"start": "started", "stop": "stopped", "restart": "restarted"}[action]
        return RelayResult(action, status, True, f"The IRC relay was {verb}. It is now `{status}`.")
    except docker_errors.NotFound as exc:
        raise RelayError(
            f"No Docker container named or numbered `{reference}` exists. That value comes "
            "from `irc_relay_id` in the bot's config.json. Use the container's NAME there "
            "rather than its ID, because an ID changes every time the container is recreated."
        ) from exc
    except docker_errors.APIError as exc:
        raise RelayError(
            f"Docker refused or failed the `{action}` action on the IRC relay. "
            "The details are in the bot's log."
        ) from exc
    except RelayError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        # Connection lost mid-call, permission denied on the socket, and so on.
        raise RelayError(UNREACHABLE_MESSAGE, drop_client=True) from exc


class Infrastructure(commands.Cog):
    def __init__(
        self,
        bot: VerificationBot,
        client_factory: Callable[[], Any] = connect_docker,
    ) -> None:
        self.bot = bot
        self._client_factory = client_factory
        self._client: Any = None
        self._lock = asyncio.Lock()

    @property
    def reference(self) -> str:
        return self.bot.config.irc_relay_id or ""

    async def cog_unload(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                log.warning("Closing the Docker client failed", exc_info=True)

    async def _run(self, action: str) -> RelayResult:
        """Connect if needed, run the action, and forget a broken connection."""
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._client_factory)
            client = self._client
            try:
                return await asyncio.to_thread(run_action, client, self.reference, action)
            except RelayError as exc:
                if exc.drop_client:
                    self._client = None
                    try:
                        await asyncio.to_thread(client.close)
                    except Exception:
                        pass
                raise

    @app_commands.command(name="irc", description="Control the IRC relay container.")
    @app_commands.describe(action="What to do with the IRC relay container.")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="status", value="status"),
            app_commands.Choice(name="start", value="start"),
            app_commands.Choice(name="stop", value="stop"),
            app_commands.Choice(name="restart", value="restart"),
        ]
    )
    @app_commands.guild_only()
    @checks.moderator_only()
    async def irc(
        self, interaction: discord.Interaction, action: app_commands.Choice[str]
    ) -> None:
        # Ephemeral from the start: a deferred reply keeps the visibility it was
        # deferred with, and errors must be private. The mod-log gets the record.
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            result = await self._run(action.value)
        except RelayError as exc:
            # Docker's error text names containers, never members.
            log.warning(
                "IRC relay action %r by member %s failed: %r",
                action.value,
                interaction.user.id,
                exc.__cause__,
            )
            await respond(interaction, exc.message, ephemeral=True)
            return
        except Exception:
            log.exception("Unexpected failure in the IRC relay action %r", action.value)
            await respond(
                interaction,
                "Something unexpected went wrong while talking to Docker. "
                "The details are in the bot's log.",
                ephemeral=True,
            )
            return

        if not result.changed and result.action != "status":
            await respond(interaction, result.message, ephemeral=True)
            return

        if result.action == "status":
            colour = NEUTRAL
        else:
            colour = SUCCESS if result.status == "running" else FAILURE
        embed = base_embed(title=f"IRC relay: {result.action}", colour=colour)
        embed.add_field(name="Container", value=result.message, inline=False)
        stamp_requester(embed, interaction.user)

        await respond(interaction, embed=embed, ephemeral=True)
        await self.bot.audit(embed)
        log.info("Member %s ran the IRC relay action %r", interaction.user.id, action.value)


async def setup(bot: VerificationBot) -> None:
    if not bot.config.irc_relay_id:
        log.info("irc_relay_id is not configured; /irc is not registered")
        return
    await bot.add_cog(Infrastructure(bot))
