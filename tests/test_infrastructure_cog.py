from unittest.mock import AsyncMock, MagicMock

import discord
import docker.errors
import pytest

from verification_bot import checks
from verification_bot.client import VerificationBot
from verification_bot.cogs import infrastructure
from verification_bot.cogs.infrastructure import Infrastructure, RelayError, run_action
from verification_bot.config import BotConfig, load_messages

from .conftest import HOME_SERVER_ID

NAME = "irc-relay"
CONTAINER_ID = "0123456789abcdef0123456789abcdef"


class FakeContainer:
    def __init__(self, status="running", fail_with=None):
        self.status = status
        self.fail_with = fail_with
        self.calls = []
        self._real_status = status

    def _act(self, name, new_status):
        self.calls.append(name)
        if self.fail_with:
            raise self.fail_with
        self._real_status = new_status

    def start(self):
        self._act("start", "running")

    def stop(self):
        self._act("stop", "exited")

    def restart(self):
        self._act("restart", "running")

    def reload(self):
        self.calls.append("reload")
        self.status = self._real_status


class FakeClient:
    def __init__(self, container=None, get_error=None):
        self.container = container or FakeContainer()
        self.get_error = get_error
        self.closed = False
        self.containers = MagicMock()
        self.containers.get.side_effect = self._get

    def _get(self, reference):
        if self.get_error:
            raise self.get_error
        if reference == NAME or CONTAINER_ID.startswith(reference):
            return self.container
        raise docker.errors.NotFound("no such container")

    def close(self):
        self.closed = True


@pytest.fixture
def irc_bot(settings):
    config = BotConfig(token="x", home_server_id=HOME_SERVER_ID, irc_relay_id=NAME)
    return VerificationBot(config, load_messages(), settings)


@pytest.fixture
def mod_log(irc_bot, monkeypatch):
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    monkeypatch.setattr(irc_bot, "get_channel", {6: channel}.get)
    return channel


def make_interaction():
    interaction = MagicMock()
    interaction.response.is_done.return_value = True
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.id = 77
    interaction.user.display_avatar.url = "https://example.invalid/a.png"
    return interaction


def choice(value):
    return MagicMock(value=value)


async def run(cog, action):
    interaction = make_interaction()
    await cog.irc.callback(cog, interaction, choice(action))
    return interaction


def reply(interaction):
    assert interaction.followup.send.await_count == 1
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True
    return kwargs


def make_cog(bot, client=None, factory=None):
    client = client or FakeClient()
    return Infrastructure(bot, factory or (lambda: client)), client


async def test_status_reports_and_logs_to_the_mod_log(irc_bot, mod_log):
    cog, client = make_cog(irc_bot)
    interaction = await run(cog, "status")
    assert "`running`" in reply(interaction)["embed"].fields[0].value
    mod_log.send.assert_awaited_once()
    assert client.container.calls == []


async def test_stop_then_start_report_the_observed_status(irc_bot, mod_log):
    cog, client = make_cog(irc_bot)
    stopped = await run(cog, "stop")
    assert "now `exited`" in reply(stopped)["embed"].fields[0].value
    assert client.container.calls == ["stop", "reload"]

    started = await run(cog, "start")
    assert "now `running`" in reply(started)["embed"].fields[0].value
    assert mod_log.send.await_count == 2


async def test_restart_reloads_before_reporting(irc_bot, mod_log):
    cog, client = make_cog(irc_bot)
    interaction = await run(cog, "restart")
    assert client.container.calls == ["restart", "reload"]
    assert "restarted" in reply(interaction)["embed"].fields[0].value


async def test_the_reported_status_is_what_docker_says_not_what_was_expected(irc_bot, mod_log):
    container = FakeContainer("running")
    container.restart = lambda: container._act("restart", "restarting")
    cog, _ = make_cog(irc_bot, FakeClient(container))
    interaction = await run(cog, "restart")
    assert "now `restarting`" in reply(interaction)["embed"].fields[0].value


async def test_already_running_and_already_stopped(irc_bot, mod_log):
    cog, client = make_cog(irc_bot)
    already = await run(cog, "start")
    assert "already running" in reply(already)["content"]

    client.container.status = "created"
    stopped = await run(cog, "stop")
    assert "already stopped" in reply(stopped)["content"]
    assert client.container.calls == []
    mod_log.send.assert_not_awaited()


@pytest.mark.parametrize("reference", [NAME, CONTAINER_ID, CONTAINER_ID[:12]])
def test_name_id_and_id_prefix_work_the_same(reference):
    result = run_action(FakeClient(), reference, "status")
    assert result.status == "running"


