import json
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from langgraph.graph import StateGraph,START,END
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt import tools_condition
from langchain_groq import ChatGroq
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from dental_agent.tools.availability import get_available_slots

load_dotenv()

model = ChatGroq(model="qwen/qwen3.8-27b",max_tokens=1024)

class DentalState(TypedDict, total=False):

    # Conversation history
    messages: Annotated[list, add_messages]

    # What the user wants
    intent: str

    # Appointment details
    patient_id: int
    doctor_id: int
    slot_id: int
    appointment_id: int

    # Workflow results
    available_slots: list
    booking_status: str
    error: str | None

builder = StateGraph(DentalState)

tools = [get_available_slots]

model_with_tools = model.bind_tools(tools)

def tool_calling_llm(state : DentalState):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    instructions = SystemMessage(content=(
        f"You are a dental availability assistant. Today is {today} in Asia/Kolkata. "
        "Use the availability tool for factual doctor and appointment information. "
        "When a requested date omits the year, assume this year if it has not passed; "
        "otherwise ask for clarification before searching. Pass dates as YYYY-MM-DD. "
        "Never silently drop a requested filter. Do not invent doctors, slots, or weekdays. "
        "Tool results are limited to the earliest 20 matching slots, not all availability. "
        "Mention this limit when relevant. An empty result means no matching available slots. "
        "Use concise Markdown and display times in Asia/Kolkata. "
        "You can only search availability right now; you cannot book, cancel, or reschedule."
    ))
    # ToolNode may preserve a list result as message content (including []).
    # Groq requires nonempty tool-message content. Send JSON text instead,
    # preserving [] as an explicit "no results" value and leaving state intact.
    messages = [
        message.model_copy(update={"content": json.dumps(message.content)})
        if isinstance(message, ToolMessage) and isinstance(message.content, list)
        else message
        for message in state["messages"]
    ]
    return {"messages": [model_with_tools.invoke([instructions, *messages])]}

builder.add_node("tool_calling_llm",tool_calling_llm)
builder.add_node("tools",ToolNode(tools))


builder.add_edge(START,"tool_calling_llm")
builder.add_conditional_edges("tool_calling_llm",tools_condition)

builder.add_edge("tools","tool_calling_llm")

graph=builder.compile()


if __name__ == "__main__":
    # png_data = graph.get_graph().draw_mermaid_png()

    # with open("appointment_graph.png", "wb") as f:
    #     f.write(png_data)

    # print("Graph image saved successfully!")
    result = graph.invoke(
        {
            "messages": [
                ("user", "Show me available slots with available dentists on 17th Oct , 2026.")
            ]
        },
        config={"recursion_limit": 10},
    )

    for message in result["messages"]:
        message.pretty_print()
