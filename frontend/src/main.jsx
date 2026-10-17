import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import AuthPage from './AuthPage';
import './styles.css';

const suggestions = [
  ['Find a specialist', 'Show me available appointments with an orthodontist.'],
  ['Choose your doctor', 'Show me available slots with Emily Johnson.'],
  ['Explore availability', 'Show me the earliest available dentist appointments.'],
];

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const bottom = useRef(null);
  const inputRef = useRef(null);
  const sending = useRef(false);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, error, pending]);
  useEffect(() => { if (!pending) inputRef.current?.focus(); }, [pending]);

  async function send(text = input) {
    const content = text.trim();
    if (!content || sending.current) return;
    if (content.length > 6000) { setError('Please keep your message under 6,000 characters.'); return; }
    sending.current = true;
    setPending(true);
    // This updates the visible chat; it does not send anything to the backend.
    setMessages(previous => [
      ...previous,
      { role: 'user', content },
    ]);
    setInput('');
    setError('');

    try {
      // This POST sends the user's text to FastAPI's ChatRequest.message.
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content }),
      });
      if (!response.ok) {
        throw new Error(`Request failed (${response.status}). Check the backend terminal for details.`);
      }
      const data = await response.json();
      if (typeof data.reply !== 'string' || !data.reply.trim()) {
        throw new Error('The backend returned an invalid reply. Check the backend terminal.');
      }
      setMessages(previous => [
        ...previous,
        { role: 'assistant', content: data.reply },
      ]);
    } catch (err) {
      // Remove the failed turn and restore the draft so it can be retried.
      setMessages(previous => previous.slice(0, -1));
      setInput(content);
      setError(err instanceof TypeError
        ? 'Could not reach the API. Check that FastAPI is running on port 8000.'
        : err.message);
    } finally {
      sending.current = false;
      setPending(false);
    }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Dental home"><span className="brand-mark">✦</span> dental<span className="brand-dot">.</span></a>
      <div className="sidebar-intro"><span className="eyebrow">A LITTLE LESS FRICTION</span><h1>Your next visit,<br />made simple.</h1><p>Find the right dentist and a time that works for you.</p></div>
      <button className="new-chat" disabled={pending} onClick={() => { setMessages([]); setError(''); setInput(''); inputRef.current?.focus(); }}>＋ New conversation</button>
      <div className="sidebar-note"><span className="note-icon">◷</span><div><strong>Clinic time</strong><p>Asia/Kolkata · IST</p></div></div>
      <div className="scope"><span className="pill">AVAILABILITY ASSISTANT</span><p>Search doctor availability through the AI assistant. Account pages are previews only; booking is not available yet.</p></div>
      <div className="sidebar-footer">Built with React + LangGraph</div>
    </aside>

    <main className="main-panel">
      <header><div><span className="assistant-dot" /> Dental assistant <span className="header-tag">Chat</span></div><div className="chat-header-actions"><span className="connection"><i />{pending ? 'Processing request…' : 'Availability chat'}</span><nav className="account-links" aria-label="Account"><a href="#/login">Log in</a><a className="signup-link" href="#/signup">Sign up</a></nav></div></header>
      <div className="conversation" aria-live="polite" aria-busy={pending}>
        {!messages.length && <section className="welcome">
          <div className="welcome-symbol">✦</div><span className="eyebrow">GOOD CARE STARTS WITH A CONVERSATION</span>
          <h2>How can we help<br />you smile today?</h2>
          <p>Ask about a doctor, a specialty, or an available date.<br />The assistant will search the clinic’s availability.</p>
          <div className="suggestions">{suggestions.map(([title, prompt]) => <button disabled={pending} key={title} onClick={() => send(prompt)}><span>{title}</span><small>{prompt}</small><b>↗</b></button>)}</div>
        </section>}
        <div className="message-list">{messages.map((message, index) => <article className={`message ${message.role}`} key={index}>
          <div className="avatar">{message.role === 'assistant' ? '✦' : 'Y'}</div>
          <div className="message-body"><div className="message-author">{message.role === 'assistant' ? 'Dental assistant' : 'You'}</div>
            <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>
          </div>
        </article>)}
        {pending && <article className="message assistant"><div className="avatar">✦</div><div className="message-body"><div className="message-author">Dental assistant</div><div className="thinking" role="status"><span /><span /><span /> Checking your request…</div></div></article>}
        {error && <div className="error" role="alert">{error}</div>}
        <div ref={bottom} /></div>
      </div>
      <div className="composer-area"><form onSubmit={event => { event.preventDefault(); send(); }}>
        <label className="sr-only" htmlFor="chat-input">Message the dental assistant</label>
        <textarea id="chat-input" ref={inputRef} value={input} maxLength={6000} rows={2} placeholder="Ask about available dentists or appointment times…" disabled={pending} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} />
        <div className="composer-bottom"><span>↵ to send · Shift + Enter for a new line</span><button type="submit" aria-label="Send message" disabled={pending || !input.trim()}>↑</button></div>
      </form><p className="disclaimer">Each request is independent; the assistant has no conversation memory yet. · Availability does not reserve a slot.</p></div>
    </main>
  </div>;
}

function Root() {
  const [route, setRoute] = useState(window.location.hash);
  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash);
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  const mode = route === '#/signup' ? 'signup' : route === '#/login' ? 'login' : null;
  useEffect(() => {
    document.title = mode === 'signup' ? 'Sign up · Dental' : mode === 'login' ? 'Log in · Dental' : 'Dental · Your appointment assistant';
  }, [mode]);
  // Keep chat mounted so visiting account previews does not lose the conversation.
  return <><div hidden={mode !== null}><App /></div>{mode && <AuthPage key={mode} mode={mode} />}</>;
}

createRoot(document.getElementById('root')).render(<Root />);
