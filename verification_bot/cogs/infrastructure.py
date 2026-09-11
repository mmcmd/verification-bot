"""Moderator control of the IRC relay Docker container.

The cog is skipped entirely when ``irc_relay_id`` is unset or the Docker daemon
cannot be reached, so the rest of the bot keeps working on hosts without Docker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import checks
from ..client import VerificationBot
from ..embeds import FAILURE, NEUTRAL, SUCCESS, base_embed, stamp_requester
from ..utils import respond

log = logging.getLogger(__name__)


class Infrastructure(commands.Cog):
    def __init__(self, bot: VerificationBot, docker_client: Any, container_id: str) -> None:
        self.bot = bot
        self.docker = docker_client
        self.container_id = container_id

    async def cog_unload(self) -> None:
        await asyncio.to_thread(self.docker.close)

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
    @app_commands.default_permissions(manage_guild=True)
    @checks.moderator_only()
    async def irc(
        self, interaction: discord.Interaction, action: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(thinking=True)

        try:
            container = await asyncio.to_thread(self.docker.containers.get, self.container_id)
        except Exception:
            log.exception("Could not reach the IRC relay container %s", self.container_id)
            await respond(
                interaction,
                f"Could not reach container `{self.container_id}`. Is the Docker daemon running?",
                ephemeral=True,
            )
            return

        status = container.status
        try:
            if action.value == "start":
                if status == "running":
                    await respond(interaction, "The IRC relay is already running.", ephemeral=True)
                    return
                await asyncio.to_thread(container.start)
                summary, colour = "started", SUCCESS
            elif action.value == "stop":
                if status == "exited":
                    await respond(interaction, "The IRC relay is already stopped.", ephemeral=True)
                    return
                await asyncio.to_thread(container.stop)
                summary, colour = "stopped", FAILURE
            elif action.value == "restart":
                await asyncio.to_thread(container.restart)
                summary, colour = "restarted", SUCCESS
            else:
                summary, colour = f"currently `{status}`", NEUTRAL
        except Exception:
            log.exception("Docker action %r failed on %s", action.value, self.container_id)
            await respond(
                interaction,
                f"The `{action.value}` action failed. Check the bot logs.",
                ephemeral=True,
            )
            return

        embed = base_embed(title="IRC relay", colour=colour)
        embed.add_field(
            name=f"Container `{self.container_id}`", value=f"The container is {summary}."
        )
        stamp_requester(embed, interaction.user)

        await respond(interaction, embed=embed)
        await self.bot.audit(embed)
        log.info(
            "%s (%s) ran the IRC relay action %r",
            interaction.user,
            interaction.user.id,
            action.value,
        )


async def setup(bot: VerificationBot) -> None:
    container_id = bot.config.irc_relay_id
    if not container_id:
        log.info("irc_relay_id is not configured; skipping the infrastructure cog")
        return

    try:
        import docker
    except ImportError:
        log.warning("The docker package is not installed; skipping the infrastructure cog")
        return

    try:
        docker_client = await asyncio.to_thread(docker.from_env)
    except Exception:
        log.warning("Could not connect to the Docker daemon; skipping the infrastructure cog")
        return

    await bot.add_cog(Infrastructure(bot, docker_client, container_id))
