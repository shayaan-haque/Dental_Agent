import { useState } from 'react';
import './auth.css';

export default function AuthPage({ mode }) {
  const signup = mode === 'signup';
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState('');

  function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const password = form.elements.namedItem('password');
    const confirmation = form.elements.namedItem('confirmPassword');
    if (signup && password.value !== confirmation.value) {
      confirmation.setCustomValidity('Your passwords do not match.');
      confirmation.reportValidity();
      return;
    }
    // UI-only: never send, log, or persist credentials.
    password.value = '';
    if (confirmation) confirmation.value = '';
    setNotice(signup
      ? 'The signup form is ready. No account was created—backend integration is coming later.'
      : 'The login form is ready. You have not been signed in—backend integration is coming later.');
  }

  return <main className="auth-layout">
    <aside className="auth-story">
      <a className="brand" href="#/chat" aria-label="Back to dental chat"><span className="brand-mark">✦</span> dental<span className="brand-dot">.</span></a>
      <div className="auth-story-content">
        <span className="eyebrow">A LITTLE LESS FRICTION</span>
        <h1>A healthier smile.<br />A simpler journey.</h1>
        <p>Your care should fit into your life. Find your dentist, explore appointment times, and take the next step at your own pace.</p>
        <div className="auth-art" aria-hidden="true"><div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" /><div className="art-center">✦</div><span className="art-spark spark-one">✧</span><span className="art-spark spark-two">✧</span></div>
        <div className="auth-benefits"><div><span>01</span> Find the right specialist</div><div><span>02</span> Explore times that suit you</div><div><span>03</span> Keep care simple</div></div>
      </div>
      <p className="auth-story-footer">Thoughtful care. One conversation at a time.</p>
    </aside>

    <section className="auth-main" aria-labelledby="auth-title">
      <a className="back-to-chat" href="#/chat">← Back to chat</a>
      <div className="auth-card">
        <span className="auth-preview">ACCOUNT UI PREVIEW</span>
        <div className="auth-mobile-brand">✦ dental.</div>
        <h2 id="auth-title">{signup ? 'Make room for better care.' : 'Welcome back.'}</h2>
        <p className="auth-subtitle">{signup ? 'Start with a few details. Your smile is in good company.' : 'A little closer to your next healthy smile.'}</p>
        <nav className="auth-tabs" aria-label="Account pages"><a href="#/login" className={!signup ? 'selected' : ''} aria-current={!signup ? 'page' : undefined}>Log in</a><a href="#/signup" className={signup ? 'selected' : ''} aria-current={signup ? 'page' : undefined}>Sign up</a></nav>

        <form className="auth-form" onSubmit={submit} onChange={() => setNotice('')}>
          {signup && <div className="auth-field"><label htmlFor="full-name">Full name</label><input id="full-name" name="name" type="text" autoComplete="name" placeholder="Your full name" required maxLength={100} pattern=".*\S.*" /></div>}
          <div className="auth-field"><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="email" placeholder="you@example.com" required maxLength={255} /></div>
          <div className="auth-field"><label htmlFor="password">Password</label><div className="password-field"><input id="password" name="password" type={showPassword ? 'text' : 'password'} autoComplete={signup ? 'new-password' : 'current-password'} placeholder={signup ? 'Create a password' : 'Enter your password'} required minLength={signup ? 8 : undefined} maxLength={128} aria-describedby={signup ? 'password-hint' : undefined} /><button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? 'Hide' : 'Show'}</button></div>{signup && <small id="password-hint">Use at least 8 characters for this preview.</small>}</div>
          {signup && <div className="auth-field"><label htmlFor="confirm-password">Confirm password</label><input id="confirm-password" name="confirmPassword" type={showPassword ? 'text' : 'password'} autoComplete="new-password" placeholder="Re-enter your password" required maxLength={128} onInput={event => event.currentTarget.setCustomValidity('')} /></div>}
          <button className="auth-submit" type="submit">{signup ? 'Create account' : 'Log in'} <span aria-hidden="true">↗</span></button>
          {notice && <div className="auth-notice" role="status">{notice}</div>}
        </form>

        <p className="auth-switch">{signup ? 'Already have an account?' : 'New to dental?'} <a href={signup ? '#/login' : '#/signup'}>{signup ? 'Log in' : 'Create an account'}</a></p>
        <div className="auth-disclaimer"><span aria-hidden="true">ⓘ</span><p>Design preview only. No accounts are created, no login takes place, and no credentials are sent or stored. Please use sample details.</p></div>
      </div>
      <p className="auth-bottom-note">Your next visit, made simple.</p>
    </section>
  </main>;
}
