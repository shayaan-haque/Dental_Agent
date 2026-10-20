from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import User
from dental_agent.security import hash_password, verify_password


# Check a hash even for unknown emails to reduce obvious timing differences.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-account-password")


class EmailAlreadyRegisteredError(Exception):
    pass


def create_user(name: str, email: str, password: str) -> User:
    clean_name = name.strip()
    normalized_email = email.strip().lower()

    if not clean_name:
        raise ValueError("Name cannot be blank")

    # Hash before opening the database transaction.
    hashed_password = hash_password(password)

    try:
        with SessionLocal.begin() as session:
            user = User(
                name=clean_name,
                email=normalized_email,
                password_hash=hashed_password,
            )

            session.add(user)
            session.flush()

        return user

    except IntegrityError as exc:
        # PostgreSQL uses 23505 for a unique-constraint violation.
        sqlstate = getattr(exc.orig, "sqlstate", None)
        diagnostic = getattr(exc.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)

        if sqlstate == "23505" and constraint == "users_email_key":
            raise EmailAlreadyRegisteredError(
                "Email is already registered"
            ) from exc

        raise


def authenticate_user(email: str, password: str) -> User | None:
    normalized_email = email.strip().lower()

    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(User.email == normalized_email)
        )

        stored_hash = (
            user.password_hash if user is not None
            else DUMMY_PASSWORD_HASH
        )
        password_matches = verify_password(password, stored_hash)

        if user is None or not password_matches:
            return None

        return user
