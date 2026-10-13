# verification-bot (for /r/sysadmin)

A Discord bot for the [/r/sysadmin](https://www.reddit.com/r/sysadmin/) Discord server
(about 25,000 members). It runs in that one server only.

## What the bot does

- **Verification by account age.** A new member runs `/verify`, and if their Discord
  account is old enough the bot gives them the verified role. Accounts that are older still
  are verified automatically the moment they join.
- **Emergency requests.** A verified member runs `/emergency` with a reason. Members who are
  allowed to vote press Approve or Deny buttons. If enough approve, the bot pings the
  emergency role. Certain roles can skip the vote.
- **Boost tracking.** When a member starts boosting the server the bot thanks them and gives
  them the booster role. When they stop, it announces it and takes the booster and colour
  roles away. `/boosters` lists the current boosters.
- **Moderator tools.** `/clearemergency`, `/irc` (control the IRC relay container) and
  `/config` (change the bot's settings from Discord).

Every feature is a Discord slash command. If you DM the bot, it replies with a hint to run
`/verify` (at most once per 10 minutes per person) and never reads what you wrote.

## Requirements

- Python 3.9 or newer.
- A Discord application with a bot user, made in the
  [Discord Developer Portal](https://discord.com/developers/applications).
- The **Server Members** intent switched on for that bot. An "intent" is a permission that
  tells Discord which kinds of events the bot is allowed to receive. Server Members is the
  only privileged intent the bot uses (it is how the bot sees joins and boosts). **Presence**
  and **Message Content** must stay off; the bot never needs them.
  Discord requires apps that reach 10,000 users to pass a review to keep privileged intents.
  See [docs/discord-intent-application.md](docs/discord-intent-application.md).
- Docker, but only if you want the `/irc` command. `/irc` talks to the Docker service on the
  machine the bot runs on, and the user running the bot must be allowed to use it (be in the
  `docker` group).

The bot needs these permissions in the server: Manage Roles, Send Messages and Embed Links,
plus Mention All Roles if the emergency role is not set to "allow anyone to mention". Its
highest role must sit **above** the verified, booster and colour roles it hands out.

## Setup

```bash
git clone https://github.com/mmcmd/verification-bot
cd verification-bot
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp config.json.example config.json
$EDITOR config.json
python verif.py
```

`config.json` holds the three things the bot needs before it can connect:

| Key | What it is for |
| --- | --- |
| `token` | The bot's password for Discord, from the Developer Portal. Keep it secret. Instead of writing it in the file you can leave it empty and set the `DISCORD_TOKEN` environment variable. |
| `homeserver_id` | The ID of the server the bot works in. The bot's server commands are registered only there. (Turn on Developer Mode in Discord, then right-click the server and choose Copy Server ID.) |
| `irc_relay_id` | The Docker container that `/irc` controls. Use the container's **name**, not its ID: an ID changes every time the container is recreated, a name does not. Leave it empty to switch `/irc` off. |

Never commit `config.json`; it is listed in `.gitignore`.

After the bot has started, go to your server and run `/config show`. It lists every setting
and marks the ones that are not set yet. Fill them in with the `/config` commands described
below. Only members with the Administrator permission can use `/config`.

## Configuration

There are two files, with different jobs.

| File | Who writes it | What is in it |
| --- | --- | --- |
| `config.json` | You, by hand | Only `token`, `homeserver_id` and `irc_relay_id`: what the bot needs before it can connect. |
| `data/settings.json` | The bot | Everything else: role IDs, channel IDs, numbers and the status text. It holds no information about any member. You normally never edit it; `/config` does. |

Changes made with `/config` apply immediately, with no restart. Each change is posted to the
mod-log channel, saying who changed what. The file is written safely (a crash never leaves a
half-written file). `data/` is git-ignored.

### The `/config` commands

All replies are visible only to the person who ran the command.

| Command | What it does |
| --- | --- |
| `/config show` | Lists every setting, and flags any single role, channel, category or user that is unset, and anything pointing to a role or channel that was deleted. An empty list of roles is allowed and is not flagged. |
| `/config role setting role` | Sets a setting that holds one role. |
| `/config channel setting channel` | Sets a setting that holds a text channel. |
| `/config category setting category` | Sets a setting that holds a channel category. |
| `/config user setting user` | Sets a setting that holds a user or bot. |
| `/config number setting value` | Sets a number, such as an age in days or a vote count. |
| `/config status text` | Changes the "Playing ..." text under the bot's name. |
| `/config role-add setting role` | Adds a role to a setting that holds a list of roles. |
| `/config role-remove setting role` | Removes a role from such a list. |
| `/config role-prune setting` | Removes deleted roles from such a list. |
| `/config clear setting` | Unsets a setting, so it goes back to its default (or to nothing). |

### The settings

A setting that is unset makes the commands that need it say that an administrator has to run
`/config`. The bot still starts.

| Setting | What it is for | Default |
| --- | --- | --- |
| Verified role | The role the bot gives to a member once they are verified. | none |
| Moderator roles | Roles that may use the moderator commands (`/clearemergency`, `/irc`). | none |
| Sudo voter roles | Roles that may approve or deny an emergency request. While empty, anyone whose top role is above the verified role may vote. | none |
| Emergency bypass roles | Roles whose `/emergency` pings straight away, with no vote. | none |
| Emergency role | The role that gets pinged when an emergency is approved. | none |
| Booster role | The role given to members while they boost the server. | none |
| Colour roles | Booster-only colour roles, taken away when a member stops boosting. | none |
| Mod-log channel | The private channel where the bot records what it did and what went wrong. | none |
| Unboost channel | The channel where the bot announces that a member stopped boosting. | none |
| Rules channel | Linked in the message a member gets after verifying. | none |
| Roles channel | The self-assignable roles channel, linked in the verification and boost messages. | none |
| Booster channel | The boosters-only channel, linked in the boost thank-you message. | none |
| On-topic category | The channel category in which `/emergency` may be used. | none |
| Moderator Mail user | The mod-mail bot that members are told to contact. While unset, the bot's owner is named instead. | none |
| Join age threshold (days) | Accounts older than this many days are verified automatically when they join. | 90 |
| /verify age threshold (days) | Accounts must be at least this many days old for `/verify` to work. | 5 |
| Emergency approval threshold | How many approvals an emergency request needs. | 3 |
| Emergency denial threshold | How many denials reject an emergency request. | 2 |
| Emergency reminder interval (seconds) | How long the bot waits between reminders about a pending request. | 180 |
| Emergency reminder count | How many reminders are sent before a pending request times out. | 5 |
| Status text | The "Playing ..." text shown under the bot's name. | `/verify to get access` |

### Importing from an old-style `config.json`

The first time the bot starts and finds no settings file, it creates one from the old-style
`config.json` (the one with keys such as `verified_role`, `log_channel_id` and
`moderator_role_IDs`), so nothing has to be retyped. Old numbers written as text are
accepted; a value that does not fit is skipped with a note in the log rather than stopping the
bot. If the old `status` is "message me to get verified!" it is replaced with
`/verify to get access`. If `homeserver_id` is the /r/sysadmin server, the rules, roles and
booster channels that the old bot had written into its source code are filled in too.
After the import the extra keys in `config.json` are ignored. Deleting `data/settings.json`
makes the bot import again on the next start.

### Command-line options

| Option | Meaning | Default |
| --- | --- | --- |
| `--config PATH` | The `config.json` file. | `config.json` |
| `--settings PATH` | The settings file the bot writes. | `data/settings.json` |
| `--messages PATH` | The file with the bot's wording. | `resources/messages.json` |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. | `INFO` |

## Commands

"Home server" means the server in `homeserver_id`. A command that works in DMs is registered
globally; the rest are registered only in the home server. `/help` shows the same grouping,
built from the commands that are actually registered.

| Command | Who can use it | Where | What it does |
| --- | --- | --- | --- |
| `/verify` | Anyone | DM or server | Gives the verified role if the account is old enough. |
| `/help` | Anyone | DM or server | Lists the commands, in sections for each kind of member. |
| `/privacy` | Anyone | DM or server | Short summary of how the bot handles data, the policy link and how to ask for deletion. |
| `/emergency reason` | Verified members, in the on-topic category | Server | Asks for the emergency role to be pinged. The reason (20 to 500 characters) is shown publicly. One request at a time; 120 second cooldown. |
| `/clearemergency` | Moderators | Server | Cancels the pending emergency request. |
| `/boosters` | Anyone | Server | Lists current boosters. |
| `/ping` | Anyone | Server | Shows the bot's connection delay. |
| `/uptime` | Anyone | Server | Shows how long the bot has been running. |
| `/github` | Anyone | Server | Link to this project's source code. |
| `/steve` | Anyone | Server | Summons Steve. |
| `/irc action` | Moderators | Server | Status, start, stop or restart of the IRC relay container (`status`, `start`, `stop`, `restart`). Only exists when `irc_relay_id` is set. |
| `/config ...` | Administrators | Server | Changes the settings (see above). |

Moderators are members with one of the "Moderator roles", or anyone with the Administrator
permission. Administrators are members with Discord's Administrator permission.

## Reduced mode

Reduced mode is what the bot does when Discord will not let it use the Server Members intent.
This happens if the intent is switched off in the Developer Portal, or if Discord has removed
it from the app (for example after a missed intent review).

Instead of stopping, the bot connects one more time without the intent, and posts one warning
to the mod-log channel. In reduced mode these are **off**: verifying automatically when a
member joins, the boost thank-you and booster role, the cleanup when someone stops boosting,
and `/boosters` (it answers that it is temporarily unavailable). Everything that is a command
keeps working, including `/verify`.

Full mode comes back by itself: once the intent is allowed again, restart the bot
(`sudo systemctl restart verificationbot`). No setting needs to change.

## Running as a service

On Linux the bot is meant to run under systemd, which starts it at boot and restarts it after a
crash. The file `deploy/verificationbot.service` is set up for the user `massimo` and the folder
`/home/massimo/verification-bot` with a virtual environment in `.venv`; edit those lines if
yours differ.

```bash
sudo cp deploy/verificationbot.service /etc/systemd/system/verificationbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now verificationbot
journalctl -u verificationbot -f        # watch the log
```

If an older unit with the same name exists in `/usr/lib/systemd/system/`, the copy in
`/etc/systemd/system/` takes precedence over it.

### Why the restart rules are strict

Discord resets a bot's token after 1000 connections in 24 hours. An earlier service file
restarted the bot every second with no limit, used up those connections, and then kept trying
with the dead token. So this service restarts only after a crash, waits 30 seconds first, allows
at most 5 starts per hour, and never restarts after a problem that restarting cannot fix.

If the limit is reached systemd gives up. Find out why (`journalctl -u verificationbot`), then:

```bash
sudo systemctl reset-failed verificationbot
sudo systemctl start verificationbot
```

### Exit codes

| Code | Meaning | Restarted by the service? |
| --- | --- | --- |
| 0 | Clean stop (Ctrl+C or `systemctl stop`). | No (it was asked to stop) |
| 1 | Unexpected crash. | Yes, after 30 seconds, within the limit |
| 2 | `config.json`, `messages.json` or the settings file is missing or broken. | No |
| 3 | Discord rejected the token. | No |
| 4 | Discord refused the connection even in reduced mode. | No |

## Logging and privacy

- The bot logs to standard output only. Under systemd that is the service log
  (`journalctl -u verificationbot`). There is no log file.
- Every Discord ID in the log is replaced by a scrambled stand-in that changes on each run.
  Usernames, the text of DMs and emergency reasons are never logged.
- Problems a moderator has to act on (a role that could not be given, an unexpected command
  error) are posted to the mod-log channel with the real member mention, because the service
  log is deliberately unreadable in that respect.
- Outside Discord the bot stores no member data. The member list, the pending emergency request
  and the DM reminder timers live in memory only.

See [PRIVACY.md](PRIVACY.md) for the full policy.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

The `dev` extra installs `pytest`, `pytest-asyncio`, `ruff` and `docker` (the `/irc` tests use
the real `docker` package with a fake client). The tests never connect to Discord and need no
token. Supported Python versions: 3.9 and newer; CI tests 3.9 and 3.12.

Continuous integration: `.github/workflows/ci.yml` runs `ruff check .` and `pytest` on Python
3.9 and 3.12 for every push to `master` and every pull request.

For the differences from the old single-file bot, see [docs/change-guide.md](docs/change-guide.md).

### Project layout

```
verif.py                       Entry point (runs verification_bot.__main__.main)
config.json.example            The three keys config.json needs
deploy/verificationbot.service systemd unit
resources/messages.json        The bot's wording
verification_bot/
    __main__.py                Command line, exit codes, reduced-mode restart
    client.py                  The bot class: intents, command registration, error handling
    config.py                  Loads config.json and messages.json
    settings.py                The settings table, the settings file, the old-config import
    checks.py                  Who may use which command
    emergency.py               The emergency vote rules (no Discord code, unit tested)
    logging_setup.py           Standard-output logging with scrambled IDs
    embeds.py, utils.py        Message formatting helpers
    cogs/
        verification.py        /verify, auto-verify on join, DM hint
        emergency.py           /emergency, /clearemergency
        community.py           Boost tracking, /boosters
        utility.py             /ping, /uptime, /github, /steve, /help, /privacy
        infrastructure.py      /irc
        settings.py            /config
tests/                         pytest suite
```

## Licence

See [LICENSE](LICENSE).
