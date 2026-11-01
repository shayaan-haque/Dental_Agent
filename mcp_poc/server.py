from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Dental Appointment MCP")

from dental_agent.services.availability import (
    get_available_slots as fetch_available_slots
)


@mcp.tool()
def get_available_slots(
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    specialization: str | None = None,
    date_filter: str | None = None,
    limit: int = 8,
) -> list:
    """Find available dental appointment slots using optional filters."""

    return fetch_available_slots(
        doctor_id=doctor_id,
        doctor_name=doctor_name,
        specialization=specialization,
        date_filter=date_filter,
        limit=limit,
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")