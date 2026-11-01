"""The camera password, kept only in the macOS Keychain (never in the database, files or logs)."""

import keyring

SERVICE = "who-ate-the-fat-ball"
ACCOUNT = "camera"


def get_password() -> str | None:
    return keyring.get_password(SERVICE, ACCOUNT)


def set_password(pw: str) -> None:
    keyring.set_password(SERVICE, ACCOUNT, pw)
