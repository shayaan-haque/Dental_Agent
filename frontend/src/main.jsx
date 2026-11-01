import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AuthPage from "./AuthPage";
import AppointmentsPanel from "./AppointmentsPanel";
import { getCurrentUser, logoutUser } from "./authApi";
import "./styles.css";

const suggestions = [
  ["Find a specialist", "Show me available appointments with an orthodontist."],
  ["Choose your doctor", "Show me available slots with Emily Johnson."],
  [
    "Explore availability",
    "Show me the earliest available dentist appointments.",
  ],
];

function App({ user, authLoading, authError, logoutPending, onLogout, view }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [retrySeconds, setRetrySeconds] = useState(0);
  const [appointmentsRevision, setAppointmentsRevision] = useState(0);
  const bottom = useRef(null);
  const inputRef = useRef(null);
  const sending = useRef(false);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error, pending]);
  useEffect(() => {
    if (!pending && view === "chat") inputRef.current?.focus();
  }, [pending, view]);
  useEffect(() => {
    if (retrySeconds <= 0) return;
    const timer = setTimeout(() => setRetrySeconds(value => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [retrySeconds]);

  async function send(text = input) {
    const content = text.trim();
    if (!content || sending.current) return;
    if (authLoading || logoutPending || retrySeconds > 0) return;
    if (!user) {
      setError("Please log in to search, book, or cancel appointments.");
      return;
    }
    if (content.length > 6000) {
      setError("Please keep your message under 6,000 characters.");
      return;
    }
    sending.current = true;
    setPending(true);
    // This updates the visible chat; it does not send anything to the backend.
    setMessages((previous) => [...previous, { role: "user", content }]);
    setInput("");
    setError("");

    try {
      // This POST sends the user's text to FastAPI's ChatRequest.message.
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content }),
      });
      if (!response.ok) {
        if (response.status === 429) {
          const delay = Number(response.headers.get("Retry-After"));
          setRetrySeconds(Number.isFinite(delay) && delay > 0 ? Math.min(3600, Math.ceil(delay)) : 60);
        }
        const failure = await response.json().catch(() => null);
        throw new Error(
          typeof failure?.detail === "string"
            ? failure.detail
            : `Request failed (${response.status}). Please check your appointments before retrying.`
        );
      }
      const data = await response.json();
      if (typeof data.reply !== "string" || !data.reply.trim()) {
        throw new Error(
          "The backend returned an invalid reply. Check the backend terminal."
        );
      }
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: data.reply },
      ]);
    } catch (err) {
      // Remove the failed turn and restore the draft so it can be retried.
      setMessages((previous) => previous.slice(0, -1));
      setInput(content);
      setError(
        err instanceof TypeError
          ? "Could not reach the API. Check that FastAPI is running on port 8000."
          : err.message
      );
    } finally {
      sending.current = false;
      setPending(false);
      // Refresh even after a failed AI response: a tool may have committed.
      setAppointmentsRevision(value => value + 1);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Dental home">
          <span className="brand-mark">✦</span> dental
          <span className="brand-dot">.</span>
        </a>
        <div className="sidebar-intro">
          <span className="eyebrow">A LITTLE LESS FRICTION</span>
          <h1>
            Your next visit,
            <br />
            made simple.
          </h1>
          <p>Find the right dentist and a time that works for you.</p>
        </div>
        <nav className="sidebar-views" aria-label="Main navigation">
          <a className={view === "chat" ? "selected" : ""} href="#/chat" aria-current={view === "chat" ? "page" : undefined}>✦ Chat</a>
          <a className={view === "appointments" ? "selected" : ""} href="#/appointments" aria-current={view === "appointments" ? "page" : undefined}>◷ My appointments</a>
        </nav>
        <div className="sidebar-note">
          <span className="note-icon">◷</span>
          <div>
            <strong>Clinic time</strong>
            <p>Asia/Kolkata · IST</p>
          </div>
        </div>
        <div className="scope">
          <span className="pill">APPOINTMENT ASSISTANT</span>
          <p>
            Sign in to find available slots, book a visit, or cancel an appointment.
            To change a visit, ask the assistant to check a new time first.
          </p>
        </div>
        <div className="sidebar-footer">Built with React + LangGraph</div>
      </aside>

      <main className="main-panel">
        <header>
          <div>
            <span className="assistant-dot" /> Dental assistant{" "}
            <span className="header-tag">{view === "appointments" ? "Appointments" : "Chat"}</span>
          </div>
          <div className="chat-header-actions">
            <nav className="header-view-switch" aria-label="Application views">
              <a className={view === "chat" ? "selected" : ""} href="#/chat" aria-current={view === "chat" ? "page" : undefined}>Chat</a>
              <a className={view === "appointments" ? "selected" : ""} href="#/appointments" aria-current={view === "appointments" ? "page" : undefined}>My appointments</a>
            </nav>
            <span className="connection">
              <i />
              {pending ? "Processing request…" : "Appointment chat"}
            </span>
            <nav className="account-links" aria-label="Account">
              {authLoading ? <span className="account-name" role="status">Checking login…</span> : user ? <>
                <span className="account-name" title={user.email}>Hi, {user.name}</span>
                <button className="logout-button" disabled={logoutPending || pending} onClick={onLogout}>
                  {logoutPending ? "Logging out…" : "Log out"}
                </button>
              </> : <>
                <a href="#/login">Log in</a>
                <a className="signup-link" href="#/signup">Sign up</a>
              </>}
            </nav>
          </div>
        </header>
        {view === "appointments" && <>
          {authError && <div className="error" role="alert">{authError}</div>}
          <AppointmentsPanel user={user} authLoading={authLoading} revision={appointmentsRevision} />
        </>}
        <div hidden={view !== "chat"} className="conversation" aria-live="polite" aria-busy={pending}>
          {!messages.length && (
            <section className="welcome">
              <div className="welcome-symbol">✦</div>
              <span className="eyebrow">
                GOOD CARE STARTS WITH A CONVERSATION
              </span>
              <h2>
                How can we help
                <br />
                you smile today?
              </h2>
              <p>
                Ask about a doctor, a specialty, or an available date.
                <br />
                The assistant will search the clinic’s availability.
              </p>
              <div className="suggestions">
                {suggestions.map(([title, prompt]) => (
                  <button
                    disabled={pending || authLoading || logoutPending || retrySeconds > 0}
                    key={title}
                    onClick={() => send(prompt)}
                  >
                    <span>{title}</span>
                    <small>{prompt}</small>
                    <b>↗</b>
                  </button>
                ))}
              </div>
            </section>
          )}
          <div className="message-list">
            {authError && <div className="error" role="alert">{authError}</div>}
            {messages.map((message, index) => (
              <article className={`message ${message.role}`} key={index}>
                <div className="avatar">
                  {message.role === "assistant" ? "✦" : "Y"}
                </div>
                <div className="message-body">
                  <div className="message-author">
                    {message.role === "assistant" ? "Dental assistant" : "You"}
                  </div>
                  <div className="markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                </div>
              </article>
            ))}
            {pending && (
              <article className="message assistant">
                <div className="avatar">✦</div>
                <div className="message-body">
                  <div className="message-author">Dental assistant</div>
                  <div className="thinking" role="status">
                    <span />
                    <span />
                    <span /> Checking your request…
                  </div>
                </div>
              </article>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <div ref={bottom} />
          </div>
        </div>
        <div hidden={view !== "chat"} className="composer-area">
          {retrySeconds > 0 && <p className="chat-cooldown" role="status">AI cooldown: {retrySeconds}s. You can still open <a href="#/appointments">My appointments</a>.</p>}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              send();
            }}
          >
            <label className="sr-only" htmlFor="chat-input">
              Message the dental assistant
            </label>
            <textarea
              id="chat-input"
              ref={inputRef}
              value={input}
              maxLength={6000}
              rows={2}
              placeholder="Ask about available dentists or appointment times…"
              disabled={pending || authLoading || logoutPending || retrySeconds > 0}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-bottom">
              <span>↵ to send · Shift + Enter for a new line</span>
              <button
                type="submit"
                aria-label="Send message"
                disabled={pending || authLoading || logoutPending || retrySeconds > 0 || !input.trim()}
              >
                ↑
              </button>
            </div>
          </form>
          <p className="disclaimer">
            Availability does not reserve a slot. A booking is saved only after confirmation.
          </p>
        </div>
      </main>
    </div>
  );
}

