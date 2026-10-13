# Privacy Policy: /r/sysadmin verification bot

**Effective date: 12 October 2026**

This bot gives new members access to the /r/sysadmin Discord server, handles
emergency requests and keeps track of server boosts. It is run by the owner of
the /r/sysadmin Discord server, based in Canada, and works in that one server
only.

## What the bot looks at

- **Your account's creation date**, to work out how many days old your account
  is. That decides whether you are verified, when you run `/verify` or
  automatically when you join.
- **Your roles in the server**, to see whether you already have access and
  whether you may use a command or vote on an emergency request.
- **Whether you are boosting the server**, and since when.
- **Your user ID, name and avatar**, which appear in the records below.
- **The reason you type into `/emergency`.**
- **The member list.** While Discord grants the bot the Server Members
  permission, Discord sends it the server's member list (IDs, names, avatars,
  roles, join and boost dates) and tells it when someone joins or a member's
  details change. The bot uses this for three things: verifying people as
  they join, noticing when someone starts or stops boosting, and the
  `/boosters` list.

The bot does not receive messages posted in the server's channels, and does not
ask Discord for anyone's online status or activity.

**Direct messages.** If you send the bot a direct message, Discord delivers it
to the bot, which replies with a note telling you to use `/verify` (at most
once every 10 minutes). The bot does not read, log or store what you wrote.

## What is recorded inside Discord

- **The moderators' log channel**, a private channel that the server's
  moderators can read. The bot posts an entry when you are verified or refused
  (with your account's age in days), when you open or vote on an emergency
  request, when a moderator or administrator acts through the bot, and when
  something goes wrong that a moderator has to fix. An entry shows your user
  ID, name and avatar and what happened.
- **Emergency requests are public.** The reason you give is posted with your
  mention in the channel where you ran `/emergency`, and copied to the
  moderators' log channel.
- **Boosts.** `/boosters` shows, in the channel where it is run, who is
  boosting and since when. When you stop boosting, a notice with your name,
  user ID and avatar is posted in a channel chosen by the administrators.
- **Role changes.** When the bot gives or removes a role, Discord's own audit
  log for the server records it with a short reason, such as your account's
  age in days.
- Some public replies show "Requested by" with your name and avatar.

## What is kept outside Discord

The bot keeps no member data outside Discord. It writes two things on the
computer it runs on:

- **A service log.** Every Discord ID in it is scrambled: before a line is
  written, each ID is replaced by a random-looking code that changes every time
  the bot restarts and cannot be turned back into the ID by someone reading the
  log. The bot does not write names or emergency reasons to it.
- **A settings file**, holding server settings only: role IDs, channel IDs, the
  ID of the Moderator Mail account, a few numbers such as the age limits, and
  the bot's status text.

The member list, a pending emergency request (who asked, the reason, who voted)
and short timers, such as when the bot last replied to your direct message,
live in the bot's memory only. They are never written to a file and are gone
when the bot stops.

## Sharing

Nothing is sold, shared with third parties, or used to train AI.

## Deleting your data

Send a message to **Moderator Mail** in the /r/sysadmin server (the account at
the top of the member list) and say what you want removed. Within 30 days we
will delete what the bot recorded about you, including entries in the
moderators' log channel, unless an entry is needed for an open moderation
matter. Discord's own audit log is kept by Discord and we cannot edit it.

## Children

The bot is not meant for anyone under 13, and we do not knowingly handle data
about anyone under 13.

## Changes to this policy

If this policy changes, the new text replaces this page and the effective date
at the top is updated.

## Contact

Moderator Mail in the /r/sysadmin Discord server.
