"""Configuration loading and validation.

The bot token is read from the ``DISCORD_TOKEN`` environment variable when it is
set, so production deployments never need to keep the secret on disk.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_MESSAGES_PATH = Path("resources/messages.json")

TOKEN_ENV_VAR = "DISCORD_TOKEN"
LOG_KEY_ENV_VAR = "LOG_ENCRYPTION_KEY"

#: Discord's developer policy caps off-platform retention of API data.
MAX_LOG_RETENTION_DAYS = 30


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


def secret_from_env(name: str) -> str | None:
    """Read a secret from ``<NAME>_FILE`` if present, else from ``<NAME>``.

    The ``_FILE`` form lets Docker secrets be mounted without ever placing the
    value in the process environment.
    """
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise ConfigError(f"Could not read {name}_FILE at {path}: {exc}") from exc
    value = os.environ.get(name)
    return value.strip() if value else None


def _require(data: Mapping[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required configuration key: {key!r}")
    return data[key]


def _as_int(data: Mapping[str, Any], key: str) -> int:
    value = _require(data, key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Configuration key {key!r} must be an integer, got {value!r}") from exc


def _as_optional_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Configuration key {key!r} must be an integer, got {value!r}") from exc


def _as_int_tuple(data: Mapping[str, Any], key: str) -> tuple[int, ...]:
    value = _require(data, key)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ConfigError(f"Configuration key {key!r} must be a list of IDs, got {value!r}")
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Configuration key {key!r} must only contain integer IDs") from exc


def _as_int_with_default(data: Mapping[str, Any], key: str, default: int) -> int:
    return _as_int(data, key) if key in data else default


def _as_optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _as_str(data: Mapping[str, Any], key: str, default: str) -> str:
    """Return a string value, treating JSON null and non-strings as absent."""
    value = data.get(key)
    return value if isinstance(value, str) else default


@dataclass(frozen=True)
class BotConfig:
    """Fully validated runtime configuration."""

    token: str
    home_server_id: int
    status: str

    verified_role_id: int
    verification_requirement_join: int
    verification_requirement_message: int

    moderator_mail_id: int
    moderator_role_ids: tuple[int, ...]

    log_channel_id: int
    unboost_announcement_channel_id: int
    rules_channel_id: int
    roles_channel_id: int

    colored_role_ids: tuple[int, ...]

    ontopic_category_id: int
    emergency_role_id: int
    emergency_request_approval_threshold: int
    emergency_request_deny_threshold: int
    emergency_role_reminder: int
    emergency_role_timeout: int
    emergency_top_role_bypass_ids: tuple[int, ...]

    irc_relay_id: str | None = None
    nitro_role_id: int | None = None
    log_directory: Path = field(default=Path("logs"))
    log_retention_days: int = 14
    log_encryption_key: str | None = field(default=None, repr=False)

    @property
    def emergency_total_timeout_seconds(self) -> int:
        return self.emergency_role_reminder * self.emergency_role_timeout

    def validate(self) -> None:
        """Sanity check values that would otherwise fail at runtime."""
        if not self.token:
            raise ConfigError(
                f"No bot token configured. Set the {TOKEN_ENV_VAR} environment variable "
                "or the 'token' key in config.json."
            )
        if self.verification_requirement_join < 0 or self.verification_requirement_message < 0:
            raise ConfigError("Verification requirements must be zero or greater.")
        if self.emergency_request_approval_threshold < 1:
            raise ConfigError("emergency_request_approval_threshold must be at least 1.")
        if self.emergency_request_deny_threshold < 1:
            raise ConfigError("emergency_request_deny_threshold must be at least 1.")
        if self.emergency_role_reminder < 15:
            raise ConfigError("emergency_role_reminder must be at least 15 seconds.")
        if self.emergency_role_timeout < 1:
            raise ConfigError("emergency_role_timeout must be at least 1.")
        if not 1 <= self.log_retention_days <= MAX_LOG_RETENTION_DAYS:
            raise ConfigError(
                "log_retention_days must be between 1 and "
                f"{MAX_LOG_RETENTION_DAYS} to stay within Discord's retention policy."
            )


def config_from_mapping(data: Mapping[str, Any]) -> BotConfig:
    """Build a :class:`BotConfig` from an already-parsed mapping."""
    config = BotConfig(
        # A JSON null or non-string must not become the literal "None".
        token=secret_from_env(TOKEN_ENV_VAR) or _as_str(data, "token", ""),
        home_server_id=_as_int(data, "homeserver_id"),
        status=_as_str(data, "status", "/verify to get access"),
        verified_role_id=_as_int(data, "verified_role"),
        verification_requirement_join=_as_int(data, "verification_requirement_join"),
        verification_requirement_message=_as_int(data, "verification_requirement_message"),
        moderator_mail_id=_as_int(data, "moderator_mail_id"),
        moderator_role_ids=_as_int_tuple(data, "moderator_role_IDs"),
        log_channel_id=_as_int(data, "log_channel_id"),
        unboost_announcement_channel_id=_as_int(data, "unboost_announcement_channel_id"),
        rules_channel_id=_as_int(data, "rules_channel_id"),
        roles_channel_id=_as_int(data, "roles_channel_id"),
        colored_role_ids=_as_int_tuple(data, "colored_roles"),
        ontopic_category_id=_as_int(data, "ontopic_category_id"),
        emergency_role_id=_as_int(data, "emergency_role_id"),
        emergency_request_approval_threshold=_as_int(data, "emergency_request_approval_threshold"),
        emergency_request_deny_threshold=_as_int(data, "emergency_request_deny_threshold"),
        emergency_role_reminder=_as_int(data, "emergency_role_reminder"),
        emergency_role_timeout=_as_int(data, "emergency_role_timeout"),
        emergency_top_role_bypass_ids=_as_int_tuple(data, "emergency_top_role_bypass_id"),
        irc_relay_id=_as_optional_str(data, "irc_relay_id"),
        nitro_role_id=_as_optional_int(data, "nitro_role"),
        log_directory=Path(_as_str(data, "log_directory", "logs")),
        log_retention_days=_as_int_with_default(data, "log_retention_days", 14),
        log_encryption_key=secret_from_env(LOG_KEY_ENV_VAR),
    )
    config.validate()
    return config


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> BotConfig:
    """Read and validate ``config.json``."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Configuration file {path} not found. Copy config.json.example to config.json."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return config_from_mapping(data)


def load_messages(path: Path | str = DEFAULT_MESSAGES_PATH) -> dict[str, Any]:
    """Read the user-facing message templates."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Message file {path} not found.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return data
