import logging
import os
from math import ceil

import jwt
from fastapi import Cookie, FastAPI, Query
from groq import RateLimitError
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from dental_agent.workflows.appointment_graph import graph
from dental_agent.schemas.auth import LoginRequest, SignupRequest
from fastapi import HTTPException
from dental_agent.schemas.auth import UserResponse
from dental_agent.services.auth import (
    create_user,
    authenticate_user,
    EmailAlreadyRegisteredError,
)
from fastapi import Response
from dental_agent.security import (
    create_access_token,
    ACCESS_TOKEN_MINUTES,
    decode_access_token_claims,
)

from fastapi import Depends
from dental_agent.dependencies import get_current_user
from dental_agent.models.database_models import User
from dental_agent.services.chat_memory import chat_memory, ClosedConversation, MemoryFull
from dental_agent.services.appointments import get_patient_appointments
from dental_agent.schemas.appointments import AppointmentListResponse, AppointmentView
from dental_agent.response_formatter import build_action_reply

logger = logging.getLogger(__name__)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title = "Dental Appointemnt System")

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)


class ChatResponse(BaseModel):
    reply: str

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    access_token: str = Cookie(default=""),
):
    if not request.message.strip():
        raise HTTPException(422, "Message cannot be blank.")
    try:
        claims = decode_access_token_claims(access_token)
        with chat_memory.turn(access_token, claims["exp"]) as conversation:
            history = conversation.messages
            result = graph.invoke(
                {"messages": [*history, ("user", request.message)], "patient_id": current_user.id},
                config={"recursion_limit": 24},
            )
            final_message = result["messages"][-1]
            if not isinstance(final_message, AIMessage) or final_message.tool_calls:
                raise RuntimeError("The graph did not return a final assistant response")

            action_reply = build_action_reply(result["messages"][len(history):])
            reply = action_reply if action_reply is not None else final_message.content
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("The graph returned an empty reply")
            # Keep the corrected reply in history too, not a potentially false
            # model-generated action confirmation. No graph changes/replays.
            result["messages"][-1] = final_message.model_copy(update={"content": reply})
            conversation.turns.append(result["messages"][len(history):])
            return ChatResponse(reply=reply)
    except (jwt.InvalidTokenError, ClosedConversation) as exc:
        raise HTTPException(401, "Please log in again.") from exc
    except MemoryFull as exc:
        raise HTTPException(503, str(exc)) from exc
    except RateLimitError as exc:
        # No automatic graph replay: a mutation may have committed before a
        # later model call was throttled. The database page remains usable.
        try:
            retry_after = max(1, min(3600, ceil(float(exc.response.headers.get("retry-after", "60")))))
        except (ValueError, TypeError, OverflowError):
            retry_after = 60
        logger.warning("AI provider rate limit reached")
        raise HTTPException(
            429,
            f"The AI provider's token/rate limit was reached. Try again in about {retry_after} seconds. "
            "My appointments still works without AI tokens. If you were booking or cancelling, "
            "check that page before retrying; the change may already have completed.",
            headers={"Retry-After": str(retry_after)},
        ) from exc
    except Exception as exc:
        logger.exception("Chat failed")
        raise HTTPException(503, "Could not complete the chat. A booking or cancellation may already have completed; open My appointments before retrying.") from exc


@app.get("/api/appointments", response_model=AppointmentListResponse)
def my_appointments(
    response: Response,
    view: AppointmentView = "upcoming",
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
):
    # No model calls and no patient_id accepted from the browser.
    response.headers["Cache-Control"] = "no-store"
    try:
        return get_patient_appointments(current_user.id, view=view, limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        logger.exception("Could not load appointments")
        raise HTTPException(503, "Could not load your appointments. Please try again.") from exc


@app.post("/api/auth/signup", response_model=UserResponse, status_code=201)
def signup(request: SignupRequest):
    try:
        user = create_user(
            name=request.name,
            email=str(request.email),
            password=request.password,
        )
        return user

    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=409,
            detail="Unable to register with this email.",
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Name cannot be blank.",
        ) from exc


@app.post("/api/auth/login", response_model=UserResponse)
def login(request: LoginRequest, response: Response):
    user = authenticate_user(
        email=str(request.email),
        password=request.password,
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password.",
        )

    token = create_access_token(user.id)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )

    return user

@app.get("/api/auth/me",response_model=UserResponse)
def me(current_user : User = Depends(get_current_user)):
    return current_user

@app.post("/api/auth/logout")
def logout(response: Response, access_token: str | None = Cookie(default=None)):
    if access_token:
        try:
            claims = decode_access_token_claims(access_token)
            chat_memory.close(access_token, claims["exp"])
        except (jwt.InvalidTokenError, ClosedConversation):
            pass
        except MemoryFull as exc:
            raise HTTPException(503, "Could not clear the chat. Please try logout again.") from exc
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )

    return {"message": "Logged out successfully."}
