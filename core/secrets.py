from __future__ import annotations

import keyring
import keyring.errors

SERVICE_NAME = "Lechu"


def get_secret(key: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, key)


def set_secret(key: str, value: str) -> None:
    keyring.set_password(SERVICE_NAME, key, value)


def delete_secret(key: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except keyring.errors.PasswordDeleteError:
        pass
