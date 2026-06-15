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


def get_google_auth_url(request: Request) -> str:
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "client_id":     os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri":  os.environ["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "state":         state,
        "prompt":        "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def handle_oauth_callback(code: str, state: str, request: Request, db: AsyncSession) -> User:
    # CSRF check
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or expected_state != state:
        raise HTTPException(400, "Invalid OAuth state")

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri":  os.environ["GOOGLE_REDIRECT_URI"],
                "grant_type":    "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, "Failed to exchange OAuth code")
        tokens = token_resp.json()

        # Get user info
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

    # Upsert user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        user.last_seen = datetime.utcnow()
        user.name = guser.get("name", user.name)
        user.profile_photo = guser.get("picture", user.profile_photo)
    else:
        user = User(
            email=email,
            name=guser.get("name", ""),
            google_id=guser.get("id", ""),
            profile_photo=guser.get("picture", ""),
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
