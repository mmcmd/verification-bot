"""Server settings that administrators change from Discord with ``/config``.

The settings file (``data/settings.json`` by default) is written by the bot
itself. It holds role IDs, channel IDs, a few numbers and the status text, and
nothing about any member.

On the first start there is no settings file yet, so the values are imported
from the old-style ``config.json`` and the owner does not have to retype them.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ConfigError

log = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path("data/settings.json")
SETTINGS_FILE_VERSION = 1

DEFAULT_STATUS_TEXT = "/verify to get access"
#: Discord cuts an activity name off at 128 characters.
STATUS_TEXT_MAX_LENGTH = 128

#: The /r/sysadmin server. The old bot hard-coded three of its channels in the
#: source instead of in ``config.json``, so the import has to supply them.
PRODUCTION_SERVER_ID = 362843193617678337
PRODUCTION_IMPORT_DEFAULTS: dict[str, int] = {
    "rules_channel": 448941767325253632,
    "roles_channel": 516816975427797012,
    "booster_channel": 585867795942604800,
}

#: The old status told people to DM the bot, which no longer verifies anyone.
OUTDATED_STATUS_TEXTS = frozenset({"message me to get verified!"})


class SettingsError(ValueError):
    """Raised when a value cannot be stored in a setting."""


class SettingKind(enum.Enum):
    ROLE = "role"
    ROLE_LIST = "role list"
    CHANNEL = "channel"
    CATEGORY = "category"
    USER = "user"
    INTEGER = "number"
    TEXT = "text"


@dataclass(frozen=True)
class SettingSpec:
    """Describes one setting: what it holds and what it is for."""

    key: str
    kind: SettingKind
    label: str
    description: str
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None
    #: Key of the same value in an old-style ``config.json``.
    legacy_key: str | None = None


_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "verified_role", SettingKind.ROLE, "Verified role",
        "The role the bot gives to a member once they are verified.",
        legacy_key="verified_role",
    ),
    SettingSpec(
        "moderator_roles", SettingKind.ROLE_LIST, "Moderator roles",
        "Roles that may use the moderator commands (/clearemergency, /irc).",
        default=(), legacy_key="moderator_role_IDs",
    ),
    SettingSpec(
        "sudo_voter_roles", SettingKind.ROLE_LIST, "Sudo voter roles",
        "Roles that may approve or deny an emergency request. While empty, anyone "
        "whose top role is above the verified role may vote.",
        default=(),
    ),
    SettingSpec(
        "emergency_bypass_roles", SettingKind.ROLE_LIST, "Emergency bypass roles",
        "Roles whose /emergency pings straight away, with no vote.",
        default=(), legacy_key="emergency_top_role_bypass_id",
    ),
    SettingSpec(
        "emergency_role", SettingKind.ROLE, "Emergency role",
        "The role that gets pinged when an emergency is approved.",
        legacy_key="emergency_role_id",
    ),
    SettingSpec(
        "booster_role", SettingKind.ROLE, "Booster role",
        "The role given to members while they boost the server.",
        legacy_key="nitro_role",
    ),
    SettingSpec(
        "colour_roles", SettingKind.ROLE_LIST, "Colour roles",
        "Booster-only colour roles, taken away when a member stops boosting.",
        default=(), legacy_key="colored_roles",
    ),
    SettingSpec(
        "mod_log_channel", SettingKind.CHANNEL, "Mod-log channel",
        "The private channel where the bot records what it did and what went wrong.",
        legacy_key="log_channel_id",
    ),
    SettingSpec(
        "unboost_channel", SettingKind.CHANNEL, "Unboost channel",
        "The channel where the bot announces that a member stopped boosting.",
        legacy_key="unboost_announcement_channel_id",
    ),
    SettingSpec(
        "rules_channel", SettingKind.CHANNEL, "Rules channel",
        "Linked in the message a member gets after verifying.",
        legacy_key="rules_channel_id",
    ),
    SettingSpec(
        "roles_channel", SettingKind.CHANNEL, "Roles channel",
        "The self-assignable roles channel, linked in the verification and boost messages.",
        legacy_key="roles_channel_id",
    ),
    SettingSpec(
        "booster_channel", SettingKind.CHANNEL, "Booster channel",
        "The boosters-only channel, linked in the boost thank-you message.",
        legacy_key="booster_channel_id",
    ),
    SettingSpec(
        "ontopic_category", SettingKind.CATEGORY, "On-topic category",
        "The channel category in which /emergency may be used.",
        legacy_key="ontopic_category_id",
    ),
    SettingSpec(
        "moderator_mail_user", SettingKind.USER, "Moderator Mail user",
        "The mod-mail bot that members are told to contact. While unset, the bot's "
        "owner is named instead.",
        legacy_key="moderator_mail_id",
    ),
    SettingSpec(
        "join_age_days", SettingKind.INTEGER, "Join age threshold (days)",
        "Accounts older than this many days are verified automatically when they join.",
        default=90, minimum=0, maximum=36_500, legacy_key="verification_requirement_join",
    ),
    SettingSpec(
        "verify_age_days", SettingKind.INTEGER, "/verify age threshold (days)",
        "Accounts must be at least this many days old for /verify to work.",
        default=5, minimum=0, maximum=36_500, legacy_key="verification_requirement_message",
    ),
    SettingSpec(
        "approval_threshold", SettingKind.INTEGER, "Emergency approval threshold",
        "How many approvals an emergency request needs.",
        default=3, minimum=1, maximum=25, legacy_key="emergency_request_approval_threshold",
    ),
    SettingSpec(
        "denial_threshold", SettingKind.INTEGER, "Emergency denial threshold",
        "How many denials reject an emergency request.",
        default=2, minimum=1, maximum=25, legacy_key="emergency_request_deny_threshold",
    ),
    SettingSpec(
        "reminder_interval_seconds", SettingKind.INTEGER, "Emergency reminder interval (seconds)",
        "How long the bot waits between reminders about a pending emergency request.",
        default=180, minimum=15, maximum=3_600, legacy_key="emergency_role_reminder",
    ),
    SettingSpec(
        "reminder_count", SettingKind.INTEGER, "Emergency reminder count",
        "How many reminders are sent before a pending emergency request times out.",
        default=5, minimum=1, maximum=24, legacy_key="emergency_role_timeout",
    ),
    SettingSpec(
        "status_text", SettingKind.TEXT, "Status text",
        "The \"Playing ...\" text shown under the bot's name.",
        default=DEFAULT_STATUS_TEXT, legacy_key="status",
    ),
)

#: Every setting, in the order ``/config show`` lists them.
SETTINGS: dict[str, SettingSpec] = {spec.key: spec for spec in _SPECS}

_ID_KINDS = frozenset(
    {SettingKind.ROLE, SettingKind.CHANNEL, SettingKind.CATEGORY, SettingKind.USER}
)


def spec_for(key: str) -> SettingSpec:
    try:
        return SETTINGS[key]
    except KeyError:
        raise KeyError(f"Unknown setting: {key!r}") from None


def _as_id(spec: SettingSpec, value: Any) -> int:
    if isinstance(value, bool):
        raise SettingsError(f"{spec.label} must be an ID, got {value!r}.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{spec.label} must be an ID, got {value!r}.") from None
    if number <= 0:
        raise SettingsError(f"{spec.label} must be an ID, got {value!r}.")
    return number


def normalise(spec: SettingSpec, value: Any) -> Any:
    """Validate ``value`` for ``spec`` and return it in its stored form.

    IDs become ``int``, role lists a ``tuple`` of ``int`` without duplicates.
    Raises :class:`SettingsError` when the value does not fit.
    """
    if spec.kind in _ID_KINDS:
        return _as_id(spec, value)

    if spec.kind is SettingKind.ROLE_LIST:
        # A single ID is accepted as a list of one. The old config stored the
        # emergency bypass role that way.
        items = [value] if isinstance(value, (str, bytes, int)) else value
        if not isinstance(items, Iterable):
            raise SettingsError(f"{spec.label} must be a list of role IDs, got {value!r}.")
        return tuple(dict.fromkeys(_as_id(spec, item) for item in items))

    if spec.kind is SettingKind.INTEGER:
        if isinstance(value, bool):
            raise SettingsError(f"{spec.label} must be a whole number, got {value!r}.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{spec.label} must be a whole number, got {value!r}.") from None
        if spec.minimum is not None and number < spec.minimum:
            raise SettingsError(f"{spec.label} must be at least {spec.minimum}.")
        if spec.maximum is not None and number > spec.maximum:
            raise SettingsError(f"{spec.label} must be at most {spec.maximum}.")
        return number

    if not isinstance(value, str) or not value.strip():
        raise SettingsError(f"{spec.label} must not be empty.")
    text = value.strip()
    if len(text) > STATUS_TEXT_MAX_LENGTH:
        raise SettingsError(f"{spec.label} must be at most {STATUS_TEXT_MAX_LENGTH} characters.")
    return text


def format_value(spec: SettingSpec, value: Any) -> str:
    """Render a setting's value for display in Discord (mentions, not raw IDs)."""
    if value is None or value == ():
        return "*not set*"
    if spec.kind is SettingKind.ROLE:
        return f"<@&{value}>"
    if spec.kind is SettingKind.ROLE_LIST:
        return ", ".join(f"<@&{role_id}>" for role_id in value)
    if spec.kind in (SettingKind.CHANNEL, SettingKind.CATEGORY):
        return f"<#{value}>"
    if spec.kind is SettingKind.USER:
        return f"<@{value}>"
    return str(value)


