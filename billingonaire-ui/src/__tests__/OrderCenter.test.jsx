import { render, screen } from '@testing-library/react';
import OrderCenter from '../OrderCenter';

describe('OrderCenter', () => {
  it('renders without crashing', () => {
    render(<OrderCenter />);
    expect(screen.getByText(/overview/i)).toBeInTheDocument();
  });
  it('shows error message when API fails', async () => {
    // Mock fetch or authenticatedFetchJSON to throw error
    jest.spyOn(global, 'fetch').mockImplementation(() => Promise.reject('API error'));
    render(<OrderCenter />);
    // Simulate action that triggers API call
    // ...simulate user interaction...
    // Check for error message
    expect(await screen.findByText(/error/i)).toBeInTheDocument();
    global.fetch.mockRestore();
  });
  // Add more tests for state changes, API calls, error handling
});
