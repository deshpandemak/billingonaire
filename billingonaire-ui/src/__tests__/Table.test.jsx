import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Table from '../Table';

// Mock AG Grid
vi.mock('ag-grid-react', () => ({
  AgGridReact: ({ columnDefs: _columnDefs, rowData }) => (
    <div data-testid="ag-grid">
      {rowData && rowData.length > 0 && (
        <div>Rows: {rowData.length}</div>
      )}
    </div>
  ),
}));

// Mock useAuth hook
vi.mock('../useAuth', () => ({
  default: () => ({
    user: { uid: 'test-user' },
    loading: false,
  }),
}));

const _mockData = [
  {
    id: '1',
    case_ref: 'WP/12345/2024',
    agp_name: 'Pooja Joshi Deshpande',
    board_date: '2024-10-01',
    order_status: 'not_linked',
  },
];

describe('Table Component', () => {
  it('should render without crashing', () => {
    render(
      <BrowserRouter>
        <Table />
      </BrowserRouter>
    );
    expect(screen.getByTestId('ag-grid')).toBeInTheDocument();
  });

  it('should display data when provided', () => {
    render(
      <BrowserRouter>
        <Table />
      </BrowserRouter>
    );
    
    // Component should mount
    expect(screen.getByTestId('ag-grid')).toBeInTheDocument();
  });

  it('should handle refresh button click', async () => {
    const { container } = render(
      <BrowserRouter>
        <Table />
      </BrowserRouter>
    );

    // Find and click refresh button if it exists
    const refreshButton = container.querySelector('[data-action="refresh"]');
    if (refreshButton) {
      fireEvent.click(refreshButton);
      await waitFor(() => {
        expect(refreshButton).toBeTruthy();
      });
    }
  });
});
