from fastapi import FastAPI
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
)

from fastapi import Depends
from dental_agent.dependencies import get_current_user
from dental_agent.models.database_models import User

app = FastAPI(title = "Dental Appointemnt System")

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)


class ChatResponse(BaseModel):
    reply: str

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    result = graph.invoke(
        {
            "messages":[
                ("user",request.message)
            ]
        },config={"recursion_limit":12},
    )
    final_message = result["messages"][-1]

    if not isinstance(final_message, AIMessage):
        raise RuntimeError("The graph did not return an assistant response")

    return ChatResponse(reply=final_message.content)


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
        secure=False,  # Local HTTP development only.
        samesite="lax",
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )

    return user

@app.get("/api/auth/me",response_model=UserResponse)
def me(current_user : User = Depends(get_current_user)):
    return current_user

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=False,  # Local HTTP development only.
        samesite="lax",
    )

    return {"message": "Logged out successfully."}
