"""Google OAuth 2.0 — restricted to @yotpo.com accounts."""

import os
import secrets
import urllib.parse
from datetime import datetime

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import User

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"

ALLOWED_DOMAIN = "yotpo.com"


def _redirect_uri() -> str:
    if uri := os.environ.get("GOOGLE_REDIRECT_URI"):
        return uri
    if domain := os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{domain}/auth/callback"
    return "http://localhost:8080/auth/callback"


def get_google_auth_url(request: Request) -> str:
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    request.session.pop("oauth_type", None)  # login flow — not gmail
    params = {
        "client_id":     os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri":  _redirect_uri(),
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "state":         state,
        "prompt":        "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def get_gmail_auth_url(request: Request) -> str:
    """Start a Gmail-scope OAuth flow. Reuses /auth/callback; oauth_type=gmail in session."""
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    request.session["oauth_type"] = "gmail"
    params = {
        "client_id":     os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri":  _redirect_uri(),
        "response_type": "code",
        "scope":         "openid email profile https://www.googleapis.com/auth/gmail.send",
        "access_type":   "offline",
        "state":         state,
        "prompt":        "consent",  # always re-consent so we always get refresh_token
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def handle_oauth_callback(code: str, state: str, request: Request, db: AsyncSession) -> User:
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or expected_state != state:
        raise HTTPException(400, "Invalid OAuth state")

    oauth_type = request.session.pop("oauth_type", "login")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri":  _redirect_uri(),
                "grant_type":    "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, "Failed to exchange OAuth code")
        tokens = token_resp.json()

        user_resp = await client.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch user info")
        guser = user_resp.json()

    email: str = guser.get("email", "")
    if not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
        raise HTTPException(403, f"Access restricted to @{ALLOWED_DOMAIN} accounts only.")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        user.last_seen = datetime.utcnow()
        user.name = guser.get("name", user.name)
        user.profile_photo = guser.get("picture", user.profile_photo)
        if oauth_type == "gmail" and tokens.get("refresh_token"):
            user.gmail_refresh_token = tokens["refresh_token"]
    else:
        user = User(
            email=email,
            name=guser.get("name", ""),
            google_id=guser.get("id", ""),
            profile_photo=guser.get("picture", ""),
            gmail_refresh_token=tokens.get("refresh_token") if oauth_type == "gmail" else None,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)
    return user


def require_auth(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Authentication required")
    return user
