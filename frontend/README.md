# Dental React frontend

This chat sends each message to the existing FastAPI `/api/chat` endpoint.
Keep the backend running from the project root in a separate terminal:

```bash
python -m uvicorn dental_agent.api:app --reload --port 8000
```

The Python environment needs FastAPI, Uvicorn, and the project's agent/database
dependencies. Keep `GROQ_API_KEY`, `DATABASE_URL`, and `JWT_SECRET_KEY` in the root `.env`, never
in frontend code. Groq rate limits still apply.

From the project root:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173). Sign in to chat.
Vite proxies `/api` to port 8000; restart Vite after changing its proxy configuration.
The API receives only the latest message and supplies trusted patient identity
and server-held history. Visible messages still disappear on browser refresh;
no patient text or tokens are saved to localStorage.

## Account integration

Use the chat header links or open `/#/login` and `/#/signup`.

- Signup posts name, email, and password to `/api/auth/signup`, then asks the
  user to log in separately.
- Login posts credentials to `/api/auth/login`. The browser stores the HttpOnly
  cookie; React stores only returned user details in memory.
- `/api/auth/me` restores the displayed user after a reload. A 401 is an expected
  logged-out state. Other errors are displayed rather than silently ignored.
- Log out posts to `/api/auth/logout` before clearing the displayed user. If the
  request fails, the UI keeps the user displayed and allows retrying.
- Navigating to account pages preserves chat, but switching accounts or logging
  out clears visible messages. `/api/chat` requires authentication. Logout clears
  server chat history and redirects to the login page. There is no New conversation button.

No JWTs or passwords are saved in local/session storage. Use the same hostname
for frontend and backend (127.0.0.1). This is local development, not production
security hardening: HTTPS cookie settings, CSRF protections, rate limiting, and
production session revocation still need review. Chat memory/logout invalidation
are local to one Python process, not shared between workers.

## Booking, cancellation, and changing a visit

- Apply the existing schema first: `python -m alembic upgrade head`. The database's
  partial unique index prevents two booked appointments for one slot.
- `get_available_slots` searches active doctors and future enabled slots. For an
  exact requested time, `date_filter=YYYY-MM-DD` and `time_filter=HH:MM` filter
   before the result limit. The chat tool returns at most 8 matches to reduce
   token usage (the underlying service defaults to 20). Times use Asia/Kolkata.
- `view_my_appointments` finds the signed-in patient's appointment IDs. Upcoming
  bookings and full history are available with pagination.
- `book_appointment` rechecks availability transactionally. Retries for an already
  owned booking return that booking; overlapping patient bookings are rejected.
- `cancel_appointment` only cancels the signed-in patient's future booked visits.
  Cancelled records are retained, and their slots can be booked again.
- `reschedule_appointment` is the dedicated tool for moving an existing visit.
  After identifying the old booking and searching the exact replacement, the
  assistant passes `appointment_id` and `new_slot_id`. Patient identity is injected.
  Never implement a move with separate cancel/book tool calls.
- Rescheduling locks the patient and both slots, revalidates the new slot, marks
  the old record `rescheduled`, and creates the new `booked` record in **one
  PostgreSQL transaction**. `flush()` sends SQL without committing. The
  `SessionLocal.begin()` context commits on success and rolls back on any failure.
  An unavailable slot, insertion failure, or known failed commit does not leave
  the old booking cancelled. Success is returned only after commit completes.
- The search itself is still not a reservation: another patient can take the
  slot before the rescheduling transaction. In that case the tool refuses the
  change and the original booking stays intact. Parallel mutation batches are
  rejected; the graph also blocks automatic cancel/book compensation afterward.
- A previously rescheduled appointment ID is rejected on retry, rather than
  creating another booking. View upcoming appointments to find the current ID.
  If the connection/provider fails and the outcome is uncertain, inspect saved
  appointments before retrying. No database schema migration is needed.
- Server history retains the last 30 complete turns per login, for the token's
  lifetime (30 minutes), with a 128-login memory limit. Login tokens have unique
  IDs, so different logins do not share chat. This development-only memory is
  lost on restart. Use a shared persistent session/checkpoint store before
   deploying multiple workers. Saved appointments themselves stay in PostgreSQL.