function Root() {
  const [route, setRoute] = useState(window.location.hash);
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [logoutPending, setLogoutPending] = useState(false);
  const restoreController = useRef(null);
  const loggingOut = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    restoreController.current = controller;

    async function restoreLogin() {
      try {
        const currentUser = await getCurrentUser(controller.signal);
        if (!controller.signal.aborted) setUser(currentUser);
      } catch (error) {
        if (error.name !== "AbortError") {
          setAuthError(error.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setAuthLoading(false);
        }
      }
    }

    restoreLogin();

    return () => controller.abort();
  }, []);

  function handleLogin(loggedInUser) {
    restoreController.current?.abort();
    setAuthError("");
    setAuthLoading(false);
    setUser(loggedInUser);
  }

  async function handleLogout() {
    if (loggingOut.current) return;
    loggingOut.current = true;
    setLogoutPending(true);
    setAuthError("");
    try {
      await logoutUser();
      restoreController.current?.abort();
      setUser(null);
      window.location.hash = "#/login";
    } catch (error) {
      // Keep the displayed session if the server could not clear its cookie.
      setAuthError(error.message);
    } finally {
      loggingOut.current = false;
      setLogoutPending(false);
    }
  }

  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const mode =
    route === "#/signup" ? "signup" : route === "#/login" ? "login" : null;
  useEffect(() => {
    document.title =
      mode === "signup"
        ? "Sign up · Dental"
        : mode === "login"
        ? "Log in · Dental"
        : "Dental · Your appointment assistant";
  }, [mode]);
  // Account navigation preserves chat; changing identity resets it for privacy.
  return (
    <>
      <div hidden={mode !== null}>
        <App key={user?.id ?? "guest"} user={user} authLoading={authLoading}
           authError={authError} logoutPending={logoutPending} onLogout={handleLogout}
           view={route === "#/appointments" ? "appointments" : "chat"} />
      </div>

      {mode && <AuthPage key={mode} mode={mode} onLogin={handleLogin} authLoading={authLoading} />}
    </>
  );
}

createRoot(document.getElementById("root")).render(<Root />);
