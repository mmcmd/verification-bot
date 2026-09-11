import logging
import re
from pathlib import Path

import pytest

from verification_bot.logging_setup import InvalidLogKey, build_cipher, setup_logging
from verification_bot.logtools import decrypt_file, generate_key


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_records_are_unreadable_on_disk(tmp_path):
    key = generate_key()
    setup_logging(tmp_path, retention_days=7, encryption_key=key)
    logging.getLogger("test").info("member 123456789012345678 was verified")
    logging.shutdown()

    on_disk = (tmp_path / "verification.log").read_text(encoding="utf-8")
    assert "123456789012345678" not in on_disk
    assert "verified" not in on_disk


def test_records_round_trip_with_the_key(tmp_path, capsys):
    key = generate_key()
    setup_logging(tmp_path, retention_days=7, encryption_key=key)
    logging.getLogger("test").info("member 123456789012345678 was verified")
    logging.shutdown()
    capsys.readouterr()  # drop the plaintext console copy

    assert decrypt_file(tmp_path / "verification.log", key) == 0
    assert "123456789012345678 was verified" in capsys.readouterr().out


def test_a_different_key_cannot_read_the_log(tmp_path, capsys):
    setup_logging(tmp_path, retention_days=7, encryption_key=generate_key())
    logging.getLogger("test").info("sensitive")
    logging.shutdown()
    capsys.readouterr()  # drop the plaintext console copy

    assert decrypt_file(tmp_path / "verification.log", generate_key()) > 0
    assert "sensitive" not in capsys.readouterr().out


def test_retention_is_bounded_by_backup_count(tmp_path):
    setup_logging(tmp_path, retention_days=30, encryption_key=generate_key())
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
    )
    assert handler.backupCount == 30
    assert handler.when == "MIDNIGHT"


def test_missing_key_warns_but_still_logs(tmp_path, caplog):
    setup_logging(tmp_path, retention_days=7, encryption_key=None)
    logging.shutdown()
    assert Path(tmp_path / "verification.log").exists()


def test_malformed_key_is_rejected():
    with pytest.raises(InvalidLogKey):
        build_cipher("not-a-valid-fernet-key")


def test_console_output_redacts_discord_ids(tmp_path, capsys):
    setup_logging(tmp_path, retention_days=7, encryption_key=generate_key())
    logging.getLogger("test").info("Member 123456789012345678 was verified")
    logging.shutdown()

    console = capsys.readouterr().out
    assert "123456789012345678" not in console
    assert "user:" in console
    assert "was verified" in console


def test_redaction_is_stable_within_a_process(tmp_path, capsys):
    setup_logging(tmp_path, retention_days=7, encryption_key=generate_key())
    logging.getLogger("test").info("a 123456789012345678")
    logging.getLogger("test").info("b 123456789012345678")
    logging.shutdown()

    pseudonyms = re.findall(r"user:[0-9a-f]{10}", capsys.readouterr().out)
    assert len(pseudonyms) == 2
    assert pseudonyms[0] == pseudonyms[1]


def test_redaction_leaves_short_numbers_alone(tmp_path, capsys):
    setup_logging(tmp_path, retention_days=7, encryption_key=generate_key())
    logging.getLogger("test").info("account age 90 days, threshold 1234")
    logging.shutdown()

    assert "account age 90 days, threshold 1234" in capsys.readouterr().out


def test_encrypted_file_keeps_the_real_id(tmp_path, capsys):
    """Redaction applies to stdout only; moderators still get real IDs from the file."""
    key = generate_key()
    setup_logging(tmp_path, retention_days=7, encryption_key=key)
    logging.getLogger("test").info("Member 123456789012345678 was verified")
    logging.shutdown()
    capsys.readouterr()

    decrypt_file(tmp_path / "verification.log", key)
    assert "123456789012345678" in capsys.readouterr().out