def has_legacy_settings(data: Mapping[str, Any]) -> bool:
    """True when ``data`` (a parsed ``config.json``) carries old-style settings."""
    return any(spec.legacy_key in data for spec in SETTINGS.values() if spec.legacy_key)


def import_legacy(data: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Translate an old-style ``config.json`` into settings.

    Returns the settings plus a list of plain-language notes about anything that
    could not be imported. A value that does not fit is skipped, never fatal, so
    one bad entry cannot keep the bot from starting.
    """
    values: dict[str, Any] = {}
    notes: list[str] = []

    for spec in SETTINGS.values():
        if spec.legacy_key is None or spec.legacy_key not in data:
            continue
        raw = data[spec.legacy_key]
        if raw is None or raw == "" or raw == []:
            continue
        if spec.key == "status_text" and isinstance(raw, str):
            if raw.strip().lower() in OUTDATED_STATUS_TEXTS:
                raw = DEFAULT_STATUS_TEXT
        try:
            values[spec.key] = normalise(spec, raw)
        except SettingsError as error:
            notes.append(f"Skipped {spec.legacy_key!r} from config.json: {error}")

    try:
        is_production = int(data.get("homeserver_id", 0)) == PRODUCTION_SERVER_ID
    except (TypeError, ValueError):
        is_production = False
    if is_production:
        for key, channel_id in PRODUCTION_IMPORT_DEFAULTS.items():
            values.setdefault(key, channel_id)

    return values, notes


class SettingsStore:
    """The settings, kept in memory and saved to disk on every change."""

    def __init__(self, path: Path | str, values: Mapping[str, Any] | None = None) -> None:
        self.path = Path(path)
        self._values: dict[str, Any] = {}
        for key, value in (values or {}).items():
            self._values[key] = normalise(spec_for(key), value)

    # -- reading -----------------------------------------------------------

    def get(self, key: str) -> Any:
        """The value of a setting, or its default while it is unset.

        Unset roles, channels, categories and users are ``None``; unset role
        lists are an empty tuple. Unknown keys raise ``KeyError``.
        """
        spec = spec_for(key)
        return self._values.get(key, spec.default)

    def is_set(self, key: str) -> bool:
        """True when the setting holds a value of its own rather than the default."""
        spec_for(key)
        value = self._values.get(key)
        return value is not None and value != ()

    def as_dict(self) -> dict[str, Any]:
        return {key: self.get(key) for key in SETTINGS}

    # -- writing -----------------------------------------------------------

    def set(self, key: str, value: Any) -> Any:
        """Validate and store a value, save the file, and return the stored form.

        ``None`` (or an empty list) clears the setting. Raises
        :class:`SettingsError` for a value that does not fit, and ``OSError``
        when the file cannot be written; in both cases nothing changes.
        """
        spec = spec_for(key)
        previous = dict(self._values)
        if value is None:
            self._values.pop(key, None)
        else:
            stored = normalise(spec, value)
            if stored == ():
                self._values.pop(key, None)
            else:
                self._values[key] = stored
        try:
            self.save()
        except OSError:
            self._values = previous
            raise
        return self.get(key)

    def reset(self, key: str) -> Any:
        """Clear a setting so it falls back to its default."""
        return self.set(key, None)

    def save(self) -> None:
        """Write the file atomically: a crash never leaves a half-written file."""
        payload = {
            "version": SETTINGS_FILE_VERSION,
            "settings": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in self._values.items()
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=4)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> SettingsStore:
        """Read an existing settings file."""
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Settings file {path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read the settings file {path}: {exc}") from exc
        stored = data.get("settings") if isinstance(data, dict) else None
        if not isinstance(stored, dict):
            raise ConfigError(f"Settings file {path} does not have the expected layout.")

        store = cls(path)
        for key, value in stored.items():
            if key not in SETTINGS:
                log.warning("Ignoring unknown setting %r in %s", key, path)
                continue
            try:
                store._values[key] = normalise(SETTINGS[key], value)
            except SettingsError as error:
                log.warning("Ignoring a bad value in %s: %s", path, error)
        return store


def load_or_import(
    path: Path | str, legacy_config: Mapping[str, Any]
) -> tuple[SettingsStore, bool]:
    """Open the settings file, creating it from ``config.json`` on first start.

    Returns the store and whether an import just happened.
    """
    path = Path(path)
    if path.exists():
        return SettingsStore.load(path), False

    values, notes = import_legacy(legacy_config)
    store = SettingsStore(path, values)
    try:
        store.save()
    except OSError as exc:
        raise ConfigError(
            f"Could not create the settings file {path}: {exc}. The bot needs to be "
            "able to write to that folder."
        ) from exc

    if values:
        log.info("Imported %d setting(s) from config.json into %s", len(values), path)
    else:
        log.info(
            "Created an empty settings file at %s. An administrator has to run /config.", path
        )
    for note in notes:
        log.warning("%s", note)
    return store, bool(values)
