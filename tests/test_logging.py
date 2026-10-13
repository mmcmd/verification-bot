import logging
import re

import pytest

from verification_bot.logging_setup import setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_logging_goes_to_standard_output_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    setup_logging()
    logging.getLogger("test").info("hello")

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert not isinstance(handlers[0], logging.FileHandler)
    assert "hello" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []  # no log file, no log folder


def test_console_output_redacts_discord_ids(capsys):
    setup_logging()
    logging.getLogger("test").info("Member 123456789012345678 was verified")

    console = capsys.readouterr().out
    assert "123456789012345678" not in console
    assert "id:" in console
    assert "was verified" in console


def test_redaction_is_stable_within_a_process(capsys):
    setup_logging()
    logging.getLogger("test").info("a 123456789012345678")
    logging.getLogger("test").info("b 123456789012345678")

    pseudonyms = re.findall(r"id:[0-9a-f]{10}", capsys.readouterr().out)
    assert len(pseudonyms) == 2
    assert pseudonyms[0] == pseudonyms[1]


def test_pseudonyms_differ_between_runs(capsys):
    setup_logging()
    logging.getLogger("test").info("a 123456789012345678")
    setup_logging()  # a restart gets a new random salt
    logging.getLogger("test").info("a 123456789012345678")

    first, second = re.findall(r"id:[0-9a-f]{10}", capsys.readouterr().out)
    assert first != second


def test_redaction_leaves_short_numbers_alone(capsys):
    setup_logging()
    logging.getLogger("test").info("account age 90 days, threshold 1234")
    assert "account age 90 days, threshold 1234" in capsys.readouterr().out


def test_ids_inside_tracebacks_are_redacted(capsys):
    setup_logging()
    try:
        raise RuntimeError("could not fetch member 123456789012345678")
    except RuntimeError:
        logging.getLogger("test").exception("lookup failed")

    console = capsys.readouterr().out
    assert "RuntimeError" in console
    assert "123456789012345678" not in console


def test_library_request_logging_stays_quiet():
    setup_logging(level=logging.DEBUG)
    assert logging.getLogger("discord.http").level == logging.WARNING
    assert logging.getLogger("discord.gateway").level == logging.WARNING
    assert logging.getLogger("discord.webhook").level == logging.WARNING
