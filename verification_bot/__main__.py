"""Command line entry point: ``python -m verification_bot``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import discord

from .client import VerificationBot
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MESSAGES_PATH,
    ConfigError,
    load_config,
    load_messages,
)
from .logging_setup import InvalidLogKey, setup_logging

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the /r/sysadmin verification bot.")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to config.json."
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        config = load_config(args.config)
        messages = load_messages(args.messages)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    try:
        setup_logging(
            config.log_directory,
            level=getattr(logging, args.log_level),
            retention_days=config.log_retention_days,
            encryption_key=config.log_encryption_key,
        )
    except InvalidLogKey as error:
        print(f"Logging error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(
            f"Logging error: cannot write to {config.log_directory}: {error}",
            file=sys.stderr,
        )
        return 2

    bot = VerificationBot(config, messages)
    try:
        bot.run(config.token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the bot token. Check DISCORD_TOKEN or config.json.")
        return 3
    except discord.PrivilegedIntentsRequired:
        log.error(
            "The Server Members intent is not enabled. Turn it on in the Discord Developer "
            "Portal under Bot > Privileged Gateway Intents."
        )
        return 4
    except KeyboardInterrupt:
        log.info("Shutting down on keyboard interrupt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
