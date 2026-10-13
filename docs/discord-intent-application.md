# Discord Privileged Intent application: answers ready to paste

## Read this first

**What this form is for.** An "intent" is a permission Discord grants a bot to
receive a category of events. Three of them are "privileged", meaning Discord
wants a reason before a large bot may have them: Server Members (who joins,
whose roles or boost status change, and the member list), Presence (who is
online) and Message Content (the text of messages). Because the bot serves a
server with more than 10,000 members, Discord now reviews its privileged
intents, and reviews them again every year. This form is that review.

**We are applying for Server Members only.** The new bot does not use Presence
or Message Content at all.

**Where the form is.** In the Discord Developer Portal
(<https://discord.com/developers/applications>), open the bot's application.
We could not record the exact page: look on the **Bot** page next to the
"Privileged Gateway Intents" switches, or for a banner or button about intent
review. Discord's own guide is at
<https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review>.

**The real form may look different.** The list of questions below was read out
of the Developer Portal's program code, not from the form on screen. The
wording, the order or the limits may differ a little. If a question appears
that is not covered here, answer it truthfully in your own words, or stop and
ask before submitting.

**Leave Presence and Message Content UNTICKED.** The form warns that intents
you do not select are lost when the submission is reviewed. That is what we
want: the new bot never asks Discord for them.

**The answers describe the NEW bot.** Do these three things before you submit:

1. Have the new code running in production (it may be running in reduced mode;
   that is fine).
2. Merge the pull request into `master`. The privacy link below points at
   `master`, and until the merge it still shows the OLD policy, which is wrong.
   Open the link yourself and check that it shows "Effective date: 12 October
   2026".
3. Enter the same link in the Developer Portal's **Privacy Policy URL** field
   (normally on the application's **General Information** page). Discord's
   Developer Terms, section 5(a), require every app to have its privacy policy
   linked there.

Each answer below is in a grey box. Copy everything inside the box and nothing
else. The character counts were measured by a script and include line breaks.

---

## 1. What does your application do?

**Form wording:** "What does your application do? Please be as detailed as
possible, and feel free to include links to image or video examples."

**Limit:** 50 to 2000 characters. **This answer:** 1972 characters.

```text
This is a private bot for one server only: the /r/sysadmin Discord server (about 25,000 members). It lets new members in without phone verification while keeping throwaway accounts out.

- Verification by account age. A new member runs the /verify slash command, in the server or in a DM with the bot. If their Discord account is at least a set number of days old, the bot gives them the "verified" role, which unlocks the server. Accounts older than a separate threshold get the role automatically when they join.

- Emergency requests. A verified member can run /emergency with a written reason, asking for the server's emergency role to be pinged about a production outage. Senior members (ranked above the verified role, or in roles the administrators choose) vote with Approve and Deny buttons, and the role is pinged only if enough approve. Roles the administrators choose can ping without a vote.

- Boost tracking. When a member starts boosting, the bot gives them the booster role and sends a thank-you DM. When they stop, it removes the booster and colour roles and posts a notice in a channel chosen by the administrators. /boosters lists the current boosters.

- Moderator tools. /clearemergency cancels a pending request, /irc controls the server's IRC relay, and /config lets administrators choose the roles, channels and thresholds. Its actions are recorded in a private moderator channel inside Discord.

- /help, /privacy and small utilities such as /ping and /uptime.

Every command is a slash command. The bot requests the Guilds, Direct Messages and Server Members intents only, not Message Content or Presence.

The only thing the bot keeps outside Discord is the server's own settings file: role IDs, channel IDs, the ID of the server's Moderator Mail account, a few numbers and the status text. It holds no member data. Its service log shows only scrambled IDs, never names or message text. The member list is held in memory only while the bot runs.
```

---

## 2. Privacy policy

**Form wording:** "Do you have a public Privacy Policy telling your users about
their data usage?"

**Answer:** Yes.

### 2a. Where is your Privacy Policy available?

**Limit:** 25 to 2000 characters. **This answer:** 526 characters.

```text
The bot's /privacy slash command shows a summary of the policy, how to ask for deletion, and the link to the full text. It works both in the server and in a direct message with the bot, and the reply is visible only to the person who ran it. The /help command lists /privacy, and its footer tells people to run /privacy to see what data the bot handles. The full policy is published at https://github.com/mmcmd/verification-bot/blob/master/PRIVACY.md and the same link is set as the Privacy Policy URL in the Developer Portal.
```

Note: the last sentence is only true once you have done step 3 under "Read
this first".

### 2b. Please share a link to your Privacy Policy.

**This answer:** 64 characters.

```text
https://github.com/mmcmd/verification-bot/blob/master/PRIVACY.md
```

---

## 3. Intent checkboxes

- **Server Members: TICK**
- **Presence: leave unticked**
- **Message Content: leave unticked**

---

## 4. Why do you need the Guild Members intent?

**Form wording:** "Why do you need the Guild Members intent?" with the hint
"Please describe the feature you're building using this intent with as much
detail as possible." ("Guild" is Discord's technical word for a server; this is
the Server Members intent.)

**Limit:** not known; we kept the answer under 2000 characters to be safe. If
the form refuses it as too long, shorten the second-to-last paragraph ("To be
straightforward about caching") rather than deleting it; that paragraph and the
last one are what the reviewers look for.
**This answer:** 1923 characters.

```text
The bot serves one server, /r/sysadmin (about 25,000 members). Three features need the Guild Members intent and cannot be built from slash commands or single-member lookups:

1. Verifying members as they join. The bot listens for the member-join event. If the new member's account is older than the server's threshold, the bot gives them the verified role at once, so members with established accounts get access without doing anything. This event is the only way the bot learns that someone has joined.

2. Boosts and unboosts. The bot listens for the member-update event and compares the member's boost date before and after. When a boost starts, it adds the booster role and sends a thank-you DM. When a boost ends, it removes the booster role and the booster-only colour roles and posts a notice in a channel chosen by the administrators. No command triggers this; the bot has to react to the event.

3. The booster list. /boosters shows everyone currently boosting and the date each boost began. It is built by filtering the member list for members who have a boost date.

To be straightforward about caching: the bot loads the full member list into memory at startup. It does so because the library it uses (discord.py) only passes on a member-update event for a member it already has loaded, so a boost or unboost by a member who was not loaded would be missed, and because the booster list is computed from that list. The list is held in memory only. It is never written to disk, never sent outside Discord, and it is gone when the bot stops.

What does not depend on the intent: /verify looks up only the one member who ran it. Emergency votes and the permission checks for moderator and administrator commands use the member data Discord includes with each interaction. If the intent is not granted, the bot starts in a reduced mode: those commands keep working and only the three features above are switched off.
```

---

## 5. Screenshots

**Form wording:** "Please provide links to screenshots and/or videos that
demonstrate your use case" (required for each intent you ticked, showing it
working in a server).

The form wants **links**, so each picture has to be uploaded somewhere that
gives a link which opens without logging in and does not expire. Replace each
slot below with your link. Paste one link per line.

```text
[SCREENSHOT LINK 1: member verified automatically on join]
[SCREENSHOT LINK 2: unboost notice]
[SCREENSHOT LINK 3: the booster list]
[SCREENSHOT LINK 4 (optional): boost thank-you DM]
```

What each picture should show:

- **Link 1, automatic verification on join (the most important one).** One
  entry from the moderators' log channel saying a member was verified when
  they joined. From the new bot the entry has the title **"Member
  auto-verified"** and the text "@member was verified on join because the
  account is N days old." An entry from the old bot is also fine; it has no
  title and reads "@member has been verified automatically because his account
  age is over the verification threshold (N days)".
- **Link 2, unboost notice.** One entry from the unboost channel saying a
  member stopped boosting. From the new bot it has the title **"Server
  unboosted"** and the text "@member (ID) unboosted the server." From the old
  bot it has the same sentence and no title. If you cannot find one, leave this
  slot out; links 1 and 3 already show the intent in use.
- **Link 3, the booster list.** The bot's reply to `/boosters`. From the new
  bot it is titled **"Server boosters"**, starts with a line like "N boost(s)
  from M member(s). Current tier: T." and then lists each booster with
  "boosting since" and a date. From the old bot (the `+boosters` command) it is
  titled "There are currently N people boosting the server. Current tier: T".
- **Link 4, optional.** The direct message the bot sends to a new booster,
  beginning "Thank you for boosting /r/sysadmin!". Only you or another booster
  would have one.

Things to know:

- Old log entries were made by the old bot and look slightly different from
  what the new bot posts, as described above. That is fine: they show the same
  features. If you would rather show the new bot, links 1 and 3 can be made
  fresh in the test server with the test bot while its Server Members switch is
  on: have a second account join (one older than the join age threshold in the
  test settings) to get the "Member auto-verified" entry, and run `/boosters`.
- These pictures show other people. Where you can, crop the picture to the one
  entry, and blur the names, avatars and ID numbers of anyone but yourself. In
  the booster list, blurring the names still leaves the layout and the dates
  visible, which is all the reviewer needs.
- Do not include a picture that shows the bot's token or the config file.

---

## 6. Off-platform storage

**Form wording:** "Are you storing any API Data off-platform (outside of
Discord)?"

