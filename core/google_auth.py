from __future__ import annotations

import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from core import memory
from core.secrets import delete_secret, get_secret, set_secret

CLIENT_CONFIG_KEY = "google_oauth_client"
TOKEN_KEY = "google_oauth_token"
CONNECTED_EMAIL_SETTING = "google_connected_email"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]


def save_client_config(client_id: str, client_secret: str) -> None:
    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    set_secret(CLIENT_CONFIG_KEY, json.dumps(config))


def has_client_config() -> bool:
    return get_secret(CLIENT_CONFIG_KEY) is not None


def run_oauth_flow() -> str:
    """Blocking - opens the system browser and runs a local server until the
    OAuth redirect comes back. Call via run.io_bound from the UI."""
    raw_config = get_secret(CLIENT_CONFIG_KEY)
    if not raw_config:
        raise RuntimeError("No hay credenciales de Google guardadas todavía.")
    config = json.loads(raw_config)
    flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES)
    credentials = flow.run_local_server(port=0)
    set_secret(TOKEN_KEY, credentials.to_json())

    service = build("oauth2", "v2", credentials=credentials)
    email = service.userinfo().get().execute()["email"]
    memory.set_setting(CONNECTED_EMAIL_SETTING, email)
    return email


def get_credentials() -> Credentials | None:
    raw_token = get_secret(TOKEN_KEY)
    if not raw_token:
        return None
    credentials = Credentials.from_authorized_user_info(json.loads(raw_token), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        set_secret(TOKEN_KEY, credentials.to_json())
    return credentials


def disconnect() -> None:
    delete_secret(TOKEN_KEY)
    memory.set_setting(CONNECTED_EMAIL_SETTING, "")


def get_connected_email() -> str | None:
    email = memory.get_setting(CONNECTED_EMAIL_SETTING, "")
    return email or None
