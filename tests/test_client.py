import pytest

from verification_bot.client import VerificationBot, build_intents
from verification_bot.config import config_from_mapping, load_messages

from .test_config import VALID


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    return VerificationBot(config_from_mapping(VALID), load_messages())


def test_only_members_intent_is_privileged():
    """Guards the Discord intent application: no Presence or Message Content."""
    intents = build_intents()
    assert intents.members is True
    assert intents.presences is False
    assert intents.message_content is False
    assert intents.guilds is True
    assert intents.dm_messages is True


def test_messages_are_rendered_with_defaults(bot):
    rendered = bot.message("verification.already_verified")
    assert "<@3>" in rendered


def test_messages_accept_extra_params(bot):
    rendered = bot.message("verification.too_young", required_days=5, account_age_days=1)
    assert "**5 days**" in rendered
    assert "**1 days**" in rendered


def test_unknown_message_path_raises(bot):
    with pytest.raises(KeyError):
        bot.message("verification.does_not_exist")


def test_every_emergency_template_renders(bot):
    assert bot.message(
        "emergency.prompt",
        caller="<@1>",
        reason="db down",
        approvals=0,
        approval_threshold=3,
        denials=0,
        deny_threshold=2,
    )
    assert bot.message(
        "emergency.approved", caller="<@1>", reason="db down", link="l", role="<@&2>"
    )
    assert bot.message("emergency.denied", caller="<@1>")
    assert bot.message("emergency.timed_out", caller="<@1>", link="l")
    assert bot.message("emergency.already_active", link="l")
    assert bot.message("emergency.reminder", link="l")
    assert bot.message("emergency.bypass", caller="<@1>", reason="db down", role="<@&2>")
    assert bot.message("boost.thank_you")
    assert bot.message("verification.dm_hint")
    assert bot.message("verification.success")
