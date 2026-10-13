from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands

from verification_bot import checks
from verification_bot.client import VerificationBot
from verification_bot.cogs.settings import BLOCK_LIMIT, Settings
from verification_bot.config import load_messages
from verification_bot.settings import SETTINGS, SettingKind, SettingsStore

from .conftest import HOME_SERVER_ID, SETTINGS_VALUES

ADMIN_ID = 900

#: Channels that exist in the fake server: the five channel settings.
TEXT_CHANNEL_IDS = (6, 7, 8, 9, 12)
CATEGORY_ID = 13


def make_role(role_id, *, managed=False, default=False):
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.mention = f"<@&{role_id}>"
    role.managed = managed
    role.is_default.return_value = default
    return role


def make_text_channel(channel_id):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.send = AsyncMock()
    return channel


def make_admin(*, administrator=True, guild_id=HOME_SERVER_ID, roles=()):
    member = MagicMock(spec=discord.Member)
    member.id = ADMIN_ID
    member.mention = f"<@{ADMIN_ID}>"
    member.roles = list(roles)
    member.guild_permissions.administrator = administrator
    member.display_avatar.url = "https://example.invalid/a.png"
    member.guild.id = guild_id
    return member


@pytest.fixture
def world(bot, monkeypatch):
    """The home server with every role, channel and category of the test settings."""
    role_ids = [
        value
        for key, spec in SETTINGS.items()
        if spec.kind in (SettingKind.ROLE, SettingKind.ROLE_LIST)
        for value in (
            SETTINGS_VALUES[key]
            if isinstance(SETTINGS_VALUES[key], tuple)
            else (SETTINGS_VALUES[key],)
        )
    ]
    roles = {role_id: make_role(role_id) for role_id in role_ids}
    channels = {channel_id: make_text_channel(channel_id) for channel_id in TEXT_CHANNEL_IDS}
    category = MagicMock(spec=discord.CategoryChannel)
    category.id = CATEGORY_ID
    channels[CATEGORY_ID] = category

    guild = MagicMock(spec=discord.Guild)
    guild.id = HOME_SERVER_ID
    guild.me = None  # the bot's own member; tests that need it set it themselves
    guild.get_role.side_effect = roles.get
    guild.get_channel_or_thread.side_effect = channels.get
    guild.roles = [make_role(HOME_SERVER_ID, default=True), *roles.values()]

    monkeypatch.setattr(bot, "get_guild", lambda guild_id: guild)
    monkeypatch.setattr(bot, "get_channel", channels.get)
    return MagicMock(guild=guild, roles=roles, channels=channels, mod_log=channels[6])


def make_interaction(bot, world=None, *, user=None):
    interaction = MagicMock()
    interaction.client = bot
    interaction.user = user or make_admin()
    interaction.guild = world.guild if world is not None else None
    interaction.guild_id = HOME_SERVER_ID
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def reply_of(interaction):
    return interaction.followup.send.await_args.kwargs["content"]


def sends_of(interaction):
    return [call.kwargs for call in interaction.followup.send.await_args_list]


def show_text(interaction):
    """Everything ``/config show`` sent: the summary plus every embed."""
    parts = []
    for kwargs in sends_of(interaction):
        if kwargs.get("content"):
            parts.append(kwargs["content"])
        parts.append(kwargs["embed"].description)
    return "\n\n".join(parts)


def block_of(text, label):
    """The part of the ``/config show`` output that is about one setting."""
    start = text.index(f"**{label}:**")
    end = text.find("\n\n", start)
    return text[start:] if end == -1 else text[start:end]


def subcommands():
    return [c for c in Settings.config.walk_commands() if isinstance(c, app_commands.Command)]


# -- access control -----------------------------------------------------------


def test_every_subcommand_is_for_administrators_only():
    commands = subcommands()
    assert commands
    for command in commands:
        assert checks.audience_of(command) is checks.Audience.ADMINISTRATOR, command.name
    assert checks.audience_of(Settings.config) is checks.Audience.ADMINISTRATOR


