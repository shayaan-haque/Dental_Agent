
import asyncio
import os
import sys

from dotenv import load_dotenv
from mcp import Client, StdioServerParameters

load_dotenv()

server = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_poc.server"],
    env={
        "DATABASE_URL": os.environ["DATABASE_URL"]
    },
)


async def main():
    async with Client(server) as client:

        # 1. Discover tools
        result = await client.list_tools()

        print("Available MCP tools:")

        for tool in result.tools:
            print(tool.name)
            print(tool.description)

        # 2. Invoke one discovered tool
        response = await client.call_tool(
            "get_available_slots",
            {
                "date_filter": "2026-11-05",
                "limit": 5,
            },
        )

        # 3. Display the result
        print("Tool error:", response.is_error)
        print("Tool result:")
        print(
            response.structured_content
            if response.structured_content is not None
            else response.content
        )


if __name__ == "__main__":
    asyncio.run(main())
