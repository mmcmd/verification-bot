"""Logging configuration.

Two sinks with deliberately different privacy properties:

* the **file** sink keeps full detail and is encrypted at rest and retention-bounded;
* the **console** sink is plaintext and is captured by the container runtime, so every
  Discord ID is replaced with a per-process pseudonym before it is written.

Use ``python -m verification_bot.logtools`` to generate a key or read a log back.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import logging.handlers
import re
import secrets
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME = "verification.log"

#: Discord snowflakes are 17-20 digit integers.
SNOWFLAKE_PATTERN = re.compile(r"\b\d{17,20}\b")


class RedactingFormatter(logging.Formatter):
    """Replaces Discord IDs with unlinkable pseudonyms.

    The salt is regenerated on every start, so an ID cannot be correlated across
    restarts and the mapping cannot be reversed by anyone reading the output.
    """

    def __init__(self, fmt: str, datefmt: str, *, salt: bytes | None = None) -> None:
        super().__init__(fmt, datefmt=datefmt)
        self._salt = salt if salt is not None else secrets.token_bytes(32)

    def format(self, record: logging.LogRecord) -> str:
        return SNOWFLAKE_PATTERN.sub(self._pseudonym, super().format(record))

    def _pseudonym(self, match: re.Match[str]) -> str:
        digest = hmac.new(self._salt, match.group(0).encode("ascii"), hashlib.sha256)
        return f"user:{digest.hexdigest()[:10]}"


class InvalidLogKey(ValueError):
    """Raised when the configured log encryption key cannot be used."""


def build_cipher(key: str):
    """Return a Fernet cipher (AES-128-CBC + HMAC-SHA256) for the given key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise InvalidLogKey(
            "The 'cryptography' package is required for encrypted logs. "
            "Install it with: pip install 'verification-bot[encryption]'"
        ) from exc

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise InvalidLogKey(
            "LOG_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
            "python -m verification_bot.logtools generate-key"
        ) from exc


class EncryptedTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Writes one Fernet token per line, so records stay individually decryptable."""

    def __init__(self, filename: Path | str, cipher, **kwargs) -> None:
        self._cipher = cipher
        super().__init__(str(filename), **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        plaintext = super().format(record)
        return self._cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")


def setup_logging(
    log_directory: Path,
    *,
    level: int = logging.INFO,
    retention_days: int = 14,
    encryption_key: str | None = None,
) -> None:
    """Configure a rotating file handler and a console handler on the root logger."""
    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    log_path = log_directory / LOG_FILENAME

    rotation = {"when": "midnight", "utc": True, "backupCount": retention_days, "encoding": "utf-8"}

    file_handler: logging.Handler
    if encryption_key:
        file_handler = EncryptedTimedRotatingFileHandler(
            log_path, build_cipher(encryption_key), **rotation
        )
    else:
        file_handler = logging.handlers.TimedRotatingFileHandler(log_path, **rotation)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(RedactingFormatter(LOG_FORMAT, DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # discord.py's HTTP logger is extremely chatty at INFO on a large guild.
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)

    if not encryption_key:
        logging.getLogger(__name__).warning(
            "Log files are NOT encrypted at rest. Discord's developer policy requires "
            "encryption for stored API data. Set LOG_ENCRYPTION_KEY (or "
            "LOG_ENCRYPTION_KEY_FILE) to enable it."
        )
