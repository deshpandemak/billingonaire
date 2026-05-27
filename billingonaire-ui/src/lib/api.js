import { auth } from './firebase.js';

const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

export const getApiUrl = (path) => {
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${cleanPath}`;
};

export const authenticatedFetch = async (url, options = {}) => {
  const user = auth.currentUser;
  if (!user) throw new Error('User not authenticated');

  const idToken = await user.getIdToken();

  const headers = {
    'Authorization': `Bearer ${idToken}`,
    ...options.headers,
  };

  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const fullUrl = `${API_BASE_URL}${url}`;
  const timeoutMs = Number(options.timeoutMs ?? 45000);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const { timeoutMs: _t, signal: callerSignal, ...fetchOptions } = options;

  let response;
  try {
    response = await fetch(fullUrl, {
      ...fetchOptions,
      headers,
      signal: callerSignal || controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API call failed: ${response.status} ${response.statusText}${errorText ? ` — ${errorText}` : ''}`);
  }

  return response;
};

export const authenticatedFetchJSON = async (url, options = {}) => {
  const response = await authenticatedFetch(url, options);
  return response.json();
};
