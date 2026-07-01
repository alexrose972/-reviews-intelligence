"""Gmail API client — send emails using stored OAuth refresh tokens."""

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Optional

import httpx

log = logging.getLogger("gmail_client")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


async def refresh_access_token(refresh_token: str) -> Optional[str]:
    """Exchange a refresh token for a fresh access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            },
        )
    if resp.status_code != 200:
        log.error("Token refresh failed: %s %s", resp.status_code, resp.text)
        return None
    return resp.json().get("access_token")


async def send_email(
    refresh_token: str,
    to_email: str,
    subject: str,
    body: str,
    from_name: str = "",
) -> dict:
    """
    Send a plain-text email via Gmail API.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    access_token = await refresh_access_token(refresh_token)
    if not access_token:
        return {"ok": False, "error": "Could not refresh Gmail token — reconnect Google account"}

    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to_email
    msg["subject"] = subject
    # from is set by Gmail to the authenticated account automatically

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )

    if resp.status_code in (200, 201):
        msg_id = resp.json().get("id", "")
        log.info("Sent email to %s (id=%s)", to_email, msg_id)
        return {"ok": True, "message_id": msg_id}

    log.error("Gmail send failed to %s: %s %s", to_email, resp.status_code, resp.text)
    return {"ok": False, "error": f"Gmail API error {resp.status_code}: {resp.text[:200]}"}
