from pwdlib import PasswordHash
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is not configured")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 30
password_hasher = PasswordHash.recommended()


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "token_type": "access",
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> int:
    payload = jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={
            "require": ["sub", "iat", "exp", "token_type"],
        },
    )

    if payload["token_type"] != "access":
        raise jwt.InvalidTokenError("Invalid token type")

    subject = payload["sub"]

    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
        or int(subject) <= 0
    ):
        raise jwt.InvalidTokenError("Invalid token subject")

    return int(subject)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hasher.verify(password, stored_hash)