# Privacy Policy — /r/sysadmin Verification Bot

_Last updated: 2026-09-10_

This policy describes what data the /r/sysadmin Verification Bot ("the bot") receives from
Discord, what it does with it, and how long it is kept. The bot is operated by the moderator
team of the /r/sysadmin Discord server. Its source code is public at
<https://github.com/mmcmd/verification-bot>.

## 1. What the bot receives

The bot connects to the Discord gateway with the following intents:

| Intent | Enabled | Purpose |
| --- | --- | --- |
| Guilds | Yes | Resolve channels, roles and categories. |
| Guild Members (privileged) | Yes | Join events, role assignment, Nitro boost state. |
| Direct Messages | Yes | Reply to a DM with instructions to run `/verify`. |
| Message Content (privileged) | **No** | Not requested. The bot never reads message text. |
| Presence (privileged) | **No** | Not requested. The bot never reads status or activity. |

From those intents the bot processes:

- Your Discord user ID, username and avatar URL.
- Your account creation date, which is derived from your user ID (Discord snowflake).
- Your roles in the /r/sysadmin server and your server join date.
- Your Nitro boost start date for the /r/sysadmin server.
- The text you type into a slash command option (for example the `reason` field of
  `/emergency`), which you supply deliberately and which is posted publicly in the channel
  where you used the command.

The bot does **not** read message content, attachments, presence, status, activity, voice
state, or any data from servers other than /r/sysadmin.

## 2. What the bot stores

| Data | Where | Retention |
| --- | --- | --- |
| Audit log entries (user ID, username, avatar URL, action taken, timestamp) | A private moderator channel inside Discord | Until moderators delete the channel history |
| Application log file on the host (same fields as above) | `logs/verification.log` on the moderators' server, **encrypted at rest** | Rotated daily and deleted after **14 days**; the software refuses any retention setting above 30 days |

Emergency requests and their votes are held in memory only and are discarded when the request
is resolved or the bot restarts.

No message content is stored anywhere. No data is sold, shared with third parties, used for
advertising, or used to train machine learning or AI models.

## 3. Encryption at rest

The log file is encrypted record-by-record with Fernet (AES-128-CBC with HMAC-SHA256
authentication) before it touches the disk. In our deployment the key is supplied as a
mounted Docker secret; the software also accepts it from the `LOG_ENCRYPTION_KEY`
environment variable for non-containerised installations. The key is never stored in the
container image or the source repository. Anyone who obtains the log volume without the key
gets only ciphertext. The host volume additionally sits on an encrypted filesystem.

The application also emits a plaintext operational log to standard output, which the
container runtime stores outside the encrypted volume. That output is passed through a
redacting formatter that replaces every Discord ID with a per-process HMAC pseudonym, and no
usernames are written to logs at all, so this sink contains no data that identifies a user.

## 4. Where the data lives

The bot runs on a private server controlled by the /r/sysadmin moderator team. Log files are
the only data stored outside Discord. Access is restricted to
moderators who administer the host.

## 5. Your choices and rights

- Using the bot is optional. `/verify` and every other command are opt-in actions you take
  deliberately; the bot never acts on your messages.
- You may request a copy or the deletion of any data the bot holds about you by contacting the
  moderator team through **Moderator Mail** in the /r/sysadmin server (top of the member
  list), or by opening an issue at <https://github.com/mmcmd/verification-bot/issues>.
- Deletion requests are acknowledged within 7 days and completed within 30 days. In practice
  all off-platform data ages out automatically within 14 days regardless.
- Leaving the server also causes your data to age out of the log rotation.

## 6. Children

The bot is reachable only from within Discord — in the /r/sysadmin server, and in direct
messages with the bot for the `/verify` command. Discord requires all users to be at least
13 years old (or older where local law requires). The bot does not knowingly process data
belonging to anyone below that age.

## 7. Changes

Material changes to this policy will be announced in the /r/sysadmin server and committed to
the public repository, so the full history of this document is auditable.

## 8. Contact

Moderator Mail in the /r/sysadmin Discord server, or
<https://github.com/mmcmd/verification-bot/issues>.
