from unittest.mock import AsyncMock, MagicMock

import discord
from discord import app_commands

from verification_bot import checks
from verification_bot.cogs.utility import (
    EMBED_TOTAL_LIMIT,
    FIELD_VALUE_LIMIT,
    MAX_FIELDS,
    PRIVACY_URL,
    SECTION_TITLES,
    Utility,
    build_help_embeds,
    build_help_sections,
)


def make_interaction():
    interaction = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.display_avatar.url = "https://example.invalid/a.png"
    return interaction


def sent_embed(interaction):
    kwargs = interaction.response.send_message.call_args.kwargs
    return kwargs["embed"], kwargs


def fields_by_section(embed):
    """Map section title -> all field text for that section (continued fields merged)."""
    result = {}
    for field in embed.fields:
        title = field.name.replace(" (continued)", "")
        result[title] = result.get(title, "") + "\n" + field.value
    return result


async def noop(interaction: discord.Interaction) -> None:
    pass


async def run_help(bot):
    cog = Utility(bot)
    interaction = make_interaction()
    await cog.help_command.callback(cog, interaction)
    embed, kwargs = sent_embed(interaction)
    return embed, kwargs, interaction


async def test_help_is_ephemeral_and_lists_every_command_in_its_section(loaded_bot):
    embed, kwargs, _ = await run_help(loaded_bot)
    assert kwargs["ephemeral"] is True
    sections = fields_by_section(embed)
    assert list(sections) == [s for s in SECTION_TITLES.values() if s in sections]
    for command in loaded_bot.all_app_commands():
        title = SECTION_TITLES[checks.audience_of(command)]
        names = (
            [c.qualified_name for c in command.walk_commands()]
            if isinstance(command, app_commands.Group)
            else [command.name]
        )
        for name in names:
            assert f"`/{name}`" in sections[title], name
    assert "`/verify`" in sections["Everyone"]
    assert "`/emergency`" in sections["Verified members"]
    assert "`/clearemergency`" in sections["Moderators"]


async def test_help_mentions_privacy_and_server_only_commands(loaded_bot):
    embed, _, _ = await run_help(loaded_bot)
    assert "/privacy" in embed.footer.text
    assert "inside the server" in embed.description or "only work" in embed.description


async def test_help_picks_up_new_commands_and_groups(loaded_bot):
    dummy = app_commands.Command(name="zzdummy", description="A dummy.", callback=noop)
    group = app_commands.Group(name="zzgroup", description="A group.")
    sub = app_commands.Command(name="secret", description="Admin thing.", callback=noop)
    sub.checks.append(checks.administrator_only()(sub).checks[-1])
    group.add_command(sub)
    loaded_bot.tree.add_command(dummy)
    loaded_bot.tree.add_command(group)

    embed, _, _ = await run_help(loaded_bot)
    sections = fields_by_section(embed)
    assert "`/zzdummy` - A dummy." in sections["Everyone"]
    assert "`/zzgroup secret` - Admin thing." in sections["Administrators"]
    assert "zzgroup" not in sections["Everyone"]


def test_empty_sections_are_omitted():
    command = app_commands.Command(name="solo", description="Only one.", callback=noop)
    sections = build_help_sections([command])
    assert [title for title, _ in sections] == ["Everyone"]


def test_commands_are_sorted_by_name_within_a_section():
    commands_ = [
        app_commands.Command(name=name, description="d", callback=noop) for name in ("b", "c", "a")
    ]
    (_, blocks), = build_help_sections(commands_)
    assert [line.split("`")[1] for line in blocks[0].split("\n")] == ["/a", "/b", "/c"]


def test_long_sections_are_split_within_embed_limits():
    commands_ = [
        app_commands.Command(name=f"command{i:03d}", description="x" * 90, callback=noop)
        for i in range(120)
    ]
    sections = build_help_sections(commands_)
    (_, blocks), = sections
    assert len(blocks) > 1
    assert all(len(block) <= FIELD_VALUE_LIMIT for block in blocks)

    embeds = build_help_embeds(sections, "intro", "footer")
    assert len(embeds) > 1
    for embed in embeds:
        assert len(embed.fields) <= MAX_FIELDS
        assert len(embed) <= EMBED_TOTAL_LIMIT
    text = "\n".join(f.value for e in embeds for f in e.fields)
    for i in range(120):
        assert f"`/command{i:03d}`" in text
    assert any("(continued)" in f.name for f in embeds[0].fields)


async def test_privacy_is_ephemeral_and_complete(loaded_bot):
    cog = Utility(loaded_bot)
    interaction = make_interaction()
    await cog.privacy.callback(cog, interaction)
    embed, kwargs = sent_embed(interaction)
    assert kwargs["ephemeral"] is True
    assert PRIVACY_URL in embed.description
    assert "<@3>" in embed.description
    assert "30 days" in embed.description
    assert "does not read, log or store" in embed.description
    assert len(embed.description) <= 4096


async def test_help_and_privacy_are_global_without_guild_only(loaded_bot):
    global_names = {c.name: c for c in loaded_bot.tree.get_commands()}
    for name in ("help", "privacy"):
        assert name in global_names
        assert not global_names[name].guild_only