def test_discord_hides_the_group_from_non_administrators():
    group = Settings.config
    assert group.default_permissions is not None
    assert group.default_permissions.administrator
    assert group.guild_only


def _predicates():
    return [check for command in subcommands() for check in command.checks]


def test_the_check_accepts_an_administrator_in_the_home_server(bot):
    interaction = make_interaction(bot)
    for predicate in _predicates():
        assert predicate(interaction) is True


@pytest.mark.parametrize(
    "case", ["not an admin", "moderator role only", "admin elsewhere", "direct message"]
)
def test_the_check_rejects_everyone_else(bot, case):
    interaction = make_interaction(bot)
    if case == "not an admin":
        interaction.user = make_admin(administrator=False)
    elif case == "moderator role only":
        moderator_role = make_role(SETTINGS_VALUES["moderator_roles"][0])
        interaction.user = make_admin(administrator=False, roles=[moderator_role])
        assert checks.is_moderator(interaction)  # a moderator, yet not enough
    elif case == "admin elsewhere":
        interaction.user = make_admin(guild_id=777)
        interaction.guild_id = 777
    else:
        interaction.user = MagicMock(spec=discord.User)
        interaction.guild_id = None

    predicates = _predicates()
    assert len(predicates) == len(subcommands())
    for predicate in predicates:
        with pytest.raises(checks.MissingAdministrator):
            predicate(interaction)


async def test_the_cog_itself_also_refuses_non_administrators(bot):
    cog = Settings(bot)
    assert await cog.interaction_check(make_interaction(bot)) is True
    with pytest.raises(checks.MissingAdministrator):
        await cog.interaction_check(
            make_interaction(bot, user=make_admin(administrator=False))
        )


# -- registration -------------------------------------------------------------


async def test_the_config_group_is_registered_within_discords_limits(loaded_bot):
    group = {command.name: command for command in loaded_bot.all_app_commands()}["config"]
    assert isinstance(group, app_commands.Group)
    assert 0 < len(group.commands) <= 25
    assert "show" in {command.name for command in group.commands}
    for command in group.walk_commands():
        assert command.description and len(command.description) <= 100
        for parameter in command.parameters:
            assert parameter.name == parameter.name.lower()
            assert len(parameter.description) <= 100
            assert len(parameter.choices) <= 25
            for choice in parameter.choices:
                assert len(choice.name) <= 100


async def test_config_goes_to_the_home_server_not_global(loaded_bot):
    loaded_bot._assign_command_scopes()
    assert "config" not in {command.name for command in loaded_bot.tree.get_commands()}
    home = discord.Object(id=HOME_SERVER_ID)
    assert "config" in {command.name for command in loaded_bot.tree.get_commands(guild=home)}


def test_pick_lists_are_built_from_the_settings():
    by_name = {command.name: command for command in subcommands()}

    def offered(name):
        parameter = next(p for p in by_name[name].parameters if p.name == "setting")
        return {choice.value for choice in parameter.choices}

    def keys(kind):
        return {key for key, spec in SETTINGS.items() if spec.kind is kind}

    assert offered("role") == keys(SettingKind.ROLE)
    assert offered("channel") == keys(SettingKind.CHANNEL)
    assert offered("category") == keys(SettingKind.CATEGORY)
    assert offered("user") == keys(SettingKind.USER)
    assert offered("number") == keys(SettingKind.INTEGER)
    for name in ("role-add", "role-remove", "role-prune"):
        assert offered(name) == keys(SettingKind.ROLE_LIST)
    assert offered("clear") == set(SETTINGS)
    # Every setting can be changed by some subcommand.
    assert keys(SettingKind.TEXT) == {"status_text"}


