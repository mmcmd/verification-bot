"""Logging configuration.

The bot logs to standard output only. Under systemd that output is captured by
the service log (``journalctl -u verificationbot``). Nothing is written to a log
file by the bot itself.

Every Discord ID is replaced with a per-run pseudonym before a line is written,
and the bot never logs usernames, so the service log holds no member data.
Anything a moderator needs to act on is posted to the mod-log channel instead,
with the real member mention.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Discord snowflakes are 17-20 digit integers.
SNOWFLAKE_PATTERN = re.compile(r"\b\d{17,20}\b")


class RedactingFormatter(logging.Formatter):
    """Replaces Discord IDs with unlinkable pseudonyms.

    The salt is regenerated on every start, so an ID cannot be correlated across
    restarts and the mapping cannot be reversed by anyone reading the output.
    Tracebacks pass through the same replacement.
    """

    def __init__(self, fmt: str, datefmt: str, *, salt: bytes | None = None) -> None:
        super().__init__(fmt, datefmt=datefmt)
        self._salt = salt if salt is not None else secrets.token_bytes(32)

    def format(self, record: logging.LogRecord) -> str:
        return SNOWFLAKE_PATTERN.sub(self._pseudonym, super().format(record))

    def _pseudonym(self, match: re.Match[str]) -> str:
        digest = hmac.new(self._salt, match.group(0).encode("ascii"), hashlib.sha256)
        return f"id:{digest.hexdigest()[:10]}"


def setup_logging(*, level: int = logging.INFO) -> None:
    """Send all logging to standard output through the redacting formatter."""
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(RedactingFormatter(LOG_FORMAT, DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.addHandler(console_handler)

    # discord.py's HTTP and gateway loggers are extremely chatty at INFO on a
    # large guild. Keeping them at WARNING also keeps request details out of the log.
    floor = max(level, logging.WARNING)
    logging.getLogger("discord.http").setLevel(floor)
    logging.getLogger("discord.gateway").setLevel(floor)
    # At DEBUG this logger prints interaction reply URLs, which contain a
    # short-lived credential. Never let it below WARNING.
    logging.getLogger("discord.webhook").setLevel(floor)
