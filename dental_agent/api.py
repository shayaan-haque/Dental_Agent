from fastapi import FastAPI
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from dental_agent.workflows.appointment_graph import graph

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