import { vi, describe, it, expect, beforeEach } from 'vitest';

// vi.hoisted runs before module imports so mockAuth is available inside vi.mock factory
const mockAuth = vi.hoisted(() => ({
  currentUser: {
    getIdToken: vi.fn().mockResolvedValue('test-token-abc'),
  },
}));

vi.mock('../lib/firebase', () => ({ auth: mockAuth }));

import * as api from '../lib/api';

describe('getApiUrl', () => {
  it('prepends /api to a path that starts with /', () => {
    expect(api.getApiUrl('/test')).toBe('/api/test');
  });

  it('prepends /api/ to a path without a leading slash', () => {
    expect(api.getApiUrl('test')).toBe('/api/test');
  });

  it('handles empty path', () => {
    expect(api.getApiUrl('')).toBe('/api/');
  });

  it('handles nested paths', () => {
    expect(api.getApiUrl('/cases/WP1/timeline')).toBe('/api/cases/WP1/timeline');
  });
});

describe('authenticatedFetch', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    mockAuth.currentUser = {
      getIdToken: vi.fn().mockResolvedValue('test-token-abc'),
    };
  });

  it('throws when no authenticated user is present', async () => {
    mockAuth.currentUser = null;
    await expect(api.authenticatedFetch('/test')).rejects.toThrow('User not authenticated');
  });

  it('includes Bearer token in Authorization header', async () => {
    mockAuth.currentUser.getIdToken.mockResolvedValueOnce('specific-token-xyz');
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
      text: async () => '',
    });

    await api.authenticatedFetch('/test');
    const [, callOptions] = global.fetch.mock.calls[0];
    expect(callOptions.headers['Authorization']).toBe('Bearer specific-token-xyz');
  });

  it('sets Content-Type to application/json for non-FormData bodies', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}), text: async () => '' });

    await api.authenticatedFetch('/test', { body: JSON.stringify({ x: 1 }) });
    const [, callOptions] = global.fetch.mock.calls[0];
    expect(callOptions.headers['Content-Type']).toBe('application/json');
  });

  it('does not set Content-Type for FormData bodies', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}), text: async () => '' });

    const form = new FormData();
    await api.authenticatedFetch('/upload', { body: form });
    const [, callOptions] = global.fetch.mock.calls[0];
    expect(callOptions.headers['Content-Type']).toBeUndefined();
  });

  it('throws on a non-ok HTTP response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: async () => 'resource not found',
    });

    await expect(api.authenticatedFetch('/missing')).rejects.toThrow('API call failed: 404');
  });

  it('returns the response object on success', async () => {
    const mockResponse = { ok: true, json: async () => ({ data: 1 }), text: async () => '' };
    global.fetch.mockResolvedValueOnce(mockResponse);

    const result = await api.authenticatedFetch('/test');
    expect(result).toBe(mockResponse);
  });
});

describe('authenticatedFetchJSON', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    mockAuth.currentUser = {
      getIdToken: vi.fn().mockResolvedValue('tok'),
    };
  });

  it('parses and returns JSON from the response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ cases: ['WP/1/2024'] }),
      text: async () => '',
    });

    const result = await api.authenticatedFetchJSON('/cases');
    expect(result).toEqual({ cases: ['WP/1/2024'] });
  });

  it('propagates errors from authenticatedFetch', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => '',
    });

    await expect(api.authenticatedFetchJSON('/cases')).rejects.toThrow('API call failed: 500');
  });
});
