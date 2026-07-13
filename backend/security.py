from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def secret_key() -> str:
    return os.getenv("JWT_SECRET", "dev-only-change-me-before-deployment")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    minutes = int(os.getenv("ACCESS_TOKEN_MINUTES", "10080"))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
