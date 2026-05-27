import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('ag-grid-react', () => {
  const AgGridReact = vi.fn(({ rowData }) => {
    return React.createElement(
      'div',
      { 'data-testid': 'ag-grid-mock' },
      rowData?.map((row, i) =>
        React.createElement('div', { key: i, 'data-testid': 'grid-row' }, row.case_no)
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

describe('Table Component', () => {
  beforeEach(() => {
    api.authenticatedFetchJSON.mockResolvedValue(mockRows);
  });

  it('renders the Search & Order Management heading', () => {
    render(<Table />);
    expect(screen.getByText(/Search & Order Management/i)).toBeTruthy();
  });

  it('renders the Search Criteria section toggle', () => {
    render(<Table />);
    expect(screen.getByText(/Search Criteria/i)).toBeTruthy();
  });

  it('opens the search form and shows Search Cases button on toggle click', async () => {
    render(<Table />);
    fireEvent.click(screen.getByText(/Search Criteria/i));
    await waitFor(() => {
      expect(screen.getByText(/Search Cases/i)).toBeTruthy();
    });
  });

  it('opens the search form and shows Clear Filters button on toggle click', async () => {
    render(<Table />);
    fireEvent.click(screen.getByText(/Search Criteria/i));
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

  it('shows search error when the API throws', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('Network error'));
    render(<Table />);
    await waitFor(() => {
      expect(screen.getByText(/Search failed/i)).toBeTruthy();
    });
  });
});
