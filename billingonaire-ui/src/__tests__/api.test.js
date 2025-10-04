import * as api from '../lib/api';

describe('api helpers', () => {
  it('getApiUrl returns correct url', () => {
    expect(api.getApiUrl('test')).toBe('/test');
  });

  it('getApiUrl handles empty path', () => {
    expect(api.getApiUrl('')).toBe('/');
  });

  it('authenticatedFetch throws if no user', async () => {
    jest.spyOn(api.auth, 'currentUser', 'get').mockReturnValue(null);
    await expect(api.authenticatedFetch('/test')).rejects.toBeDefined();
    jest.restoreAllMocks();
  });
  // Add more tests for authenticatedFetch, error cases
});
