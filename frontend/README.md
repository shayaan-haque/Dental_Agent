# Dental React frontend

This chat sends each message to the existing FastAPI `/api/chat` endpoint.
Keep the backend running from the project root in a separate terminal:

```bash
python -m uvicorn dental_agent.api:app --reload --port 8000
```

The Python environment needs FastAPI, Uvicorn, and the project's agent/database
dependencies. Keep `GROQ_API_KEY` and `DATABASE_URL` in the root `.env`, never
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
and disappear on refresh. This supports availability only, not login or booking.

## Account page previews

Use the chat header links or open `/#/login` and `/#/signup`. These pages are
frontend-only: they validate fields locally but do not send authentication
requests, create users, store credentials, or grant access. Use sample details.
Returning to chat preserves the current conversation. Real authentication and
database integration will be implemented separately.

To check the production build:

```bash
npm run build
```
