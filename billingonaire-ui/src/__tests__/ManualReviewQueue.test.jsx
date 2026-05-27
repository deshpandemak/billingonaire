import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
}));

import * as api from '../lib/api';
import ManualReviewQueue from '../components/ManualReviewQueue';

const mockItems = [
  {
    doc_id: 'case_mr_01',
    case_ref: 'WP/1/2024',
    board_date: '2024-10-01',
    petitioner: 'State of Maharashtra',
    respondent: 'ABC Corp',
    order_category: 'ADJOURNED',
    confidence_score: 0.45,
    order_link: 'https://example.com/order.pdf',
  },
  {
    doc_id: 'case_mr_02',
    case_ref: 'WP/2/2024',
    board_date: '2024-10-02',
    petitioner: 'Union of India',
    respondent: 'XYZ Ltd',
    order_category: null,
    confidence_score: 0.62,
    order_link: null,
  },
  {
    doc_id: 'case_mr_03',
    case_ref: 'WP/3/2024',
    board_date: '2024-10-03',
    petitioner: 'Central Govt',
    respondent: 'Respondent Co',
    order_category: 'DISPOSED_OFF',
    confidence_score: 0.75,
    order_link: null,
  },
];

describe('ManualReviewQueue', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockResolvedValue(mockItems);
  });

  it('shows loading spinner on initial mount', () => {
    api.authenticatedFetchJSON.mockReturnValueOnce(new Promise(() => {}));
    render(<ManualReviewQueue />);
    expect(screen.getByText(/Loading review queue/i)).toBeTruthy();
  });

  it('renders the heading after data loads', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('Manual Review Queue')).toBeTruthy();
    });
  });

  it('shows the item count badge', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('3 items')).toBeTruthy();
    });
  });

  it('renders a row for each review item', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('WP/1/2024')).toBeTruthy();
      expect(screen.getByText('WP/2/2024')).toBeTruthy();
      expect(screen.getByText('WP/3/2024')).toBeTruthy();
    });
  });

  it('shows danger badge for confidence < 50%', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('45%')).toBeTruthy();
    });
  });

  it('shows warning badge for confidence between 50% and 70%', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('62%')).toBeTruthy();
    });
  });

  it('shows secondary badge for confidence >= 70%', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('75%')).toBeTruthy();
    });
  });

  it('renders a View PDF button only for items that have an order_link', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => {
      const pdfLinks = screen.getAllByText('View PDF');
      expect(pdfLinks).toHaveLength(1);
    });
  });

  it('shows the empty state when no items are pending', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce([]);
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText(/No cases awaiting manual review/i)).toBeTruthy();
    });
  });

  it('shows 0 items badge in the empty state', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce([]);
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('0 items')).toBeTruthy();
    });
  });

  it('removes item from list and shows success message on override', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce(mockItems)
      .mockResolvedValueOnce({ success: true });

    render(<ManualReviewQueue />);
    await waitFor(() => screen.getByText('WP/1/2024'));

    const adjournButtons = screen.getAllByText('Adjourned');
    fireEvent.click(adjournButtons[0]);

    await waitFor(() => {
      expect(screen.queryByText('WP/1/2024')).toBeNull();
      expect(screen.getByText(/set to Adjourned/i)).toBeTruthy();
    });
  });

  it('shows error message when override fails', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce(mockItems)
      .mockRejectedValueOnce(new Error('Server error'));

    render(<ManualReviewQueue />);
    await waitFor(() => screen.getByText('WP/1/2024'));

    const adjournButtons = screen.getAllByText('Adjourned');
    fireEvent.click(adjournButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Override failed/i)).toBeTruthy();
    });
  });

  it('shows error alert when the initial fetch fails', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('Network error'));
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText(/Failed to load review queue/i)).toBeTruthy();
    });
  });

  it('shows Retry button on fetch failure', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('Network error'));
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('Retry')).toBeTruthy();
    });
  });

  it('handles items array nested under data.items', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce({ items: mockItems });
    render(<ManualReviewQueue />);
    await waitFor(() => {
      expect(screen.getByText('WP/1/2024')).toBeTruthy();
    });
  });

  it('renders Refresh button and re-fetches on click', async () => {
    render(<ManualReviewQueue />);
    await waitFor(() => screen.getByText('Refresh'));
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => {
      expect(api.authenticatedFetchJSON).toHaveBeenCalledTimes(2);
    });
  });
});
