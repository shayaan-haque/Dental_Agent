import { useRef, useState } from "react";
import { loginUser, signupUser } from "./authApi";
import "./auth.css";

export default function AuthPage({ mode, onLogin, authLoading }) {
  const signup = mode === "signup";
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);

  async function submit(event) {
    event.preventDefault();

    if (submitting.current || authLoading) return;

    const form = event.currentTarget;
    const fields = new FormData(form);

    const password = fields.get("password");
    const confirmation = form.elements.namedItem("confirmPassword");

    confirmation?.setCustomValidity("");

    if (signup && password !== fields.get("confirmPassword")) {
      confirmation.setCustomValidity("Your passwords do not match.");
      confirmation.reportValidity();
      return;
    }

    submitting.current = true;
    setPending(true);
    setError("");
    setNotice("");

    try {
      if (signup) {
        await signupUser({
          name: fields.get("name").trim(),
          email: fields.get("email").trim(),
          password,
        });
        form.reset();
        setShowPassword(false);
        setNotice("Account created successfully. Select Log in to sign in.");
      } else {
        const loggedInUser = await loginUser(fields.get("email").trim(), password);
        form.reset();
        onLogin(loggedInUser);
        window.location.hash = "#/chat";
      }
    } catch (error) {
      setError(
        error instanceof TypeError
          ? "Cannot reach the server. Check that FastAPI is running."
          : error.message
      );
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <main className="auth-layout">
      <aside className="auth-story">
        <a className="brand" href="#/chat" aria-label="Back to dental chat">
          <span className="brand-mark">✦</span> dental
          <span className="brand-dot">.</span>
        </a>
        <div className="auth-story-content">
          <span className="eyebrow">A LITTLE LESS FRICTION</span>
          <h1>
            A healthier smile.
            <br />A simpler journey.
          </h1>
          <p>
            Your care should fit into your life. Find your dentist, explore
            appointment times, and take the next step at your own pace.
          </p>
          <div className="auth-art" aria-hidden="true">
            <div className="art-orbit orbit-one" />
            <div className="art-orbit orbit-two" />
            <div className="art-center">✦</div>
            <span className="art-spark spark-one">✧</span>
            <span className="art-spark spark-two">✧</span>
          </div>
          <div className="auth-benefits">
            <div>
              <span>01</span> Find the right specialist
            </div>
            <div>
              <span>02</span> Explore times that suit you
            </div>
            <div>
              <span>03</span> Keep care simple
            </div>
          </div>
        </div>
        <p className="auth-story-footer">
          Thoughtful care. One conversation at a time.
        </p>
      </aside>

      <section className="auth-main" aria-labelledby="auth-title">
        <a className="back-to-chat" href="#/chat">
          ← Back to chat
        </a>
        <div className="auth-card">
          <span className="auth-preview">YOUR DENTAL ACCOUNT</span>
          <div className="auth-mobile-brand">✦ dental.</div>
          <h2 id="auth-title">
            {signup ? "Make room for better care." : "Welcome back."}
          </h2>
          <p className="auth-subtitle">
            {signup
              ? "Start with a few details. Your smile is in good company."
              : "A little closer to your next healthy smile."}
          </p>
          <nav className="auth-tabs" aria-label="Account pages">
            <a
              href="#/login"
              className={!signup ? "selected" : ""}
              aria-current={!signup ? "page" : undefined}
            >
              Log in
            </a>
            <a
              href="#/signup"
              className={signup ? "selected" : ""}
              aria-current={signup ? "page" : undefined}
            >
              Sign up
            </a>
          </nav>

          <form
            className="auth-form"
            onSubmit={submit}
            onChange={() => {
              setNotice("");
              setError("");
            }}
            aria-busy={pending}
            onInput={(event) => {
              event.currentTarget.elements.namedItem("confirmPassword")?.setCustomValidity("");
            }}
          >
            {signup && (
              <div className="auth-field">
                <label htmlFor="full-name">Full name</label>
                <input
                  id="full-name"
                  name="name"
                  type="text"
                  autoComplete="name"
                  placeholder="Your full name"
                  required
                  disabled={pending}
                  maxLength={100}
                  pattern=".*\S.*"
                />
              </div>
            )}
            <div className="auth-field">
              <label htmlFor="email">Email address</label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                required
                disabled={pending}
                maxLength={255}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="password">Password</label>
              <div className="password-field">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={signup ? "new-password" : "current-password"}
                  placeholder={
                    signup ? "Create a password" : "Enter your password"
                  }
                  required
                  disabled={pending}
                  minLength={signup ? 15 : undefined}
                  maxLength={128}
                  aria-describedby={signup ? "password-hint" : undefined}
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              {signup && (
                <small id="password-hint">
                  Use at least 15 characters.
                </small>
              )}
            </div>
            {signup && (
              <div className="auth-field">
                <label htmlFor="confirm-password">Confirm password</label>
                <input
                  id="confirm-password"
                  name="confirmPassword"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  placeholder="Re-enter your password"
                  required
                  disabled={pending}
                  maxLength={128}
                  onInput={(event) => event.currentTarget.setCustomValidity("")}
                />
              </div>
            )}
            <button className="auth-submit" type="submit" disabled={pending || authLoading}>
              {pending ? "Please wait…" : authLoading ? "Checking login…" : signup ? "Create account" : "Log in"}
              <span aria-hidden="true">↗</span>
            </button>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {notice && (
              <div className="auth-notice" role="status">
                {notice}
              </div>
            )}
          </form>

          <p className="auth-switch">
            {signup ? "Already have an account?" : "New to dental?"}{" "}
            <a href={signup ? "#/login" : "#/signup"}>
              {signup ? "Log in" : "Create an account"}
            </a>
          </p>
          <div className="auth-disclaimer">
            <span aria-hidden="true">ⓘ</span>
            <p>
              {signup
                ? "Signup creates an account. You’ll log in separately afterward."
                : "Login uses an HttpOnly cookie that JavaScript cannot read. Your session expires after 30 minutes."}
            </p>
          </div>
        </div>
        <p className="auth-bottom-note">Your next visit, made simple.</p>
      </section>
    </main>
  );
}