def test_values_are_chosen_with_discords_pickers():
    by_name = {command.name: command for command in subcommands()}

    def option(command, name):
        return next(p for p in by_name[command].parameters if p.name == name)

    assert option("role", "role").type is discord.AppCommandOptionType.role
    assert option("role-add", "role").type is discord.AppCommandOptionType.role
    assert option("channel", "channel").type is discord.AppCommandOptionType.channel
    assert option("channel", "channel").channel_types == [
        discord.ChannelType.text,
        discord.ChannelType.news,
    ]
    assert option("category", "category").channel_types == [discord.ChannelType.category]
    assert option("user", "user").type is discord.AppCommandOptionType.user
    value = option("number", "value")
    assert value.type is discord.AppCommandOptionType.integer
    numbers = [spec for spec in SETTINGS.values() if spec.kind is SettingKind.INTEGER]
    assert value.min_value == min(spec.minimum for spec in numbers)
    assert value.max_value == max(spec.maximum for spec in numbers)
    assert option("status", "text").max_value == 128


# -- changing a value ---------------------------------------------------------


async def test_a_change_is_saved_applied_and_recorded_in_the_mod_log(bot, world):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)
    new_role = make_role(70)

    await cog.role.callback(cog, interaction, "verified_role", new_role)

    assert bot.settings.get("verified_role") == 70
    assert SettingsStore.load(bot.settings.path).get("verified_role") == 70

    entry = world.mod_log.send.await_args.kwargs["embed"]
    assert entry.title == "Setting changed"
    assert f"<@{ADMIN_ID}>" in entry.description
    assert "<@&2>" in entry.description and "<@&70>" in entry.description

    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True
    assert "<@&2>" in kwargs["content"] and "<@&70>" in kwargs["content"]
    mentions = kwargs["allowed_mentions"]
    assert not (mentions.everyone or mentions.users or mentions.roles)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)


async def test_channel_category_and_user_are_stored(bot, world):
    cog = Settings(bot)

    await cog.channel.callback(
        cog, make_interaction(bot, world), "rules_channel", make_text_channel(71)
    )
    category = MagicMock(spec=discord.CategoryChannel)
    category.id = 72
    await cog.category.callback(cog, make_interaction(bot, world), "ontopic_category", category)
    user = MagicMock(spec=discord.User)
    user.id = 73
    await cog.user.callback(cog, make_interaction(bot, world), "moderator_mail_user", user)

    reloaded = SettingsStore.load(bot.settings.path)
    assert reloaded.get("rules_channel") == 71
    assert reloaded.get("ontopic_category") == 72
    assert reloaded.get("moderator_mail_user") == 73
    assert world.mod_log.send.await_count == 3


async def test_setting_the_same_value_again_changes_nothing(bot, world):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)

    await cog.role.callback(cog, interaction, "verified_role", world.roles[2])

    assert "already" in reply_of(interaction)
    world.mod_log.send.assert_not_awaited()


async def test_a_setting_of_the_wrong_kind_is_refused(bot, world):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)

    await cog.role.callback(cog, interaction, "mod_log_channel", make_role(70))

    assert "Nothing was changed" in reply_of(interaction)
    assert bot.settings.get("mod_log_channel") == 6
    world.mod_log.send.assert_not_awaited()


async def test_role_list_add_and_remove(bot, world):
    cog = Settings(bot)

    await cog.role_add.callback(cog, make_interaction(bot, world), "colour_roles", make_role(70))
    assert bot.settings.get("colour_roles") == (10, 11, 70)
    assert SettingsStore.load(bot.settings.path).get("colour_roles") == (10, 11, 70)

    again = make_interaction(bot, world)
    await cog.role_add.callback(cog, again, "colour_roles", make_role(70))
    assert "already" in reply_of(again)

    await cog.role_remove.callback(
        cog, make_interaction(bot, world), "colour_roles", world.roles[10]
    )
    assert bot.settings.get("colour_roles") == (11, 70)

    absent = make_interaction(bot, world)
    await cog.role_remove.callback(cog, absent, "colour_roles", make_role(99))
    assert "is not in" in reply_of(absent)
    assert world.mod_log.send.await_count == 2


async def test_removing_the_last_role_empties_the_list(bot, world):
    cog = Settings(bot)

    await cog.role_remove.callback(
        cog, make_interaction(bot, world), "sudo_voter_roles", world.roles[17]
    )

    assert bot.settings.get("sudo_voter_roles") == ()
    assert not SettingsStore.load(bot.settings.path).is_set("sudo_voter_roles")


