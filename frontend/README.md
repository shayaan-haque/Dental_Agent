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

Open http://127.0.0.1:5173. You can type messages, try the suggestion cards,
and reset the visible conversation. Vite proxies `/api` to port 8000; restart
Vite after changing its proxy configuration. The API receives only the latest
message, so it cannot remember prior turns yet. Messages live in browser memory
and disappear on refresh. Booking is not implemented yet.

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
  out clears visible messages. Chat remains independent per message and its
  existing backend route is not protected by this frontend integration.

No JWTs or passwords are saved in local/session storage. Use the same hostname
for frontend and backend (127.0.0.1). This is local development, not production
security hardening: HTTPS cookie settings, CSRF protections, rate limiting, and
server-side route authorization still need review.

Run authentication request-helper tests without contacting the backend:

```bash
node --test src/authApi.test.js
```

To check the production build:

```bash
npm run build
```