async def test_the_configured_reference_is_passed_through_unchanged(irc_bot, mod_log):
    irc_bot.config = BotConfig(token="x", home_server_id=1, irc_relay_id=CONTAINER_ID[:12])
    cog, client = make_cog(irc_bot)
    await run(cog, "status")
    client.containers.get.assert_called_with(CONTAINER_ID[:12])


async def test_container_not_found(irc_bot, mod_log):
    irc_bot.config = BotConfig(token="x", home_server_id=1, irc_relay_id="missing")
    cog, _ = make_cog(irc_bot)
    text = reply(await run(cog, "status"))["content"]
    assert "`missing`" in text and "irc_relay_id" in text and "NAME" in text
    mod_log.send.assert_not_awaited()


async def test_daemon_unreachable_at_connect_and_retried_next_time(irc_bot, mod_log):
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RelayError(infrastructure.UNREACHABLE_MESSAGE, drop_client=True)
        return FakeClient()

    cog = Infrastructure(irc_bot, factory)
    text = reply(await run(cog, "status"))["content"]
    assert "Docker daemon" in text and "`docker` group" in text

    assert "`running`" in reply(await run(cog, "status"))["embed"].fields[0].value
    assert len(attempts) == 2


async def test_connection_lost_mid_call_drops_the_client(irc_bot, mod_log):
    client = FakeClient(get_error=ConnectionError("socket gone"))
    cog, _ = make_cog(irc_bot, client)
    text = reply(await run(cog, "status"))["content"]
    assert "Docker daemon" in text
    assert client.closed and cog._client is None


def test_connect_docker_reports_an_unreachable_daemon(monkeypatch):
    def broken(*args, **kwargs):
        raise docker.errors.DockerException("Error while fetching server API version")

    monkeypatch.setattr(docker, "from_env", broken)
    with pytest.raises(RelayError) as caught:
        infrastructure.connect_docker()
    assert "Docker daemon" in caught.value.message and caught.value.drop_client


def test_connect_docker_reports_a_missing_package(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "docker", None)
    with pytest.raises(RelayError) as caught:
        infrastructure.connect_docker()
    assert "`docker` Python package is not installed" in caught.value.message


async def test_docker_package_missing_reaches_the_moderator(irc_bot, mod_log, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "docker", None)
    cog = Infrastructure(irc_bot)
    text = reply(await run(cog, "status"))["content"]
    assert "package is not installed" in text


async def test_api_error_on_the_action(irc_bot, mod_log):
    container = FakeContainer(fail_with=docker.errors.APIError("boom"))
    cog, client = make_cog(irc_bot, FakeClient(container))
    text = reply(await run(cog, "restart"))["content"]
    assert "failed the `restart` action" in text
    assert cog._client is client  # an API error is not a lost connection
    mod_log.send.assert_not_awaited()


async def test_unexpected_factory_failure_still_gets_a_reply(irc_bot, mod_log):
    def factory():
        raise RuntimeError("bug")

    text = reply(await run(Infrastructure(irc_bot, factory), "status"))["content"]
    assert "unexpected" in text


async def test_command_is_registered_when_irc_relay_id_is_set(irc_bot):
    await infrastructure.setup(irc_bot)  # no Docker involved at startup
    assert irc_bot.get_cog("Infrastructure") is not None


async def test_command_is_not_registered_when_irc_relay_id_is_unset(bot):
    await infrastructure.setup(bot)
    assert bot.get_cog("Infrastructure") is None


async def test_unload_closes_the_client_and_tolerates_none(irc_bot, mod_log):
    cog, client = make_cog(irc_bot)
    await run(cog, "status")
    await cog.cog_unload()
    assert client.closed

    await Infrastructure(irc_bot).cog_unload()


def test_command_requires_a_moderator_and_a_guild():
    command = Infrastructure.irc
    assert checks.audience_of(command) is checks.Audience.MODERATOR
    assert command.guild_only
    # Not hidden behind a Discord permission: the moderator-role check decides,
    # exactly as in the old bot.
    assert command.default_permissions is None


@pytest.mark.parametrize("status", ["restarting", "paused"])
def test_stop_acts_on_a_container_that_is_not_cleanly_stopped(status):
    """A crash-looping relay must be stoppable, as it was with the old bot."""
    container = FakeContainer(status=status)
    result = run_action(FakeClient(container), "irc-relay", "stop")
    assert "stop" in container.calls
    assert result.changed is True


@pytest.mark.parametrize("status", ["exited", "created", "dead"])
def test_stop_does_nothing_when_there_is_nothing_to_stop(status):
    container = FakeContainer(status=status)
    result = run_action(FakeClient(container), "irc-relay", "stop")
    assert container.calls == []
    assert result.changed is False
