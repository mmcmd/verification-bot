# verification-bot (for /r/sysadmin)

Account-age verification and moderation utilities for the [/r/sysadmin](https://www.reddit.com/r/sysadmin/)
Discord server (~25,000 members). Every user-facing feature is a Discord **slash command**.

The bot requests exactly one privileged intent — **Server Members**. It does **not** use
Message Content or Presence. See [PRIVACY.md](PRIVACY.md).

## Commands

| Command | Who can use it | What it does |
| --- | --- | --- |
| `/verify` | Anyone, including in DMs with the bot | Grants the verified role if the account is older than `verification_requirement_message` days |
| `/emergency reason:<text>` | Verified members, on-topic channels only | Opens a staff-approved request to ping the emergency role |
| `/clearemergency` | Moderators | Cancels the pending emergency request |
| `/boosters` | Anyone | Lists current Nitro boosters |
| `/irc action:<start\|stop\|restart\|status>` | Moderators | Controls the IRC relay Docker container |
| `/ping`, `/uptime`, `/github`, `/steve` | Anyone | Diagnostics and fluff |

Automatic behaviour (no command needed):

- Members whose account is older than `verification_requirement_join` days are verified on join.
- Members who start boosting get a thank-you DM and the hidden Nitro Booster role, which
  displays them in the member list. They can self-remove it later without losing anything else.
- Members who stop boosting lose their colored roles and the Nitro Booster role, and are
  announced in the unboost channel.
- DMing the bot returns a short message pointing at `/verify`. The message body is never read.

## Requirements

- Docker with Compose v2 (recommended), **or** Python 3.10+
- The **Server Members** privileged intent enabled in the Discord Developer Portal

## Running with Docker (recommended)

The image is a two-stage Alpine build that ships only a virtualenv and the
interpreter — **~90 MB**, running as an unprivileged user on a read-only root
filesystem, capped at 256 MB / 0.5 CPU.

```bash
cp config.json.example config.json
$EDITOR config.json

# Compose validates secret files before starting anything, so create them first.
docker compose build bot
mkdir -p secrets
printf '%s' 'YOUR_BOT_TOKEN' > secrets/discord_token
docker run --rm --entrypoint python verification-bot:latest \
    -m verification_bot.logtools generate-key > secrets/log_encryption_key
chmod 600 secrets/*

docker compose up -d
docker compose logs -f bot
```

Both secrets are mounted as Docker secrets at `/run/secrets/...` and read through
`DISCORD_TOKEN_FILE` / `LOG_ENCRYPTION_KEY_FILE`, so neither value ever appears in
the process environment, in `docker inspect`, or in the image.

**Back up `secrets/log_encryption_key`.** Without it, existing log files cannot be read.

### Enabling `/irc` under Docker

`/irc` needs to talk to the Docker daemon. Mounting `/var/run/docker.sock` directly
into the bot would give it root-equivalent access to the host, so Compose instead
runs a proxy with an explicit per-endpoint allowlist — inspect, start, stop and
restart on the single configured container, and nothing else:

```bash
export DOCKER_GID=$(getent group docker | cut -d: -f3)
export IRC_RELAY_ID=0b275a53fcec   # must match irc_relay_id in config.json
docker compose --profile irc up -d
```

Requests the bot does not need — including `containers/create` and `containers/{id}/exec`,
which are the usual paths from socket access to host root — are rejected by the proxy.

Without that profile the infrastructure cog cannot reach a daemon and disables
itself with a log warning; every other command is unaffected.

## Running without Docker

```bash
git clone https://github.com/mmcmd/verification-bot
cd verification-bot
python -m venv .venv
. .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[encryption,docker]"

cp config.json.example config.json
$EDITOR config.json

export DISCORD_TOKEN="..."
export LOG_ENCRYPTION_KEY="$(python -m verification_bot.logtools generate-key)"
python -m verification_bot
```

`python verif.py` still works for existing deployments.

## Logging and data retention

Log files are the only Discord data the bot writes outside Discord, so they are:

- **Encrypted at rest** with Fernet (AES-128-CBC + HMAC-SHA256), one token per
  record, keyed by `LOG_ENCRYPTION_KEY`. If no key is set the bot still runs but
  logs a loud warning that it is out of policy.
- **Rotated daily and deleted after `log_retention_days`** (default 14). The config
  loader refuses any value above 30 to stay inside Discord's retention policy.

The bot also writes a plaintext copy to stdout, which the container runtime persists
outside the encrypted volume. That sink runs through a redacting formatter: every
Discord ID is replaced with a per-process HMAC pseudonym, and no usernames are ever
logged, so container logs stay useful for debugging without carrying personal data.

Read the encrypted log back with:

```bash
docker compose exec bot python -m verification_bot.logtools decrypt /app/logs/verification.log
```

### Bot permissions

Invite the bot with `Manage Roles`, `Send Messages`, `Embed Links`, and — for the emergency
ping — `Mention @everyone, @here and All Roles`. Its highest role must sit **above** the
verified and colored roles it manages.

### Command registration

On startup the bot registers `/verify` globally (so it works in DMs) and every other command
directly to `homeserver_id`, which makes guild command updates appear instantly.

## Configuration

All keys live in `config.json`; see `config.json.example` for the full annotated list.
User-facing copy lives in `resources/messages.json` and can be edited without touching code.

Notable keys:

| Key | Meaning |
| --- | --- |
| `verification_requirement_join` | Account age (days) for automatic verification on join |
| `verification_requirement_message` | Account age (days) required for `/verify` |
| `emergency_request_approval_threshold` | Approvals needed to send the emergency ping |
| `emergency_request_deny_threshold` | Denials needed to reject a request |
| `emergency_role_reminder` / `emergency_role_timeout` | Reminder interval, and how many reminders before the request expires |
| `emergency_top_role_bypass_id` | Roles that may ping without approval |
| `nitro_role` | Hidden Nitro Booster role granted on boost; omit to disable |
| `irc_relay_id` | Docker container for `/irc`; omit to disable the cog |
| `log_retention_days` | Days of logs kept on disk (1–30, default 14) |

Secrets are never read from `config.json` in production. Set `DISCORD_TOKEN` /
`LOG_ENCRYPTION_KEY`, or their `_FILE` variants pointing at a mounted secret.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Project layout

```
verification_bot/
├── __main__.py        # CLI entry point
├── client.py          # Bot subclass, command tree, error handling, intents
├── config.py          # Config loading and validation
├── checks.py          # Reusable app-command checks
├── emergency.py       # Pure emergency vote state machine (unit tested)
├── logging_setup.py   # Encrypted, retention-bounded logging
├── logtools.py        # Key generation and log decryption CLI
├── embeds.py, utils.py
└── cogs/
    ├── verification.py, emergency.py, community.py,
    └── utility.py, infrastructure.py
```

## License

See [LICENSE](LICENSE).
