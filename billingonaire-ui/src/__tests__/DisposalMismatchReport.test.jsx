import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../lib/firebase', () => ({
  auth: { currentUser: { getIdToken: vi.fn().mockResolvedValue('fake-token') } },
}));

vi.mock('firebase/auth', () => ({
  onAuthStateChanged: (_auth, callback) => {
    callback({ uid: 'u1' });
    return () => {};
  },
}));

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
  getApiUrl: (path) => `https://api.test${path}`,
}));

import * as api from '../lib/api';
import DisposalMismatchReport from '../DisposalMismatchReport';

const FLAGGED_REPORT = {
  cases_checked: 5,
  flagged_count: 1,
  already_disposed_by_same_agp: 2,
  no_disposal_yet: 1,
  disposal_agp_unnamed: 1,
  results: [
    {
      case_ref: 'WP/1/2026',
      appearances: [{ date: '2026-08-07', category: 'HEARD_AND_ADJOURNED' }],
      appearances_count: 1,
      disposal_date: '2026-09-08',
      disposal_board_date: '2026-09-08',
      disposal_agp_names: ['Rajan Pawar'],
      order_link: 'https://storage.example/disposal.pdf',
    },
  ],
};

const EMPTY_REPORT = {
  cases_checked: 3,
  flagged_count: 0,
  already_disposed_by_same_agp: 3,
  no_disposal_yet: 0,
  disposal_agp_unnamed: 0,
  results: [],
};

const mockAdminUsers = (names = []) => {
  api.authenticatedFetchJSON.mockImplementation((url) => {
    if (url === '/admin/active-users') return Promise.resolve({ user_names: names });
    return Promise.resolve({});
  });
};

const runReport = async () => {
  fireEvent.click(screen.getByText('Run Report'));
  await waitFor(() => {
    expect(screen.queryByText('Scanning...')).not.toBeInTheDocument();
  });
};

describe('DisposalMismatchReport', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockReset();
    mockAdminUsers();
  });

  it('renders the heading', () => {
    render(<DisposalMismatchReport />);
    expect(screen.getByText(/Disposal Mismatch Report/i)).toBeTruthy();
  });

  it('runs the report and posts to /reports/cross-agp-disposals with the selected date range', async () => {
    let capturedUrl = null;
    let capturedOptions = null;
    api.authenticatedFetchJSON.mockImplementation((url, options) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/reports/cross-agp-disposals')) {
        capturedUrl = url;
        capturedOptions = options;
        return Promise.resolve(FLAGGED_REPORT);
      }
      return Promise.resolve({});
    });

    render(<DisposalMismatchReport />);
    await runReport();

    expect(capturedOptions.method).toBe('POST');
    expect(capturedUrl).toContain('start_date=');
    expect(capturedUrl).toContain('end_date=');
    expect(screen.getByText('WP/1/2026')).toBeTruthy();
  });

  it('shows the flagged case with appearances, disposal date, and the other AGP name', async () => {
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/reports/cross-agp-disposals')) return Promise.resolve(FLAGGED_REPORT);
      return Promise.resolve({});
    });

    render(<DisposalMismatchReport />);
    await runReport();

    expect(screen.getByText('WP/1/2026')).toBeTruthy();
    expect(screen.getByText(/2026-08-07/)).toBeTruthy();
    expect(screen.getByText('2026-09-08')).toBeTruthy();
    expect(screen.getByText('Rajan Pawar')).toBeTruthy();
    expect(screen.getByText('Flagged').closest('.card').textContent).toContain('1');

    // The order PDF link must go through the backend proxy (which streams
    // via service-account credentials), never the raw GCS object URL --
    // the bucket isn't publicly readable, so a direct link 403s.
    const viewLink = screen.getByText('View');
    expect(viewLink.getAttribute('href')).toBe('https://api.test/orders/pdf/2026-09-08-WP-1-2026');
    expect(viewLink.getAttribute('href')).not.toContain('storage.googleapis.com');
  });

  it('shows a friendly empty state when nothing is flagged', async () => {
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/reports/cross-agp-disposals')) return Promise.resolve(EMPTY_REPORT);
      return Promise.resolve({});
    });

    render(<DisposalMismatchReport />);
    await runReport();

    expect(screen.getByText(/No mismatches found/)).toBeTruthy();
    expect(screen.getByText('Same AGP disposed').closest('.card').textContent).toContain('3');
  });

  it('an admin can pick a specific AGP and the report includes user_name', async () => {
    mockAdminUsers(['Pooja Deshpande']);
    let capturedUrl = null;
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: ['Pooja Deshpande'] });
      if (url.startsWith('/reports/cross-agp-disposals')) {
        capturedUrl = url;
        return Promise.resolve(EMPTY_REPORT);
      }
      return Promise.resolve({});
    });

    render(<DisposalMismatchReport />);
    await waitFor(() => screen.getByText('Pooja Deshpande'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Pooja Deshpande' } });
    await runReport();

    expect(capturedUrl).toContain('user_name=Pooja%20Deshpande');
  });
});
