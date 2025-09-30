import React, { useEffect, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { authenticatedFetchJSON } from './lib/api';
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
  const [appliedCriteria, setAppliedCriteria] = useState({
    startDate: '',
    endDate: '',
    advocateName: '',
    caseNumber: '',
    caseType: '',
    caseYear: '',
    caseStage: ''
  });
  const [searchOpen, setSearchOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [showOrderDrawer, setShowOrderDrawer] = useState(false);
  const [processingOrders, setProcessingOrders] = useState(new Set());

  useEffect(() => {
    // By default, show last 3 months data
    const today = new Date();
    const threeMonthsAgo = new Date();
    threeMonthsAgo.setMonth(today.getMonth() - 3);
    
    const endDate = today.toISOString().split('T')[0];
    const startDate = threeMonthsAgo.toISOString().split('T')[0];
    
    const initialCriteria = { 
      startDate, 
      endDate, 
      advocateName: '', 
      caseNumber: '', 
      caseType: '', 
      caseYear: '', 
      caseStage: '' 
    };
    
    setSearchCriteria(initialCriteria);
    setAppliedCriteria(initialCriteria);
    fetchData(initialCriteria);
    // eslint-disable-next-line
  }, []);

  const fetchData = async (criteria = searchCriteria) => {
    if (!criteria.startDate && !criteria.endDate && !criteria.advocateName && !criteria.caseNumber && !criteria.caseType && !criteria.caseYear && !criteria.caseStage) {
      setSearchError('Please fill at least one search criteria');
      return;
    }

    setIsSearching(true);
    setSearchError('');
    
    // Store the criteria that are actually being applied
    setAppliedCriteria({ ...criteria });
    
    try {
      const result = await authenticatedFetchJSON('/get-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          startDate: criteria.startDate,
          endDate: criteria.endDate,
          advocateName: criteria.advocateName,
          caseNumber: criteria.caseNumber,
          caseType: criteria.caseType,
          caseYear: criteria.caseYear,
          caseStage: criteria.caseStage
        })
      });
      console.log('🔍 API Response received:', result);
      console.log('📊 Data type:', typeof result, 'Length:', Array.isArray(result) ? result.length : 'Not array');
      console.log('📋 First 3 records:', Array.isArray(result) ? result.slice(0, 3) : result);
      console.log('🎯 Applied search criteria:', criteria);
      setData(result);
      setEditedData(JSON.parse(JSON.stringify(result)));
      console.log('✅ Data set to state. Current data length:', Array.isArray(result) ? result.length : 'Not array');
    } catch (e) {
      console.error('Search failed:', e);
      setSearchError('Search failed. Please check your criteria and try again.');
    } finally {
      setIsSearching(false);
    }
  };

  const saveData = async () => {
    try {
      await authenticatedFetchJSON('/save-data', {
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
      headerName: 'Order Status', 
      field: 'order_downloaded', 
      sortable: true, 
      filter: false,
      width: 130,
      flex: 0,
      cellRenderer: 'orderStatusRenderer'
    },
    { 
      headerName: 'Order Analysis', 
      field: 'order_category', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      width: 150,
      flex: 0,
      cellStyle: params => {
        if (params.value === 'WP DISPOSED OF') return { backgroundColor: '#d4edda', color: '#155724' };
        if (params.value === 'ADJOURNED') return { backgroundColor: '#fff3cd', color: '#856404' };
        if (params.value === 'HEARD & ADJN') return { backgroundColor: '#cce7ff', color: '#004085' };
        return null;
      }
    },
    { 
      headerName: 'Order Actions', 
      field: 'order_actions',
      cellRenderer: 'orderActionsRenderer',
      width: 300,
      flex: 0,
      suppressSizeToFit: true,
      pinned: 'right'
    },
    { 
      headerName: 'Actions', 
      field: 'actions',
      cellRenderer: 'deleteButtonRenderer',
      width: 100,
      flex: 0,
      suppressSizeToFit: true,
      pinned: 'right'
    }
  ];

  // Custom cell renderer for order status badge
  const OrderStatusRenderer = (props) => {
    const { data } = props;
    const hasOrder = data?.order_downloaded || data?.order_link;
    const hasAnalysis = data?.order_analysis_completed;
    
    if (!hasOrder) {
      return <span className="badge" style={{ backgroundColor: '#6c757d', color: 'white' }}>No Order</span>;
    }
    
    if (hasAnalysis) {
      return <span className="badge" style={{ backgroundColor: '#28a745', color: 'white' }}>✓ Analyzed</span>;
    }
    
    return <span className="badge" style={{ backgroundColor: '#17a2b8', color: 'white' }}>Downloaded</span>;
  };

  // Custom cell renderer for order action buttons
  const OrderActionsRenderer = (props) => {
    const { data } = props;
    const caseId = data?.id;
    const caseRef = `${data?.case_type}/${data?.case_no}/${data?.case_year}`;
    const hasOrder = data?.order_downloaded || data?.order_link;
    const isProcessing = processingOrders.has(caseId);
    
    return (
      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
        {hasOrder && data?.order_link ? (
          <>
            <button 
              className="btn-professional btn-primary" 
              style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
              onClick={() => window.open(data.order_link, '_blank')}
              title="View Order PDF"
            >
              📄 View
            </button>
            {!data?.order_analysis_completed && (
              <button 
                className="btn-professional btn-success" 
                style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
                onClick={() => handleAnalyzeOrder(caseId, caseRef)}
                disabled={isProcessing}
                title="Analyze Order"
              >
                {isProcessing ? '⏳' : '🤖'} Analyze
              </button>
            )}
          </>
        ) : (
          <button 
            className="btn-professional btn-primary" 
            style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
            onClick={() => handleDownloadOrder(caseId, caseRef, data)}
            disabled={isProcessing}
            title="Download from Court"
          >
            {isProcessing ? '⏳ Downloading...' : '⬇️ Download'}
          </button>
        )}
        {data?.order_analysis_completed && (
          <button 
            className="btn-professional btn-info" 
            style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem', backgroundColor: '#17a2b8' }}
            onClick={() => viewOrderDetails(caseId)}
            title="View Analysis Details"
          >
            📊 Details
          </button>
        )}
      </div>
    );
  };

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

  // Order management functions
  const handleDownloadOrder = async (caseId, caseRef, caseData) => {
    setProcessingOrders(prev => new Set(prev).add(caseId));
    try {
      const response = await authenticatedFetchJSON(`/auto-orders/process-case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: caseId,
          case_ref: caseRef,
          board_date: caseData.board_date
        })
      });

      console.log('Download response:', response);

      if (response.download_success && response.order_link) {
        // Download successful and we have the order link
        const hasAnalysis = response.analysis_success;
        const category = response.analysis_data?.order_category;
        
        let message = `✅ Order downloaded successfully for ${caseRef}!\n\n`;
        message += `📄 Order Link: ${response.order_link}\n`;
        
        if (hasAnalysis && category) {
          message += `\n🤖 Analysis Complete:\n`;
          message += `Category: ${category}\n`;
          message += `Confidence: ${(response.analysis_data?.order_category_confidence || 0) * 100}%`;
        }
        
        alert(message);
        
        // Refresh the data to show updated order status
        await fetchData();
      } else if (response.error) {
        alert(`❌ Failed to download order for ${caseRef}:\n\n${response.error}`);
      } else {
        alert(`⚠️ Order processing incomplete for ${caseRef}\n\nPlease try again or check the logs.`);
      }
    } catch (error) {
      console.error('Error downloading order:', error);
      alert(`❌ Error downloading order for ${caseRef}:\n\n${error.message}`);
    } finally {
      setProcessingOrders(prev => {
        const newSet = new Set(prev);
        newSet.delete(caseId);
        return newSet;
      });
    }
  };

  const handleAnalyzeOrder = async (caseId, caseRef) => {
    setProcessingOrders(prev => new Set(prev).add(caseId));
    try {
      const response = await authenticatedFetchJSON(`/auto-orders/analyze-case/${caseId}`, {
        method: 'POST'
      });

      console.log('Analysis response:', response);

      if (response.success) {
        const category = response.data?.order_category;
        const date = response.data?.order_date;
        const petitioners = response.data?.order_petitioners;
        const respondents = response.data?.order_respondents;
        
        let message = `✅ Order analyzed successfully for ${caseRef}!\n\n`;
        
        if (category) {
          message += `📊 Category: ${category}\n`;
        }
        if (date) {
          message += `📅 Order Date: ${date}\n`;
        }
        if (petitioners && petitioners.length > 0) {
          message += `\n👤 Petitioners: ${petitioners.length} found\n`;
        }
        if (respondents && respondents.length > 0) {
          message += `👥 Respondents: ${respondents.length} found\n`;
        }
        
        alert(message);
        
        // Refresh the data to show analysis results
        await fetchData();
      } else {
        alert(`❌ Failed to analyze order for ${caseRef}:\n\n${response.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error analyzing order:', error);
      alert(`❌ Error analyzing order for ${caseRef}:\n\n${error.message}`);
    } finally {
      setProcessingOrders(prev => {
        const newSet = new Set(prev);
        newSet.delete(caseId);
        return newSet;
      });
    }
  };

  const viewOrderDetails = (caseId) => {
    setSelectedCaseId(caseId);
    setShowOrderDrawer(true);
  };

  const frameworkComponents = {
    deleteButtonRenderer: DeleteButtonRenderer,
    orderStatusRenderer: OrderStatusRenderer,
    orderActionsRenderer: OrderActionsRenderer
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">🔍 Search & Order Management</h1>
        <p className="dashboard-subtitle">
          Search court cases, download orders, and analyze them all from one unified interface
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
                    disabled={isSearching}
                    style={{ 
                      flex: 1,
                      opacity: isSearching ? 0.7 : 1,
                      cursor: isSearching ? 'not-allowed' : 'pointer'
                    }}
                  >
                    {isSearching ? (
                      <>
                        <span className="loading" style={{ marginRight: '8px' }}></span>
                        Searching...
                      </>
                    ) : (
                      '🔍 Search Cases'
                    )}
                  </button>
                  <button 
                    className="btn-professional btn-secondary"
                    disabled={isSearching}
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
                      setSearchError('');
                    }}
                    style={{
                      opacity: isSearching ? 0.7 : 1,
                      cursor: isSearching ? 'not-allowed' : 'pointer'
                    }}
                  >
                    Clear
                  </button>
                </div>
                
                {/* Progress Bar */}
                {isSearching && (
                  <div style={{ marginTop: 'var(--spacing-md)' }}>
                    <div style={{
                      width: '100%',
                      height: '4px',
                      backgroundColor: 'var(--gray-200)',
                      borderRadius: '2px',
                      overflow: 'hidden'
                    }}>
                      <div style={{
                        width: '100%',
                        height: '100%',
                        background: 'linear-gradient(90deg, var(--primary-color) 0%, var(--primary-light) 100%)',
                        animation: 'progress-slide 2s ease-in-out infinite'
                      }}></div>
                    </div>
                    <p style={{ 
                      marginTop: '8px', 
                      fontSize: '0.875rem', 
                      color: 'var(--gray-600)', 
                      textAlign: 'center' 
                    }}>
                      Searching through case database... Please wait
                    </p>
                  </div>
                )}
                
                {/* Error Message */}
                {searchError && (
                  <div style={{
                    marginTop: 'var(--spacing-md)',
                    padding: 'var(--spacing-sm)',
                    backgroundColor: 'var(--error-bg)',
                    border: '1px solid var(--error-border)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--error-color)'
                  }}>
                    {searchError}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Applied Search Criteria Display */}
        {(appliedCriteria.startDate || appliedCriteria.endDate || appliedCriteria.advocateName || appliedCriteria.caseNumber || appliedCriteria.caseType || appliedCriteria.caseYear || appliedCriteria.caseStage) && (
          <div className="card-professional" style={{ marginBottom: 'var(--spacing-lg)', backgroundColor: 'var(--success-bg)' }}>
            <div className="card-header">
              <h3 className="section-title" style={{ color: 'var(--success-color)', fontSize: '1rem' }}>
                🎯 Applied Search Filters
              </h3>
            </div>
            <div className="card-body" style={{ padding: 'var(--spacing-md)' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-sm)' }}>
                {appliedCriteria.startDate && (
                  <span className="badge bg-primary">
                    Start Date: {appliedCriteria.startDate}
                  </span>
                )}
                {appliedCriteria.endDate && (
                  <span className="badge bg-primary">
                    End Date: {appliedCriteria.endDate}
                  </span>
                )}
                {appliedCriteria.advocateName && (
                  <span className="badge bg-primary">
                    Advocate: {appliedCriteria.advocateName}
                  </span>
                )}
                {appliedCriteria.caseNumber && (
                  <span className="badge bg-primary">
                    Case Number: {appliedCriteria.caseNumber}
                  </span>
                )}
                {appliedCriteria.caseType && (
                  <span className="badge bg-primary">
                    Case Type: {appliedCriteria.caseType}
                  </span>
                )}
                {appliedCriteria.caseYear && (
                  <span className="badge bg-primary">
                    Case Year: {appliedCriteria.caseYear}
                  </span>
                )}
                {appliedCriteria.caseStage && (
                  <span className="badge bg-primary">
                    Case Stage: {appliedCriteria.caseStage}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

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
                components={frameworkComponents}
                rowHeight={50}
                headerHeight={45}
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
