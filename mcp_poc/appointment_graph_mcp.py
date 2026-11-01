
import asyncio
import os
import sys
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_mcp_adapters.client import MultiServerMCPClient


load_dotenv()


class MCPDentalState(TypedDict):
    messages: Annotated[list, add_messages]


async def main():

    # 1. Configure MCP client
    client = MultiServerMCPClient({
        "dental": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_poc.server"],
            "env": os.environ.copy(),
        }
    })

    # 2. Discover MCP tools
    tools = await client.get_tools()

    print("Discovered MCP tools:")
    for tool in tools:
        print("-", tool.name)

    if not tools:
        raise RuntimeError("No MCP tools discovered")

    # 3. Initialize the LLM
    model = ChatGroq(
        model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
        max_tokens=512,
        max_retries=0,
        timeout=45,
    )

    # 4. Bind MCP tools to the LLM
    model_with_tools = model.bind_tools(tools)

    # 5. Create LangGraph LLM node
    async def call_llm(state: MCPDentalState):

        instructions = SystemMessage(
            content=(
                "You are a dental appointment assistant. "
                "Use the available tool to search real dental "
                "appointment availability. "
                "Never invent doctors, times, or slot IDs. "
                "Do not claim to book or cancel appointments. "
                "You can only search availability."
            )
        )

        response = await model_with_tools.ainvoke(
            [instructions, *state["messages"]]
        )

        return {"messages": [response]}

    # 6. Build the graph
    builder = StateGraph(MCPDentalState)

    builder.add_node("assistant", call_llm)
    builder.add_node("tools", ToolNode(tools))

    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")

    graph = builder.compile()

    # 7. Test using a natural-language prompt
    result = await graph.ainvoke(
        {
            "messages": [
                (
                    "user",
                    "Find available dentists on November 5, 2026. "
                    "Show me up to 3 appointment slots."
                )
            ]
        },
        config={"recursion_limit": 10},
    )

    # 8. Display all messages, including tool calls/results
    print("\n--- LangGraph execution ---")

    for message in result["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