## Backend-verified action replies

The graph still runs LLM → tools → LLM. Before returning `/api/chat`, FastAPI
formats attempted bookings, cancellations, and reschedules from their backend
tool results instead of trusting the model's final wording. Results are matched
by `tool_call_id` using only the current request's messages. Success requires the
expected outcome code and valid, matching appointment details; missing/malformed
results produce an unverified-outcome message, never a confirmation.

The corrected reply is also saved in chat memory. Multiple attempted actions
are reported separately so a later rejection cannot hide an earlier committed
success. Ordinary chat and read-only searches keep the model's response.
This adds no model calls or database writes, and does not change provider quotas.
If the graph raises before returning (for example a provider 429), the existing
error handler still advises checking My appointments before retrying.

## My appointments (no AI required)

Use **My appointments** in the sidebar or header, or open `/#/appointments`.
The page calls the authenticated `GET /api/appointments` endpoint directly:

- **Upcoming:** future or ongoing booked visits.
- **Previous:** past booked visits and completed visits, retaining their actual status.
- **Cancelled:** cancelled bookings.
- **Rescheduled:** old bookings successfully moved by the atomic rescheduling tool.
- **All bookings:** complete saved history, newest visits first.

The list is paginated and has a Refresh button. Empty accounts show an empty
state, never sample bookings. Database failures show an error/retry rather than
pretending there are no bookings. Switching views keeps the visible chat, and
the appointment list refreshes after a chat request finishes, even if its final
AI response failed. It remains available during AI rate limits.

## Refresh development availability

From the project root, preview or replace unused future availability for the
existing active doctors, today through the next 10 days (11 calendar days):

```bash
python -m scripts.refresh_availability
python -m scripts.refresh_availability --apply
```

Slots run daily 09:00–12:00 IST in 30-minute intervals, including weekends.
Use `--start-date YYYY-MM-DD --days-ahead 10` for an explicit date window.
Doctor profiles, past/ongoing slots, and every slot linked to any booking history
are preserved. Only unreferenced future slots are replaced. The apply operation
uses one transaction and a brief maintenance lock; if a booking is in progress,
it fails safely instead of racing the booking. No AI requests are made.

## AI token limits

The observed Groq tier allows 1,000 output tokens/minute. Previously each model
call requested `max_tokens=1024`, which exceeded that limit even for the first
request. The default is now **256 tokens per model call**, with short replies,
smaller tool results, and no automatic retries. Optionally configure the backend
in the root `.env` (restart the backend afterward):

```dotenv
GROQ_MAX_TOKENS=256
# GROQ_MODEL=your-tool-capable-model
```

Only the latest 4 complete earlier turns plus the active turn are sent to the
model, bounded by an 18,000-character budget for earlier context. Tool-call/result
pairs are never split. The active turn is retained intact, and full stored history
still supplies execution safeguards. This reduces input usage but isn't an exact
tokenizer count or a way to bypass the provider's quota.

A tool workflow can call the model several times, so total minute/day limits can
still be reached. The API returns HTTP 429 with `Retry-After`; chat shows a cooldown
without replaying actions. Use My appointments to check any change before retrying.
Higher sustained usage requires waiting for quota reset or changing the provider
plan/model to one with suitable limits; raising `GROQ_MAX_TOKENS` alone won't help.

Install test dependencies with `python -m pip install -r requirements-dev.txt`.
Run backend tests with `python -m pytest tests -q`. PostgreSQL locking tests are
opt-in: set `TEST_DATABASE_URL` to a **test** PostgreSQL database with `btree_gist`
already enabled. They create/drop only their own randomly named test schema.
Set `BOOKING_TEST_BACKEND=postgres` as well to run the behavior suite against
that PostgreSQL database instead of the default isolated SQLite database.

Run frontend request-helper tests without contacting the backend:

```bash
node --test src/authApi.test.js src/appointmentsApi.test.js
```

To check the production build:

```bash
npm run build
```