**Answer:** No.

Why "No" is the honest answer, in case you are asked: the bot keeps nothing
about members outside Discord. Its settings file holds only the server's own
configuration (role IDs, channel IDs, the ID of the Moderator Mail account, a
few numbers and the status text), and answer 1 says so openly. Its log, which
the server's service manager captures, has every Discord ID replaced by a
scrambled code and the bot does not write usernames to it. The moderators' log
with real names lives in a channel inside Discord, not on our computer. The
member list exists only in the bot's memory while it runs.

The form has three follow-up questions that should appear **only** if you
answer "Yes". With "No" selected you should not see them. If the form shows
them anyway, first check that "No" is really selected. If they are still
required, answer like this:

- **"Are you storing API Data for 30 days or less?"** Yes. (Nothing about
  members is stored at all.)
- **"How do users contact you to request deletion of their activity data?"**
  Paste:

  ```text
  Members send a message to Moderator Mail in the /r/sysadmin Discord server (the account at the top of the member list). Requests are handled within 30 days. The /privacy command tells members this.
  ```

  (197 characters.)
- **"Are you encrypting the data that you store at rest, as is required by our
  developer policy?"** Be careful here. The bot does not encrypt anything,
  because it stores no member data: the only file it writes is the settings
  file, which is plain text and, as the bot writes it, readable only by the
  account the bot runs under. Do not answer "Yes" unless the disk of the server itself is encrypted,
  which only you know. If there is a text box, write: "No API data about users
  is stored. The only file is the server's settings file (role and channel
  IDs), which is not encrypted." If there is only Yes or No and no way to
  explain, stop and ask Discord's developer support rather than guess.

