import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
}));

import * as api from '../lib/api';
import PendingMatterConfirmations from '../components/PendingMatterConfirmations';

const mockPending = [
  {
    id: 'conf-1',
    case_ref: 'WP/1/2026',
    case_id: 'board-doc-1',
    matched_text: 'P. Deshpande',
    confidence_score: 0.42,
  },
  {
    id: 'conf-2',
    case_ref: 'WP/2/2026',
    case_id: 'board-doc-2',
    matched_text: 'Deshpande',
    confidence_score: 0.38,
  },
];

describe('PendingMatterConfirmations', () => {
  it('renders nothing while loading', () => {
    api.authenticatedFetchJSON.mockReturnValue(new Promise(() => {}));
    const { container } = render(<PendingMatterConfirmations />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when there are no pending confirmations', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce({ pending: [] });
    const { container } = render(<PendingMatterConfirmations />);
    await waitFor(() => expect(api.authenticatedFetchJSON).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it('renders a row per pending confirmation with the matched text', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce({ pending: mockPending });
    render(<PendingMatterConfirmations />);
    await waitFor(() => screen.getByText('WP/1/2026'));

    expect(screen.getByText('WP/2/2026')).toBeTruthy();
    expect(screen.getByText(/P\. Deshpande/)).toBeTruthy();
    expect(screen.getAllByText("Yes, that's me")).toHaveLength(2);
  });

  it('confirming removes the item and calls the confirm endpoint', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce({ pending: mockPending })
      .mockResolvedValueOnce({ success: true });

    render(<PendingMatterConfirmations />);
    await waitFor(() => screen.getByText('WP/1/2026'));

    fireEvent.click(screen.getAllByText("Yes, that's me")[0]);

    await waitFor(() => {
      expect(screen.queryByText('WP/1/2026')).toBeNull();
    });
    expect(screen.getByText('WP/2/2026')).toBeTruthy();
    expect(api.authenticatedFetchJSON).toHaveBeenCalledWith(
      '/user-matters/pending-confirmations/conf-1/confirm',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('rejecting removes the item and calls the reject endpoint', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce({ pending: mockPending })
      .mockResolvedValueOnce({ success: true });

    render(<PendingMatterConfirmations />);
    await waitFor(() => screen.getByText('WP/1/2026'));

    fireEvent.click(screen.getAllByText('Not me')[0]);

    await waitFor(() => {
      expect(screen.queryByText('WP/1/2026')).toBeNull();
    });
    expect(api.authenticatedFetchJSON).toHaveBeenCalledWith(
      '/user-matters/pending-confirmations/conf-1/reject',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('the whole component disappears once the last item is resolved', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce({ pending: [mockPending[0]] })
      .mockResolvedValueOnce({ success: true });

    const { container } = render(<PendingMatterConfirmations />);
    await waitFor(() => screen.getByText('WP/1/2026'));

    fireEvent.click(screen.getByText("Yes, that's me"));

    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });

  it('shows an inline error without crashing if a response action fails', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce({ pending: [mockPending[0]] })
      .mockRejectedValueOnce(new Error('Network error'));

    render(<PendingMatterConfirmations />);
    await waitFor(() => screen.getByText('WP/1/2026'));

    fireEvent.click(screen.getByText("Yes, that's me"));

    await waitFor(() => {
      expect(screen.getByText(/Network error/)).toBeTruthy();
    });
    // Item stays since the action failed.
    expect(screen.getByText('WP/1/2026')).toBeTruthy();
  });

  it('a failed initial fetch degrades silently, no error banner', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('boom'));
    const { container } = render(<PendingMatterConfirmations />);
    await waitFor(() => expect(api.authenticatedFetchJSON).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });
});
