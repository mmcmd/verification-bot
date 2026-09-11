"""Key generation and log decryption helper.

``python -m verification_bot.logtools generate-key``
``python -m verification_bot.logtools decrypt logs/verification.log``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import LOG_KEY_ENV_VAR, secret_from_env
from .logging_setup import InvalidLogKey, build_cipher


def generate_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def decrypt_file(path: Path, key: str) -> int:
    from cryptography.fernet import InvalidToken

    cipher = build_cipher(key)
    failures = 0
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            token = line.strip()
            if not token:
                continue
            try:
                print(cipher.decrypt(token.encode("ascii")).decode("utf-8"))
            except InvalidToken:
                failures += 1
                print(f"<line {number}: could not decrypt with this key>", file=sys.stderr)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage encrypted verification bot logs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-key", help="Print a new Fernet key for LOG_ENCRYPTION_KEY.")
    decrypt = sub.add_parser("decrypt", help="Decrypt a log file to stdout.")
    decrypt.add_argument("path", type=Path)
    decrypt.add_argument(
        "--key",
        help=f"Fernet key. Defaults to the {LOG_KEY_ENV_VAR} environment variable.",
    )

    args = parser.parse_args(argv)

    if args.command == "generate-key":
        print(generate_key())
        return 0

    key = args.key or secret_from_env(LOG_KEY_ENV_VAR)
    if not key:
        print(f"No key supplied. Pass --key or set {LOG_KEY_ENV_VAR}.", file=sys.stderr)
        return 2
    if not args.path.is_file():
        print(f"{args.path} does not exist.", file=sys.stderr)
        return 2

    try:
        return 1 if decrypt_file(args.path, key) else 0
    except InvalidLogKey as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
