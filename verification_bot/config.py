"""Startup configuration: only what the bot needs before it can connect.

``config.json`` holds the bot token, the home server ID and (optionally) the IRC
relay container. Everything else lives in the settings file that the bot writes
itself and that administrators change with ``/config`` (see ``settings.py``).

The bot token is read from the ``DISCORD_TOKEN`` environment variable when it is
set, so the secret does not have to be kept in the file.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_MESSAGES_PATH = Path("resources/messages.json")

TOKEN_ENV_VAR = "DISCORD_TOKEN"


class ConfigError(RuntimeError):
    """Raised when a configuration file is missing or invalid."""


def _as_str(data: Mapping[str, Any], key: str, default: str) -> str:
    """Return a string value, treating JSON null and non-strings as absent."""
    value = data.get(key)
    return value if isinstance(value, str) else default


@dataclass(frozen=True)
class BotConfig:
    """Validated startup configuration."""

    token: str = field(repr=False)
    home_server_id: int
    #: Name or ID of the IRC relay Docker container; ``None`` disables ``/irc``.
    irc_relay_id: str | None = None


def config_from_mapping(data: Mapping[str, Any]) -> BotConfig:
    """Build a :class:`BotConfig` from an already-parsed mapping.

    Keys other than ``token``, ``homeserver_id`` and ``irc_relay_id`` are ignored
    here. An old-style ``config.json`` carries many more; those are imported into
    the settings file on first start.
    """
    env_token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    # A JSON null or non-string must not become the literal "None".
    token = env_token or _as_str(data, "token", "").strip()
    if not token:
        raise ConfigError(
            f"No bot token configured. Set the {TOKEN_ENV_VAR} environment variable "
            "or the 'token' key in config.json."
        )

    if "homeserver_id" not in data:
        raise ConfigError("Missing required configuration key: 'homeserver_id'")
    raw_server_id = data["homeserver_id"]
    try:
        home_server_id = int(raw_server_id)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"Configuration key 'homeserver_id' must be a server ID, got {raw_server_id!r}"
        ) from exc

    relay = data.get("irc_relay_id")
    irc_relay_id = str(relay).strip() if relay not in (None, "") else None

    return BotConfig(token=token, home_server_id=home_server_id, irc_relay_id=irc_relay_id or None)


def read_json_object(path: Path | str, *, missing_hint: str = "") -> dict[str, Any]:
    """Read a JSON file that must contain an object."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found.{' ' + missing_hint if missing_hint else ''}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return data


def load_raw_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read ``config.json`` without interpreting it."""
    return read_json_object(path, missing_hint="Copy config.json.example to config.json.")


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> BotConfig:
    """Read and validate ``config.json``."""
    return config_from_mapping(load_raw_config(path))


def load_messages(path: Path | str = DEFAULT_MESSAGES_PATH) -> dict[str, Any]:
    """Read the user-facing message templates."""
    return read_json_object(path)
