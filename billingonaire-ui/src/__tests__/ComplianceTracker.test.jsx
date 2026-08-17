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
  authenticatedFetch: vi.fn(),
  getApiUrl: (path) => `https://api.test${path}`,
}));

import * as api from '../lib/api';
import ComplianceTracker from '../ComplianceTracker';

const DISPOSED_REPORT = {
  count: 1,
  disposed_count: 1,
  newly_scanned: 0,
  llm_errors: 0,
  ai_available: true,
  results: [
    {
      case_ref: 'WP/1/2026',
      board_date: '2026-07-08',
      order_date: '2026-07-08',
      order_category: 'DISPOSED_OFF',
      order_link: 'https://storage.example/order.pdf',
      directives: [],
    },
  ],
};

const DIRECTIVE_REPORT = {
  count: 1,
  disposed_count: 0,
  newly_scanned: 1,
  llm_errors: 0,
  ai_available: true,
  results: [
    {
      case_ref: 'WP/7967/2026',
      board_date: '2026-07-08',
      order_date: '2026-07-08',
      order_category: 'HEARD_AND_ADJOURNED',
      order_link: 'https://storage.example/order.pdf',
      directives: [
        {
          directive_type: 'FILE_REPLY_AFFIDAVIT',
          description: 'Respondents shall file their reply affidavits on or before 13th August 2026.',
          deadline_date: '2026-08-13',
        },
      ],
    },
  ],
};

// authenticatedFetchJSON is called twice on mount for a signed-in admin
// (once for /admin/active-users), then once per scan -- default every
// mock to the admin-users response so runScan's own mockResolvedValueOnce
// isn't shadowed by a stale queued response from mount.
const mockAdminUsers = (names = []) => {
  api.authenticatedFetchJSON.mockImplementation((url) => {
    if (url === '/admin/active-users') {
      return Promise.resolve({ user_names: names });
    }
    return Promise.resolve({});
  });
};

const runScan = async () => {
  fireEvent.click(screen.getByText('Run Compliance Scan'));
  await waitFor(() => {
    expect(screen.queryByText('Scanning...')).not.toBeInTheDocument();
  });
};

describe('ComplianceTracker', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockReset();
    api.authenticatedFetch.mockReset();
    mockAdminUsers();
    window.URL.createObjectURL = vi.fn(() => 'blob:fake');
    window.URL.revokeObjectURL = vi.fn();
  });

  it('renders the Compliance Tracker heading', () => {
    render(<ComplianceTracker />);
    expect(screen.getByText(/Compliance Tracker/i)).toBeTruthy();
  });

  it('runs a scan and posts to /compliance/scan with the selected date range', async () => {
    mockAdminUsers();
    api.authenticatedFetchJSON.mockImplementation((url, options) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/compliance/scan')) {
        expect(options.method).toBe('POST');
        return Promise.resolve(DISPOSED_REPORT);
      }
      return Promise.resolve({});
    });

    render(<ComplianceTracker />);
    await runScan();

    expect(screen.getByText('WP/1/2026')).toBeTruthy();
    expect(screen.getByText('Disposed cases').closest('.card').textContent).toContain('1');
  });

  it('shows the directive description and a deadline badge for a HEARD_AND_ADJOURNED result', async () => {
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/compliance/scan')) return Promise.resolve(DIRECTIVE_REPORT);
      return Promise.resolve({});
    });

    render(<ComplianceTracker />);
    await runScan();

    expect(screen.getByRole('button', { name: /File reply affidavit/ })).toBeTruthy();
    expect(screen.getByText(/Respondents shall file their reply affidavits/)).toBeTruthy();
    expect(screen.getByText(/2026-08-13/)).toBeTruthy();
  });

  it('shows a warning when AI directive extraction is not configured', async () => {
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/compliance/scan')) {
        return Promise.resolve({ ...DISPOSED_REPORT, ai_available: false });
      }
      return Promise.resolve({});
    });

    render(<ComplianceTracker />);
    await runScan();

    expect(screen.getByText(/AI directive extraction is not configured/)).toBeTruthy();
    // Disposed cases still show even without AI.
    expect(screen.getByText('WP/1/2026')).toBeTruthy();
  });

  it('the Disposed filter narrows the table to disposed-only rows', async () => {
    const mixedReport = {
      ...DIRECTIVE_REPORT,
      disposed_count: 1,
      results: [...DIRECTIVE_REPORT.results, ...DISPOSED_REPORT.results],
    };
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/compliance/scan')) return Promise.resolve(mixedReport);
      return Promise.resolve({});
    });

    render(<ComplianceTracker />);
    await runScan();

    expect(screen.getByText('WP/7967/2026')).toBeTruthy();
    expect(screen.getByText('WP/1/2026')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^Disposed/ }));

    expect(screen.getByText('WP/1/2026')).toBeTruthy();
    expect(screen.queryByText('WP/7967/2026')).not.toBeInTheDocument();
  });

  it('an admin can pick a specific AGP and the scan includes user_name', async () => {
    mockAdminUsers(['Pooja Deshpande']);
    let capturedUrl = null;
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: ['Pooja Deshpande'] });
      if (url.startsWith('/compliance/scan')) {
        capturedUrl = url;
        return Promise.resolve(DISPOSED_REPORT);
      }
      return Promise.resolve({});
    });

    render(<ComplianceTracker />);
    await waitFor(() => screen.getByText('Pooja Deshpande'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Pooja Deshpande' } });
    await runScan();

    expect(capturedUrl).toContain('user_name=Pooja%20Deshpande');
  });

  it('exports the report as Excel after a scan', async () => {
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/compliance/scan')) return Promise.resolve(DIRECTIVE_REPORT);
      return Promise.resolve({});
    });
    const fakeBlob = new Blob(['fake xlsx bytes']);
    let capturedUrl = null;
    api.authenticatedFetch.mockImplementation((url) => {
      capturedUrl = url;
      return Promise.resolve({ blob: () => Promise.resolve(fakeBlob) });
    });

    render(<ComplianceTracker />);
    await runScan();

    expect(screen.queryByText('Export Excel (XLSX)')).toBeTruthy();
    fireEvent.click(screen.getByText('Export Excel (XLSX)'));

    await waitFor(() => expect(api.authenticatedFetch).toHaveBeenCalled());
    expect(capturedUrl).toContain('/compliance/export/excel');
    expect(capturedUrl).toContain('start_date=');
    expect(window.URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);
  });

  it('does not show the export button before a scan has run', () => {
    render(<ComplianceTracker />);
    expect(screen.queryByText('Export Excel (XLSX)')).not.toBeInTheDocument();
  });
});