---

## 7. Certification checkbox

The last box asks you to certify that the answers are accurate and complete.
Before you tick it, read answers 1, 2 and 4 once more against the bot you are
actually running. In particular check that:

- the new bot, not the old `verif.py` from `master`, is the one in production;
- `/privacy` and `/help` answer in the server;
- the privacy link opens the new policy;
- Presence and Message Content are unticked on the form and switched off on the
  Bot page of the Developer Portal;
- the Moderator Mail account named in the settings is the server's mod-mail
  bot (run `/config show` to see it).

---

## After you submit

- **Until Discord approves, the bot runs in reduced mode.** The review window
  was missed, so Discord has most likely already switched the Server Members
  intent off. In reduced mode every command works, including `/verify`. What
  is off: automatic verification on join, the boost thank-you and booster
  role, the cleanup when someone stops boosting, and `/boosters`. The bot
  posts one warning about this in the moderators' log channel when it starts.
- **When Discord approves:** check that the Server Members switch is on in the
  Developer Portal (Bot page), then restart the bot once with
  `sudo systemctl restart verificationbot`. No setting needs to change. The
  log should then say "Running in FULL mode", and `/config show` should say
  "Mode: full".
- **The review repeats every year.** Put a reminder in your calendar. Missing
  it is what switched the intent off this time. Keep this file: next year's
  answers will be nearly the same.
