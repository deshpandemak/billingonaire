import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
  getApiUrl: (path) => `http://localhost:8000${path}`,
}));

import * as api from '../lib/api';
import CaseDetailModal from '../components/CaseDetailModal';

const mockTimeline = {
  case_ref: 'WP/3373/2024',
  petitioner: 'State of Maharashtra',
  respondent: 'ABC Corp',
  lifecycle_status: 'analysed',
  orders: [
    {
      order_date: '2024-10-01',
      order_link: 'https://example.com/order1.pdf',
      order_category: 'ADJOURNED',
      government_pleader: ['AGP Sharma'],
    },
    {
      order_date: '2024-11-05',
      order_link: null,
      order_category: 'DISPOSED_OFF',
      government_pleader: ['AGP Verma'],
    },
  ],
  board_dates: [
    { board_date: '2024-10-01', respondent_lawyer: 'AGP Sharma', additional_respondent_lawyers: [] },
  ],
  lifecycle_events: [
    { status: 'board_ingested', timestamp: '2024-10-01T10:00:00Z' },
    { status: 'analysed', timestamp: '2024-10-02T12:00:00Z' },
  ],
};

describe('CaseDetailModal', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockResolvedValue(mockTimeline);
  });

  it('does not fetch when show is false', () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={false} onHide={vi.fn()} />);
    expect(api.authenticatedFetchJSON).not.toHaveBeenCalled();
  });

  it('shows loading spinner while fetching', async () => {
    api.authenticatedFetchJSON.mockReturnValueOnce(new Promise(() => {}));
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    expect(screen.getByText(/Loading case timeline/i)).toBeTruthy();
  });

  it('displays petitioner and respondent after successful fetch', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('State of Maharashtra')).toBeTruthy();
      expect(screen.getByText('ABC Corp')).toBeTruthy();
    });
  });

  it('renders the appearances table with correct column headers', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('GP in Board')).toBeTruthy();
      expect(screen.getByText('GP in Order')).toBeTruthy();
      expect(screen.getByText('Order PDF')).toBeTruthy();
      expect(screen.getByText('Order Analysis')).toBeTruthy();
    });
  });

  it('shows two appearance rows matching the mock data', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('2024-10-01')).toBeTruthy();
      expect(screen.getByText('2024-11-05')).toBeTruthy();
    });
  });

  it('renders a View Order link for appearances with an order PDF', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      const link = screen.getByText('View Order');
      expect(link).toBeTruthy();
      // Non-GCS links are proxied through /orders/pdf/{boardDocId}
      const href = link.getAttribute('href');
      expect(href).toContain('/orders/pdf/');
    });
  });

  it('shows error alert when the API call fails', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('Not found'));
    render(<CaseDetailModal caseRef="WP/999/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/Could not load case timeline/i)).toBeTruthy();
    });
  });

  it('shows lifecycle event log toggle button when events exist', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/Lifecycle Event Log/i)).toBeTruthy();
    });
  });

  it('expands lifecycle event log when toggle is clicked', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => screen.getByText(/Lifecycle Event Log/i));
    fireEvent.click(screen.getByText(/Show.*Lifecycle Event Log/i));
    await waitFor(() => {
      expect(screen.getByText(/Hide.*Lifecycle Event Log/i)).toBeTruthy();
    });
  });

  it('calls the API with the encoded case ref', async () => {
    render(<CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />);
    await waitFor(() => {
      expect(api.authenticatedFetchJSON).toHaveBeenCalledWith(
        '/cases/WP%2F3373%2F2024/timeline'
      );
    });
  });

  it('resets timeline state when show changes to false', async () => {
    const { rerender } = render(
      <CaseDetailModal caseRef="WP/3373/2024" show={true} onHide={vi.fn()} />
    );
    await waitFor(() => screen.getByText('State of Maharashtra'));
    rerender(<CaseDetailModal caseRef="WP/3373/2024" show={false} onHide={vi.fn()} />);
    expect(screen.queryByText('State of Maharashtra')).toBeNull();
  });
});
