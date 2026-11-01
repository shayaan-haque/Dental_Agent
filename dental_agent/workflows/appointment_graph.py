import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt import tools_condition
from langgraph.runtime import Runtime
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from dental_agent.tools.availability import get_available_slots
from dental_agent.tools.booking import book_appointment
from dental_agent.tools.cancellation import cancel_appointment
from dental_agent.tools.appointments import view_my_appointments
from dental_agent.tools.rescheduling import reschedule_appointment
from dental_agent.workflows.message_budget import model_messages

load_dotenv()

# The current tier allows 1,000 output tokens/minute. Requesting 1,024
# fails even on the first call. Small replies also leave room for tool loops.
model = ChatGroq(
    model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
    max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "256")),
    max_retries=0,
    timeout=45,
)

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

tools = [get_available_slots, view_my_appointments, book_appointment, cancel_appointment, reschedule_appointment]
mutation_tools = {"book_appointment", "cancel_appointment", "reschedule_appointment"}

model_with_tools = model.bind_tools(tools)

def tool_calling_llm(state : DentalState):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    instructions = SystemMessage(content=(
        f"You are a dental appointment assistant. Today is {today} in Asia/Kolkata. "
        "Use the availability tool for factual doctor and appointment information. "
        "When a requested date omits the year, assume this year if it has not passed; "
        "otherwise ask for clarification before searching. Pass dates as YYYY-MM-DD. "
        "Never silently drop a requested filter. Do not invent doctors, slots, or weekdays. "
        "Availability tool results are limited to the earliest 8 matching slots, not all availability. "
        "Mention this limit when relevant. An empty result means no matching available slots. "
        "Use concise Markdown, normally under 100 words, and display times in Asia/Kolkata. "
        "Show at most 5 matching slots in a short list; offer to narrow the search for more. "
        "You can search availability, view the patient's bookings, book, cancel, and reschedule. "
        "Patient identity comes from the backend: never ask for or accept another patient's ID. "
        "Use view_my_appointments to find owned appointment IDs; do not confuse appointment_id with slot_id. "
        "Never invent IDs. Use exact doctor/date/time filters, including time_filter for an exact time. "
        "Ask for clarification if the doctor, existing appointment, or replacement is ambiguous. "
        "Only mutate when the user explicitly requests that action for that appointment/slot. "
        "Do not book a merely suggested alternative without the patient's approval. "
        "RESCHEDULING must use the dedicated reschedule_appointment tool, never cancel then book. "
        "First identify the existing appointment with "
        "view_my_appointments. Keep the same doctor unless the patient asks otherwise. "
        "Search get_available_slots for the exact replacement doctor/date/time. If none matches, "
        "say so and leave the existing appointment untouched. Never cancel just to explore availability. "
        "If a replacement matches the patient's request, call reschedule_appointment once with "
        "the old appointment_id and new_slot_id. Its transaction moves the visit atomically. "
        "Do not cancel/book separately, compensate for a failure, or retry a mutation in the same turn. "
        "An unavailable replacement or failed insertion leaves the original booking intact. "
        "After success, the old record is rescheduled and the new record is booked. "
        "Never combine mutations in one tool-call batch; wait for each result. "
        "An availability check is not a reservation. Only ok=true from the relevant mutation tool "
        "confirms its result. Include appointment ID, doctor, date and time in booking confirmations. "
        "For database errors, the outcome may be uncertain: check view_my_appointments, never blindly "
        "retry mutations or claim that nothing changed."
    ))
    # Keep recent complete turns and compact tool JSON. Execution still sees the
    # full trusted history, including search/cancellation results used as guards.
    messages = model_messages(state["messages"])
    return {"messages": [model_with_tools.invoke([instructions, *messages])]}

builder.add_node("tool_calling_llm",tool_calling_llm)

tool_node = ToolNode(tools, handle_tool_errors=json.dumps({
    "ok": False, "code": "tool_error",
    "message": "The tool could not complete the request. Do not assume success. Check your saved appointments before retrying.",
}))


def _rejected_calls(calls, code, message):
    return {"messages": [ToolMessage(
        content=json.dumps({"ok": False, "code": code, "message": message}),
        tool_call_id=call["id"], name=call["name"],
    ) for call in calls]}


def _tool_content(message):
    try:
        return json.loads(message.content) if isinstance(message.content, str) else message.content
    except (ValueError, TypeError):
        return None


def execute_tools(state: DentalState, config: RunnableConfig = None, runtime: Runtime = None):
    calls = state["messages"][-1].tool_calls
    # ToolNode normally executes a batch concurrently. A prompt alone must not
    # allow cancellation and booking to race (or two bookings to be made at once).
    if len(calls) > 1 and any(call["name"] in mutation_tools for call in calls):
        return _rejected_calls(calls, "sequential_calls_required",
                               "Nothing was changed. Call one mutation at a time and wait for its result.")
    if len(calls) == 1:
        call = calls[0]
        if call["name"] in mutation_tools:
            for message in reversed(state["messages"][:-1]):
                if isinstance(message, HumanMessage):
                    break
                if isinstance(message, ToolMessage) and message.name == "reschedule_appointment":
                    result = _tool_content(message)
                    # These rejections did not execute a mutation; allow the
                    # model to correct its search/batching before trying again.
                    if isinstance(result, dict) and result.get("code") in {"replacement_not_searched", "sequential_calls_required"}:
                        continue
                    return _rejected_calls(calls, "reschedule_finished",
                                           "Rescheduling was already attempted. Read saved appointments and explain the result; wait for a new user request before another mutation.")
        if call["name"] == "cancel_appointment" and "replacement_slot_id" in call["args"]:
            return _rejected_calls(calls, "reschedule_tool_required",
                                   "Nothing was cancelled. Use reschedule_appointment with appointment_id and new_slot_id to move a visit atomically.")
        if call["name"] == "reschedule_appointment":
            target = call["args"].get("new_slot_id")
            searched_slots = [
                slot.get("slot_id")
                for message in state["messages"][:-1]
                if isinstance(message, ToolMessage) and message.name == "get_available_slots"
                for slot in (_tool_content(message) if isinstance(_tool_content(message), list) else [])
                if isinstance(slot, dict)
            ]
            if target not in searched_slots:
                return _rejected_calls(calls, "replacement_not_searched",
                                       "Nothing was changed. Search for the requested replacement before calling reschedule_appointment.")
        if call["name"] == "book_appointment":
            # A failed cancellation must stop this turn even if the model tries
            # to proceed. A later explicit user request can start a new action.
            for message in reversed(state["messages"][:-1]):
                if isinstance(message, HumanMessage):
                    break
                if isinstance(message, ToolMessage) and message.name == "cancel_appointment":
                    result = _tool_content(message)
                    if not isinstance(result, dict) or not result.get("ok"):
                        return _rejected_calls(calls, "cancellation_failed",
                                               "Do not book: cancellation did not succeed. Explain the failure to the patient.")
                    return _rejected_calls(calls, "reschedule_tool_required",
                                           "Do not book after cancelling to move a visit. Changes must use reschedule_appointment as one atomic operation.")
    return tool_node.invoke(state, config=config, runtime=runtime or Runtime())


builder.add_node("tools", execute_tools)


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