async def test_role_prune_drops_only_deleted_roles(bot, world):
    cog = Settings(bot)
    bot.settings.set("colour_roles", (10, 555, 11, 556))

    interaction = make_interaction(bot, world)
    await cog.role_prune.callback(cog, interaction, "colour_roles")
    assert bot.settings.get("colour_roles") == (10, 11)
    assert "2 deleted roles" in reply_of(interaction)

    tidy = make_interaction(bot, world)
    await cog.role_prune.callback(cog, tidy, "colour_roles")
    assert "Nothing was changed" in reply_of(tidy)


async def test_role_prune_does_nothing_when_the_server_roles_are_not_visible(bot, world):
    cog = Settings(bot)
    world.guild.roles = []
    world.guild.get_role.side_effect = lambda role_id: None
    interaction = make_interaction(bot, world)

    await cog.role_prune.callback(cog, interaction, "colour_roles")

    assert bot.settings.get("colour_roles") == (10, 11)
    assert "Nothing was changed" in reply_of(interaction)


async def test_clear_puts_a_setting_back_to_its_default(bot, world):
    cog = Settings(bot)
    bot.settings.set("approval_threshold", 7)

    number = make_interaction(bot, world)
    await cog.clear.callback(cog, number, "approval_threshold")
    assert bot.settings.get("approval_threshold") == SETTINGS["approval_threshold"].default
    assert "default" in reply_of(number)

    await cog.clear.callback(cog, make_interaction(bot, world), "unboost_channel")
    assert bot.settings.get("unboost_channel") is None
    assert not SettingsStore.load(bot.settings.path).is_set("unboost_channel")

    again = make_interaction(bot, world)
    await cog.clear.callback(cog, again, "unboost_channel")
    assert "Nothing was changed" in reply_of(again)
    assert world.mod_log.send.await_count == 2


async def test_a_number_is_stored(bot, world):
    cog = Settings(bot)

    await cog.number.callback(cog, make_interaction(bot, world), "reminder_count", 8)

    assert SettingsStore.load(bot.settings.path).get("reminder_count") == 8


@pytest.mark.parametrize("value", [14, 3601])
async def test_a_number_out_of_range_is_rejected_and_nothing_changes(bot, world, value):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)
    bot.settings.save()
    saved = bot.settings.path.read_text(encoding="utf-8")

    await cog.number.callback(cog, interaction, "reminder_interval_seconds", value)

    reply = reply_of(interaction)
    assert "Nothing was changed" in reply
    assert "15 to 3600" in reply
    assert bot.settings.get("reminder_interval_seconds") == 180
    assert bot.settings.path.read_text(encoding="utf-8") == saved
    world.mod_log.send.assert_not_awaited()


async def test_status_text_is_applied_at_once(bot, world, monkeypatch):
    cog = Settings(bot)
    change_presence = AsyncMock()
    monkeypatch.setattr(bot, "change_presence", change_presence)
    monkeypatch.setattr(bot, "is_closed", lambda: False)

    await cog.status.callback(cog, make_interaction(bot, world), "  hello there  ")

    assert bot.settings.get("status_text") == "hello there"
    assert SettingsStore.load(bot.settings.path).get("status_text") == "hello there"
    assert change_presence.await_args.kwargs["activity"].name == "hello there"


async def test_a_settings_file_that_cannot_be_written_is_reported(bot, world, monkeypatch):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(bot.settings, "save", fail)
    await cog.role.callback(cog, interaction, "verified_role", make_role(70))

    assert "could not write its settings file" in reply_of(interaction)
    assert bot.settings.get("verified_role") == 2
    world.mod_log.send.assert_not_awaited()


async def test_a_change_without_a_mod_log_channel_says_it_was_not_recorded(
    config, empty_settings
):
    bot = VerificationBot(config, load_messages(), empty_settings)
    cog = Settings(bot)
    interaction = make_interaction(bot)

    await cog.number.callback(cog, interaction, "join_age_days", 30)

    assert bot.settings.get("join_age_days") == 30
    assert "could not be recorded in the mod-log" in reply_of(interaction)


