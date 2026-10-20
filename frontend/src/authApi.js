// Authentication requests share the Vite /api proxy. The browser manages the
// HttpOnly cookie; never copy the JWT or passwords into browser storage.
async function authRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api/auth/${path}`, {
      credentials: 'same-origin',
      ...options,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the server. Check that FastAPI is running.');
  }
  if (path === 'me' && response.status === 401) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const validationMessage = Array.isArray(detail)
      ? detail.map(item => `${item.loc?.at(-1) || 'Field'}: ${item.msg}`).join(' ')
      : null;
    throw new Error(typeof detail === 'string' ? detail : validationMessage || `Request failed (${response.status}). Please try again.`);
  }
  return data;
}

export function signupUser(payload) {
  return authRequest('signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function loginUser(email, password) {
  return authRequest('login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
}

export function getCurrentUser(signal) {
  return authRequest('me', { signal });
}

export function logoutUser() {
  return authRequest('logout', { method: 'POST' });
}
