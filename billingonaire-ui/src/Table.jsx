import React, { useEffect, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { authenticatedFetch } from './lib/api';
import './styles/professional.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

const Table = () => {
  const [data, setData] = useState([]);
  const [editedData, setEditedData] = useState([]);
  const [searchCriteria, setSearchCriteria] = useState({
    startDate: '',
    endDate: '',
    advocateName: '',
    caseNumber: '',
    caseType: '',
    caseYear: '',
    caseStage: ''
  });
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    // By default, show today's data
    const today = new Date().toISOString().split('T')[0];
    setSearchCriteria((prev) => ({ ...prev, startDate: today, endDate: today }));
    fetchData({ ...searchCriteria, startDate: today, endDate: today });
    // eslint-disable-next-line
  }, []);

  const fetchData = async (criteria = searchCriteria) => {
    if (!criteria.startDate && !criteria.endDate && !criteria.advocateName && !criteria.caseNumber && !criteria.caseType && !criteria.caseYear && !criteria.caseStage) {
      alert('Please fill at least one search criteria');
      return;
    }
    try {
      const result = await authenticatedFetch('/get-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: criteria.startDate,
          end_date: criteria.endDate,
          advocate_name: criteria.advocateName,
          case_number: criteria.caseNumber,
          case_type: criteria.caseType,
          case_year: criteria.caseYear,
          case_stage: criteria.caseStage
        })
      });
      setData(result);
      setEditedData(JSON.parse(JSON.stringify(result)));
    } catch (e) {
      console.error('Search failed:', e);
      alert('Search failed. Please check your criteria and try again.');
    }
  };

  const saveData = async () => {
    try {
      await authenticatedFetch('/save-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editedData)
      });
      alert('Data saved successfully!');
    } catch (e) {
      console.error('Failed to save data:', e.message);
      alert('Failed to save data. Please try again.');
    }
  };

  const cancelEdit = () => {
    setEditedData(JSON.parse(JSON.stringify(data)));
  };

  const addRow = () => {
    setEditedData((prev) => [...prev, {}]);
  };

  const deleteRow = (index) => {
    setEditedData((prev) => prev.filter((_, i) => i !== index));
  };

  // AG Grid column definitions
  const columnDefs = [
    { 
      headerName: 'Board Date', 
      field: 'board_date', 
      sortable: true, 
      filter: 'agDateColumnFilter',
      editable: true,
      width: 150
    },
    { 
      headerName: 'Case Type', 
      field: 'case_type', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 120
    },
    { 
      headerName: 'Case Number', 
      field: 'case_no', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 150
    },
    { 
      headerName: 'Case Year', 
      field: 'case_year', 
      sortable: true, 
      filter: 'agNumberColumnFilter',
      editable: true,
      width: 120
    },
    { 
      headerName: 'Petitioner', 
      field: 'petitioner_name', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 200
    },
    { 
      headerName: 'Respondent', 
      field: 'respondent_name', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 200
    },
    { 
      headerName: 'AGP Name', 
      field: 'respondent_lawyer', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 180
    },
    { 
      headerName: 'Court Order', 
      field: 'court_order', 
      sortable: true, 
      filter: 'agSetColumnFilter',
      editable: true,
      width: 150,
      cellStyle: params => {
        if (params.value === 'DISPOSAL') return { backgroundColor: '#d4edda', color: '#155724' };
        if (params.value === 'ADJOURNMENT') return { backgroundColor: '#fff3cd', color: '#856404' };
        if (params.value === 'HEARD & ADJRN') return { backgroundColor: '#cce7ff', color: '#004085' };
        return null;
      }
    },
    { 
      headerName: 'Actions', 
      field: 'actions',
      cellRenderer: 'deleteButtonRenderer',
      width: 100,
      pinned: 'right'
    }
  ];

  // Custom cell renderer for delete button
  const DeleteButtonRenderer = (props) => {
    const handleDelete = () => {
      const rowIndex = props.rowIndex;
      setEditedData(prev => prev.filter((_, i) => i !== rowIndex));
    };

    return (
      <button 
        className="btn-professional btn-danger" 
        style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
        onClick={handleDelete}
      >
        Delete
      </button>
    );
  };

  const components = {
    deleteButtonRenderer: DeleteButtonRenderer
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">🔍 Advanced Search & Data Management</h1>
        <p className="dashboard-subtitle">
          Search court cases and AGP assignments with powerful filters and professional data grid
        </p>
      </div>

      <div className="dashboard-section">
        {/* Elegant Search Criteria Card */}
        <div className="card-professional" style={{ marginBottom: 'var(--spacing-xl)' }}>
          <div className="card-header">
            <h2 className="section-title">📋 Search Criteria</h2>
            <button 
              className="btn-professional btn-secondary"
              onClick={() => setSearchOpen(!searchOpen)}
              style={{ fontSize: '0.875rem' }}
            >
              {searchOpen ? 'Hide Filters' : 'Show Filters'}
            </button>
          </div>
          {searchOpen && (
            <div className="card-body">
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', 
                gap: 'var(--spacing-lg)',
                marginBottom: 'var(--spacing-lg)'
              }}>
                <div className="form-group">
                  <label className="form-label">Start Date</label>
                  <input
                    type="date"
                    className="form-control"
                    value={searchCriteria.startDate}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, startDate: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">End Date</label>
                  <input
                    type="date"
                    className="form-control"
                    value={searchCriteria.endDate}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, endDate: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">AGP/Advocate Name</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="Enter advocate name..."
                    value={searchCriteria.advocateName}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, advocateName: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Case Number</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="Enter case number..."
                    value={searchCriteria.caseNumber}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, caseNumber: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Case Type</label>
                  <select
                    className="form-control"
                    value={searchCriteria.caseType}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, caseType: e.target.value }))}
                  >
                    <option value="">All Case Types</option>
                    <option value="WP">WP - Writ Petition</option>
                    <option value="IA">IA - Interim Application</option>
                    <option value="CP">CP - Civil Petition</option>
                    <option value="PIL">PIL - Public Interest Litigation</option>
                    <option value="CAW">CAW - Civil Appeal Writ</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Case Year</label>
                  <input
                    type="number"
                    className="form-control"
                    placeholder="e.g., 2025"
                    value={searchCriteria.caseYear}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, caseYear: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Case Stage</label>
                  <select
                    className="form-control"
                    value={searchCriteria.caseStage}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, caseStage: e.target.value }))}
                  >
                    <option value="">All Stages</option>
                    <option value="Registration">Registration</option>
                    <option value="Stamp">Stamp</option>
                  </select>
                </div>
                <div style={{ display: 'flex', alignItems: 'end', gap: 'var(--spacing-md)' }}>
                  <button 
                    className="btn-professional btn-primary"
                    onClick={() => fetchData()}
                    style={{ flex: 1 }}
                  >
                    🔍 Search Cases
                  </button>
                  <button 
                    className="btn-professional btn-secondary"
                    onClick={() => {
                      setSearchCriteria({
                        startDate: '',
                        endDate: '',
                        advocateName: '',
                        caseNumber: '',
                        caseType: '',
                        caseYear: '',
                        caseStage: ''
                      });
                    }}
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Professional AG Grid */}
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📊 Case Data ({data.length} records)</h2>
            <div style={{ display: 'flex', gap: 'var(--spacing-md)' }}>
              <button 
                className="btn-professional btn-success"
                onClick={addRow}
                style={{ fontSize: '0.875rem' }}
              >
                + Add Row
              </button>
              <button 
                className="btn-professional btn-primary"
                onClick={saveData}
                style={{ fontSize: '0.875rem' }}
              >
                💾 Save Changes
              </button>
              <button 
                className="btn-professional btn-secondary"
                onClick={cancelEdit}
                style={{ fontSize: '0.875rem' }}
              >
                ↶ Cancel
              </button>
            </div>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <div 
              className="ag-theme-alpine"
              style={{ 
                height: '600px', 
                width: '100%',
                '--ag-font-family': 'var(--font-main)',
                '--ag-font-size': '14px',
                '--ag-header-background-color': 'var(--gray-50)',
                '--ag-header-foreground-color': 'var(--gray-900)',
                '--ag-odd-row-background-color': 'var(--gray-25)',
                '--ag-border-color': 'var(--gray-200)'
              }}
            >
              <AgGridReact
                rowData={editedData}
                columnDefs={columnDefs}
                components={components}
                defaultColDef={{
                  flex: 1,
                  minWidth: 100,
                  resizable: true,
                  sortable: true,
                  filter: true,
                  editable: true
                }}
                gridOptions={{
                  animateRows: true,
                  pagination: true,
                  paginationPageSize: 50,
                  domLayout: 'normal',
                  rowSelection: { mode: 'multiRow' }
                }}
                onCellValueChanged={(params) => {
                  const rowIndex = params.rowIndex;
                  const field = params.colDef.field;
                  const newValue = params.newValue;
                  setEditedData(prev => prev.map((row, index) => 
                    index === rowIndex ? { ...row, [field]: newValue } : row
                  ));
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Table;
