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
import BillGeneration from '../BillGeneration';

const BILL_DATA = {
  user_name: 'self',
  total_entries: 3,
  total_fees: 5625,
  bill_entries: [
    {
      id: 'case1', date: '2026-07-01', case_detail: 'WP/1/2026',
      case_type: 'WP', case_no: '1', case_year: '2026',
      parties_name: 'A vs B', results: 'WP DISPOSED OF', fees_rs: 2500,
      order_link: 'https://storage.example/1.pdf', order_category: 'DISPOSED_OFF',
      confidence_score: 1.0, order_category_confidence: 0.9,
    },
    {
      id: 'case2', date: '2026-07-02', case_detail: 'WP/2/2026',
      case_type: 'WP', case_no: '2', case_year: '2026',
      parties_name: 'C vs D', results: 'HEARD & ADJN.', fees_rs: 1875,
      order_link: 'https://storage.example/2.pdf', order_category: 'HEARD_AND_ADJOURNED',
      confidence_score: 1.0, order_category_confidence: 0.9,
    },
    {
      id: 'case3', date: '2026-07-03', case_detail: 'WP/3/2026',
      case_type: 'WP', case_no: '3', case_year: '2026',
      parties_name: 'E vs F', results: '*ADJOURNED*', fees_rs: 1250,
      order_link: null, order_category: null,
      confidence_score: 1.0, order_category_confidence: null,
    },
  ],
};

const mockAdminUsers = (names = []) => {
  api.authenticatedFetchJSON.mockImplementation((url) => {
    if (url === '/admin/active-users') return Promise.resolve({ user_names: names });
    return Promise.resolve({});
  });
};

const generate = async () => {
  fireEvent.click(screen.getByText('Generate Bill Data'));
  await waitFor(() => {
    expect(screen.getByText('Bill Entries')).toBeTruthy();
  });
};

describe('BillGeneration', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockReset();
  });

  it('shows an order-category breakdown for the generated bill', async () => {
    mockAdminUsers();
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') return Promise.resolve({ user_names: [] });
      if (url.startsWith('/bills/generate')) return Promise.resolve(BILL_DATA);
      return Promise.resolve({});
    });

    render(<BillGeneration />);
    await generate();

    expect(screen.getByText('Disposed of: 1')).toBeTruthy();
    expect(screen.getByText('Heard & adjourned: 1')).toBeTruthy();
    expect(screen.getByText('Adjourned: 0')).toBeTruthy();
    expect(screen.getByText('Assumed (no order): 1')).toBeTruthy();
  });

  it('persists an admin outcome correction to the case record', async () => {
    mockAdminUsers(['Pooja Makarand Joshi Deshpande']);
    let overrideCall = null;
    api.authenticatedFetchJSON.mockImplementation((url, options) => {
      if (url === '/admin/active-users') {
        return Promise.resolve({ user_names: ['Pooja Makarand Joshi Deshpande'] });
      }
      if (url.startsWith('/bills/generate')) return Promise.resolve(BILL_DATA);
      if (url.startsWith('/admin/orders/') && url.endsWith('/override')) {
        overrideCall = { url, body: JSON.parse(options.body) };
        return Promise.resolve({ success: true });
      }
      return Promise.resolve({});
    });

    render(<BillGeneration />);
    await waitFor(() => screen.getByText('Generate Bill Data'));
    await generate();

    // Edit the DISPOSED_OFF row (case1) and change its outcome.
    const editButtons = screen.getAllByText('✏️');
    fireEvent.click(editButtons[0]);

    const outcomeSelect = screen.getAllByTitle(/Saving a change here also corrects the case record/)[0];
    fireEvent.change(outcomeSelect, { target: { value: 'ADJOURNED' } });

    const saveButton = screen.getByText('✓');
    fireEvent.click(saveButton);

    await waitFor(() => expect(overrideCall).not.toBeNull());
    expect(overrideCall.url).toContain('/admin/orders/WP-1-2026/override');
    expect(overrideCall.body).toMatchObject({
      order_category: 'ADJOURNED',
      order_date: '2026-07-01',
    });

    await waitFor(() => {
      expect(screen.getByText(/Correction saved to the case record/)).toBeTruthy();
    });
  });

  it('does not attempt to persist a correction for a non-admin user', async () => {
    mockAdminUsers();
    api.authenticatedFetchJSON.mockImplementation((url) => {
      if (url === '/admin/active-users') {
        // Non-admin: /admin/active-users itself fails (mirrors real 403 behaviour).
        return Promise.reject(new Error('403'));
      }
      if (url.startsWith('/bills/generate')) return Promise.resolve(BILL_DATA);
      if (url.startsWith('/admin/orders/')) {
        throw new Error('should not be called for a non-admin user');
      }
      return Promise.resolve({});
    });

    render(<BillGeneration />);
    await generate();

    const editButtons = screen.getAllByText('✏️');
    fireEvent.click(editButtons[0]);
    fireEvent.click(screen.getByText('✓'));

    // No override call should ever be attempted; nothing to await on beyond
    // the edit closing back to the read view.
    await waitFor(() => {
      expect(screen.queryByText('✓')).not.toBeInTheDocument();
    });
  });
});