# -- guards -------------------------------------------------------------------


async def test_everyone_is_refused_as_a_role(bot, world):
    cog = Settings(bot)
    everyone = make_role(HOME_SERVER_ID, default=True)

    single = make_interaction(bot, world)
    await cog.role.callback(cog, single, "emergency_role", everyone)
    listed = make_interaction(bot, world)
    await cog.role_add.callback(cog, listed, "moderator_roles", everyone)

    assert "@everyone" in reply_of(single) and "@everyone" in reply_of(listed)
    assert bot.settings.get("emergency_role") == 14
    assert bot.settings.get("moderator_roles") == (4, 5)


async def test_a_managed_role_is_refused_only_where_the_bot_must_assign_it(bot, world):
    cog = Settings(bot)
    managed = make_role(70, managed=True)

    refused = make_interaction(bot, world)
    await cog.role.callback(cog, refused, "booster_role", managed)
    assert "Nothing was changed" in reply_of(refused)
    assert bot.settings.get("booster_role") == 16

    listed = make_interaction(bot, world)
    await cog.role_add.callback(cog, listed, "colour_roles", managed)
    assert bot.settings.get("colour_roles") == (10, 11)

    # The emergency role is only pinged, never assigned, so a managed role is fine.
    await cog.role.callback(cog, make_interaction(bot, world), "emergency_role", managed)
    assert bot.settings.get("emergency_role") == 70


async def test_a_role_above_the_bots_own_is_saved_with_a_warning(bot, world):
    cog = Settings(bot)
    world.guild.me = MagicMock()
    world.guild.me.top_role.__le__ = lambda self, other: True
    interaction = make_interaction(bot, world)

    await cog.role.callback(cog, interaction, "verified_role", make_role(70))

    assert bot.settings.get("verified_role") == 70
    assert "below the bot's own highest role" in reply_of(interaction)


async def test_a_mod_log_channel_the_bot_cannot_post_in_is_saved_with_a_warning(bot, world):
    cog = Settings(bot)
    world.guild.me = MagicMock()
    channel = make_text_channel(71)
    channel.permissions_for.return_value = discord.Permissions(view_channel=True)
    interaction = make_interaction(bot, world)

    await cog.channel.callback(cog, interaction, "mod_log_channel", channel)

    assert bot.settings.get("mod_log_channel") == 71
    reply = reply_of(interaction)
    assert "Send Messages" in reply and "Embed Links" in reply


# -- /config show -------------------------------------------------------------


async def test_show_lists_every_setting_and_reports_a_healthy_server(bot, world):
    cog = Settings(bot)
    interaction = make_interaction(bot, world)

    await cog.show.callback(cog, interaction)

    text = show_text(interaction)
    for spec in SETTINGS.values():
        assert f"**{spec.label}:**" in text
    assert "All settings look good" in text
    assert "Needs attention" not in text
    assert "Mode: full" in text
    for kwargs in sends_of(interaction):
        assert kwargs["ephemeral"] is True
        assert not kwargs["allowed_mentions"].roles


async def test_show_says_when_the_bot_is_in_reduced_mode(reduced_bot):
    cog = Settings(reduced_bot)
    interaction = make_interaction(reduced_bot)

    await cog.show.callback(cog, interaction)

    text = show_text(interaction)
    assert "Mode: reduced" in text
    assert "/boosters" in text


