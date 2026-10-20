import jwt
from fastapi import Cookie, HTTPException

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import User
from dental_agent.security import decode_access_token


def get_current_user(
    access_token: str | None = Cookie(default=None),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="Please log in again.",
    )

    if not access_token:
        raise unauthorized

    try:
        user_id = decode_access_token(access_token)
    except jwt.InvalidTokenError as exc:
        raise unauthorized from exc

    with SessionLocal() as session:
        user = session.get(User,user_id)

        if user is None:
            raise unauthorized

        return user