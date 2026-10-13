"""Command line entry point: ``python -m verification_bot``.

The exit codes matter: the systemd service restarts the bot after a crash, but
must never restart it after a problem that a restart cannot fix. Restarting on a
rejected token is what got the old bot's token reset by Discord.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from .client import VerificationBot
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MESSAGES_PATH,
    BotConfig,
    ConfigError,
    config_from_mapping,
    load_messages,
    load_raw_config,
)
from .logging_setup import setup_logging
from .settings import DEFAULT_SETTINGS_PATH, SettingsStore, load_or_import

log = logging.getLogger(__name__)

EXIT_OK = 0
#: Anything unexpected. The service waits and starts the bot again.
EXIT_CRASH = 1
#: config.json, messages.json or the settings file is missing or broken.
EXIT_BAD_CONFIG = 2
#: Discord rejected the bot token.
EXIT_BAD_TOKEN = 3
#: Discord refused the gateway intents even in reduced mode.
EXIT_INTENTS_REFUSED = 4

#: Gateway close codes: authentication failed, invalid intents, disallowed intents.
CLOSE_CODE_BAD_TOKEN = 4004
CLOSE_CODES_INTENTS = (4013, 4014)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the /r/sysadmin verification bot.")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to config.json."
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="Path to the settings file the bot writes and /config changes.",
    )
    parser.add_argument(
        "--messages", type=Path, default=DEFAULT_MESSAGES_PATH, help="Path to messages.json."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


async def _start(bot: VerificationBot, token: str) -> None:
    """Connect and stay connected until the bot is closed."""
    loop = asyncio.get_running_loop()

    closing: list[asyncio.Task[None]] = []

    def request_shutdown() -> None:
        if not closing:
            log.info("Shutdown requested; closing the connection")
            closing.append(loop.create_task(bot.close()))

    handled: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            continue  # Not available here (Windows, or not the main thread).
        handled.append(signum)

    try:
        async with bot:
            await bot.start(token)
    finally:
        for signum in handled:
            loop.remove_signal_handler(signum)


async def run_bot(config: BotConfig, messages: dict[str, Any], settings: SettingsStore) -> int:
    """Run the bot and return the process exit code.

    Connects once. If Discord refuses the Server Members intent, connects exactly
    once more without it (reduced mode). There is no other retry.
    """
    bot = VerificationBot(config, messages, settings)
    try:
        await _start(bot, config.token)
        return EXIT_OK
    except discord.PrivilegedIntentsRequired:
        log.warning(
            "Discord refused the Server Members intent. Starting once more without it "
            "(reduced mode)."
        )

    # The commands were registered during the first attempt, before the gateway
    # connection was refused, so the second attempt does not register them again.
    bot = VerificationBot(config, messages, settings, reduced_mode=True, sync_commands=False)
    try:
        await _start(bot, config.token)
    except discord.PrivilegedIntentsRequired:
        log.error("Discord refused the connection even without the Server Members intent.")
        return EXIT_INTENTS_REFUSED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(level=getattr(logging, args.log_level))

    try:
        raw_config = load_raw_config(args.config)
        config = config_from_mapping(raw_config)
        messages = load_messages(args.messages)
        settings, _ = load_or_import(args.settings, raw_config)
    except ConfigError as error:
        log.error("Configuration error: %s", error)
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_BAD_CONFIG
    except Exception as error:
        # A file in the wrong text encoding, a folder the bot may not enter, and
        # the like. Starting again would hit the same problem, so do not restart.
        log.exception("Could not load the configuration")
        print(f"Configuration error: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_BAD_CONFIG

    try:
        return asyncio.run(run_bot(config, messages, settings))
    except KeyboardInterrupt:
        log.info("Shutting down on keyboard interrupt")
        return EXIT_OK
    except discord.LoginFailure:
        log.error(
            "Discord rejected the bot token. Put a valid token in config.json (or the "
            "DISCORD_TOKEN environment variable). The bot will not restart by itself."
        )
        return EXIT_BAD_TOKEN
    except discord.ConnectionClosed as error:
        if error.code == CLOSE_CODE_BAD_TOKEN:
            log.error(
                "Discord closed the connection because the bot token is no longer valid. "
                "The bot will not restart by itself."
            )
            return EXIT_BAD_TOKEN
        if error.code in CLOSE_CODES_INTENTS:
            log.error("Discord refused the gateway intents (close code %s).", error.code)
            return EXIT_INTENTS_REFUSED
        log.error("Discord closed the connection (close code %s).", error.code)
        return EXIT_CRASH
    except commands.ExtensionError:
        log.exception("A part of the bot failed to load. This is a bug, not a setting.")
        return EXIT_BAD_CONFIG
    except Exception:
        log.exception("The bot stopped because of an unexpected error")
        return EXIT_CRASH


if __name__ == "__main__":
    raise SystemExit(main())
