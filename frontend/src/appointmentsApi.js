// Saved bookings come from PostgreSQL, not the language model.
export async function getAppointments({ view = "upcoming", limit = 10, offset = 0, signal } = {}) {
  const query = new URLSearchParams({ view, limit: String(limit), offset: String(offset) });
  let response;
  try {
    response = await fetch(`/api/appointments?${query}`, {
      credentials: "same-origin", cache: "no-store", signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Cannot reach the server. Please try again.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) throw new Error("Please log in again to view your appointments.");
    throw new Error(typeof data?.detail === "string" ? data.detail : "Could not load your appointments. Please try again.");
  }
  if (!Array.isArray(data?.items) || typeof data?.has_more !== "boolean") {
    throw new Error("The server returned an invalid appointment list. Please try again.");
  }
  return data;
}