async def test_show_flags_unset_deleted_and_wrong_type(bot, world):
    """The shape of the owner's test server: IDs that do not belong to it."""
    cog = Settings(bot)
    bot.settings.set("verified_role", None)  # unset
    bot.settings.set("emergency_role", 5550)  # a deleted role
    bot.settings.set("emergency_bypass_roles", (15, 5551))  # one deleted role in a list
    bot.settings.set("unboost_channel", 5552)  # really a user ID
    bot.settings.set("ontopic_category", 5553)  # a category of another server
    bot.settings.set("rules_channel", CATEGORY_ID)  # exists, but is not a text channel
    bot.settings.set("moderator_mail_user", 5554)  # users are never looked up
    interaction = make_interaction(bot, world)

    await cog.show.callback(cog, interaction)

    text = show_text(interaction)
    assert "6 settings need attention" in text
    assert "not set" in block_of(text, "Verified role")
    assert "nothing has been chosen yet" in block_of(text, "Verified role")
    assert "`5550` does not exist" in block_of(text, "Emergency role")
    bypass = block_of(text, "Emergency bypass roles")
    assert "`5551`" in bypass and "`15`" not in bypass
    assert "`5552` is not a channel in this server" in block_of(text, "Unboost channel")
    assert "`5553` does not exist" in block_of(text, "On-topic category")
    assert "is not a text channel" in block_of(text, "Rules channel")
    mail = block_of(text, "Moderator Mail user")
    assert "<@5554>" in mail and "Needs attention" not in mail
    for healthy in ("Booster role", "Mod-log channel", "Colour roles", "Status text"):
        assert "Needs attention" not in block_of(text, healthy)


async def test_show_on_a_fresh_install_flags_what_is_unset(config, empty_settings):
    bot = VerificationBot(config, load_messages(), empty_settings)
    cog = Settings(bot)
    interaction = make_interaction(bot)

    await cog.show.callback(cog, interaction)

    text = show_text(interaction)
    must_choose = [
        spec
        for spec in SETTINGS.values()
        if spec.kind
        in (SettingKind.ROLE, SettingKind.CHANNEL, SettingKind.CATEGORY, SettingKind.USER)
    ]
    assert f"{len(must_choose)} settings need attention" in text
    for spec in must_choose:
        assert "Needs attention" in block_of(text, spec.label)
    assert "Needs attention" not in block_of(text, "Moderator roles")


async def test_show_flags_a_role_the_bot_cannot_assign(bot, world):
    cog = Settings(bot)
    world.guild.me = MagicMock()
    world.guild.me.top_role.__le__ = lambda self, other: other.id in (2, 10)
    world.mod_log.permissions_for.return_value = discord.Permissions.all()
    interaction = make_interaction(bot, world)

    await cog.show.callback(cog, interaction)

    text = show_text(interaction)
    assert "2 settings need attention" in text
    assert "Needs attention" in block_of(text, "Verified role")
    assert "<@&10>" in block_of(text, "Colour roles").split("Needs attention")[1]
    assert "Needs attention" not in block_of(text, "Emergency role")


async def test_show_stays_within_discords_limits_with_very_long_lists(bot, world):
    cog = Settings(bot)
    for index, spec in enumerate(SETTINGS.values()):
        if spec.kind is SettingKind.ROLE_LIST:
            start = 10**18 + index * 1000
            bot.settings.set(spec.key, tuple(range(start, start + 250)))  # all deleted
    interaction = make_interaction(bot, world)

    await cog.show.callback(cog, interaction)

    sends = sends_of(interaction)
    assert 1 <= len(sends) <= 10
    for kwargs in sends:
        embed = kwargs["embed"]
        assert len(embed.description) <= 4096
        assert len(embed.fields) <= 25
        assert len(embed) <= 6000
        assert len(kwargs.get("content") or "") <= 2000
    text = show_text(interaction)
    for spec in SETTINGS.values():
        assert f"**{spec.label}:**" in text
        assert len(block_of(text, spec.label)) <= BLOCK_LIMIT
    assert "and 230 more" in text


async def test_show_with_production_sized_lists_fits_in_one_message(bot, world):
    cog = Settings(bot)
    bot.settings.set("colour_roles", tuple(range(10**18, 10**18 + 9)))
    bot.settings.set("moderator_roles", tuple(range(2 * 10**18, 2 * 10**18 + 5)))
    interaction = make_interaction(bot, world)

    await cog.show.callback(cog, interaction)

    (kwargs,) = sends_of(interaction)
    assert len(kwargs["embed"]) <= 6000
    assert len(kwargs["embed"].description) <= 4096
