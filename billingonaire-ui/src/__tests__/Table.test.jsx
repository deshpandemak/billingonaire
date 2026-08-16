import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('ag-grid-react', () => {
  const AgGridReact = vi.fn(({ rowData, columnDefs }) => {
    const findCol = (headerName) => columnDefs?.find((c) => c.headerName === headerName);
    const gpInBoardCol = findCol('AGP on board');
    const gpInOrderCol = findCol('AGP in order');
    return React.createElement(
      'div',
      { 'data-testid': 'ag-grid-mock' },
      rowData?.map((row, i) =>
        React.createElement(
          'div',
          { key: i, 'data-testid': 'grid-row' },
          row.case_no,
          React.createElement(
            'span',
            { 'data-testid': 'gp-in-board' },
            gpInBoardCol?.valueGetter({ data: row })
          ),
          React.createElement(
            'span',
            { 'data-testid': 'gp-in-order' },
            gpInOrderCol?.valueGetter({ data: row })
          ),
          // Normalized (post normalizeCaseRecord) values, straight off rowData --
          // these are the fields the "Court Order"/"Outcome" columns read.
          React.createElement('span', { 'data-testid': 'order-link' }, row.order_link || ''),
          React.createElement('span', { 'data-testid': 'order-category' }, row.order_category || ''),
          React.createElement('span', { 'data-testid': 'order-date' }, row.order_date || '')
        )
      )
    );
  });
  return { AgGridReact };
});

vi.mock('ag-grid-community', () => ({
  ModuleRegistry: { registerModules: vi.fn() },
  AllCommunityModule: {},
}));

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
}));

vi.mock('../components/CaseDetailModal', () => ({
  default: vi.fn(() => null),
}));

import * as api from '../lib/api';
import Table from '../Table';

const mockRows = [
  {
    case_no: 'WP/1/2024',
    board_date: '2024-01-15',
    respondent_lawyer: 'AGP Sharma',
    order_status: 'not_linked',
  },
  {
    case_no: 'WP/2/2024',
    board_date: '2024-01-15',
    respondent_lawyer: 'AGP Verma',
    order_status: 'analysed',
  },
];

const openSearchForm = () => fireEvent.click(screen.getByText('Show Filters'));

describe('Table Component', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockResolvedValue(mockRows);
  });

  it('renders the Search & Order Management heading', () => {
    render(<Table />);
    expect(screen.getByText(/Search & Order Management/i)).toBeTruthy();
  });

  it('renders the Search Criteria section title', () => {
    render(<Table />);
    expect(screen.getByText(/Search Criteria/i)).toBeTruthy();
  });

  it('renders the Show Filters toggle button', () => {
    render(<Table />);
    expect(screen.getByText('Show Filters')).toBeTruthy();
  });

  it('opens the search form and shows Search Cases button on toggle click', async () => {
    render(<Table />);
    openSearchForm();
    await waitFor(() => {
      expect(screen.getByText(/Search Cases/i)).toBeTruthy();
    });
  });

  it('opens the search form and shows Clear Filters button on toggle click', async () => {
    render(<Table />);
    openSearchForm();
    await waitFor(() => {
      expect(screen.getByText('Clear Filters')).toBeTruthy();
    });
  });

  it('renders the AG Grid after data loads', async () => {
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByTestId('ag-grid-mock')).toBeTruthy();
    });
  });

  it('shows record count after data loads', async () => {
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByText(/2 records/i)).toBeTruthy();
    });
  });

  it('shows grid rows for each returned record', async () => {
    render(<Table />);
    await waitFor(() => {
      const rows = screen.getAllByTestId('grid-row');
      expect(rows).toHaveLength(2);
    });
  });

  it('calls authenticatedFetchJSON with /get-data on initial load', async () => {
    render(<Table />);
    await waitFor(() => {
      expect(api.authenticatedFetchJSON).toHaveBeenCalledWith(
        '/get-data',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('"AGP in order" only shows names extracted from the order, not the board assignment', async () => {
    // Regression: assigned_government_pleaders is the board's respondent_lawyer
    // assignment (set at board upload, before any order exists) and must never
    // be folded into the "AGP in order" figure -- only government_pleader
    // (extracted from the downloaded order PDF) belongs there.
    api.authenticatedFetchJSON.mockResolvedValueOnce([
      {
        case_no: 'WP/3/2024',
        board_date: '2024-01-15',
        respondent_lawyer: 'AGP Board-Only',
        additional_respondent_lawyers: [],
        assigned_government_pleaders: ['AGP Board-Only'],
        government_pleader: [],
        order_status: 'not_linked',
      },
    ]);
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByTestId('gp-in-board').textContent).toBe('AGP Board-Only');
    });
    expect(screen.getByTestId('gp-in-order').textContent).toBe('-');
  });

  it('"AGP in order" shows names once the order analysis has extracted a GP', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce([
      {
        case_no: 'WP/4/2024',
        board_date: '2024-01-15',
        respondent_lawyer: 'AGP Board-Only',
        assigned_government_pleaders: ['AGP Board-Only'],
        government_pleader: ['AGP From Order'],
        order_status: 'analysed',
      },
    ]);
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByTestId('gp-in-order').textContent).toBe('AGP From Order');
    });
  });

  it('a board date with no analysed order of its own never borrows a different date\'s order', async () => {
    // Regression: WP/9336/2025's 3rd-July row was showing the 30th-July
    // order (link, category, GP) because the row-normalizer fell back to
    // order_history's *latest* entry whenever this row's own date-matched
    // fields were empty. order_history holds every hearing for the case,
    // so "latest" can be a completely different date than this row.
    api.authenticatedFetchJSON.mockResolvedValueOnce([
      {
        case_no: 'WP/9336/2025',
        board_date: '2025-07-03',
        // Backend (Board._hydrate_with_case_details) found no order dated
        // 2025-07-03, so these are the honest, un-matched defaults:
        order_link: null,
        order_status: 'not_linked',
        order_category: null,
        order_date: null,
        government_pleader: [],
        // The case's actual order history -- a later, unrelated hearing.
        order_history: [
          {
            order_date: '2025-07-30',
            board_date: '2025-07-30',
            order_link: 'https://storage.example/2025-07-30.pdf',
            order_status: 'analysed',
            order_category: 'DISPOSED_OFF',
            government_pleader: ['AGP From 30th July'],
          },
        ],
      },
    ]);
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByTestId('gp-in-order').textContent).toBe('-');
    });
    expect(screen.getByTestId('order-link').textContent).toBe('');
    expect(screen.getByTestId('order-category').textContent).toBe('');
    expect(screen.getByTestId('order-date').textContent).toBe('');
  });

  it('shows search error inside the form when the API throws', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('Network error'));
    render(<Table />);
    await waitFor(() => screen.getByText('Show Filters'));
    openSearchForm();
    await waitFor(() => {
      expect(screen.getByText(/Search failed/i)).toBeTruthy();
    });
  });
});
