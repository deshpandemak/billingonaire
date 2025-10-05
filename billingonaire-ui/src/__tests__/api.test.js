import * as api from '../lib/api';
import { vi } from 'vitest';

describe('api helpers', () => {
  it('getApiUrl returns correct url', () => {
    expect(api.getApiUrl('test')).toBe('/api/test');
  });

  it('getApiUrl handles empty path', () => {
    expect(api.getApiUrl('')).toBe('/api/');
  });

  it('authenticatedFetch throws if no user', async () => {
    api.auth = { currentUser: null };
    await expect(api.authenticatedFetch('/test')).rejects.toBeDefined();
  });
  // Add more tests for authenticatedFetch, error cases
});
