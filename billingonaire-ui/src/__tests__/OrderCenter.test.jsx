import { render, screen } from '@testing-library/react';
import OrderCenter from '../OrderCenter';

describe('OrderCenter', () => {
  it('renders without crashing', () => {
    render(<OrderCenter />);
    expect(screen.getByText(/overview/i)).toBeInTheDocument();
  });
  it('shows error message when API fails', async () => {
    // Mock fetch or authenticatedFetchJSON to throw error
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.reject('API error'));
    render(<OrderCenter />);
    // Simulate action that triggers API call
    // ...simulate user interaction...
    // Check for error message
  expect(await screen.findByRole('alert')).toBeInTheDocument();
    global.fetch.mockRestore();
    vi.restoreAllMocks();
  });
  // Add more tests for state changes, API calls, error handling
});
