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
    caseStage: '',
    orderStatus: '',
    orderCategory: ''
  });
  const [appliedCriteria, setAppliedCriteria] = useState({
    startDate: '',
    endDate: '',
    advocateName: '',
    caseNumber: '',
    caseType: '',
    caseYear: '',
    caseStage: '',
    orderStatus: '',
    orderCategory: ''
  });
  const [searchOpen, setSearchOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [_selectedCaseId, setSelectedCaseId] = useState(null);
  const [_showOrderDrawer, setShowOrderDrawer] = useState(false);
  const [processingOrders, setProcessingOrders] = useState(new Set());
  const [selectedRows, setSelectedRows] = useState([]);
  const [gridApi, setGridApi] = useState(null);
  const [maxSequences, setMaxSequences] = useState(50); // Configurable max sequences for order download

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
      caseStage: '',
      orderStatus: '',
      orderCategory: ''
    };
    
    setSearchCriteria(initialCriteria);
    setAppliedCriteria(initialCriteria);
    fetchData(initialCriteria);
    // eslint-disable-next-line
  }, []);

  const fetchData = async (criteria = searchCriteria) => {
    if (!criteria.startDate && !criteria.endDate && !criteria.advocateName && !criteria.caseNumber && !criteria.caseType && !criteria.caseYear && !criteria.caseStage && !criteria.orderStatus && !criteria.orderCategory) {
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
          caseStage: criteria.caseStage,
          orderStatus: criteria.orderStatus,
          orderCategory: criteria.orderCategory
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

  const _deleteRow = (index) => {
    setEditedData((prev) => prev.filter((_, i) => i !== index));
  };

  // AG Grid column definitions
  const columnDefs = [
    {
      headerName: '',
      field: 'checkbox',
      checkboxSelection: true,
      headerCheckboxSelection: true,
      width: 50,
      pinned: 'left',
      lockPinned: true,
      suppressMenu: true,
      filter: false,
      sortable: false,
      editable: false,
      resizable: false
    },
    { 
      headerName: 'Board Date', 
      field: 'board_date', 
      sortable: true, 
      filter: 'agDateColumnFilter',
      editable: true,
      width: 150
    },
    { 
      headerName: 'Case Number', 
      field: 'case_number', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: false,
      width: 180,
      valueGetter: params => {
        const caseType = params.data?.case_type || '';
        const caseNo = params.data?.case_no || '';
        const caseYear = params.data?.case_year || '';
        return `${caseType}/${caseNo}/${caseYear}`;
      }
    },
    { 
      headerName: 'Petitioner', 
      field: 'petitioner_name', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 250,
      valueGetter: params => {
        // Only show data from order analysis
        return params.data?.order_petitioner || '-';
      }
    },
    { 
      headerName: 'Respondent', 
      field: 'respondent_name', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 250,
      valueGetter: params => {
        // Only show data from order analysis
        return params.data?.order_respondent || '-';
      }
    },
    { 
      headerName: 'AGP Name', 
      field: 'agp_name', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 250,
      valueGetter: params => {
        // Show all AGP names from board data and order data
        const agpNames = [];
        
        // Primary AGP from board
        if (params.data?.respondent_lawyer) {
          agpNames.push(params.data.respondent_lawyer);
        }
        
        // Additional AGPs from board (now an array)
        if (params.data?.additional_respondent_lawyers && Array.isArray(params.data.additional_respondent_lawyers)) {
          agpNames.push(...params.data.additional_respondent_lawyers);
        }
        
        // Government pleaders from order analysis (simplified structure)
        if (params.data?.order_cases && Array.isArray(params.data.order_cases) && params.data.order_cases.length > 0) {
          const firstCase = params.data.order_cases[0];
          if (firstCase.government_pleader && Array.isArray(firstCase.government_pleader)) {
            agpNames.push(...firstCase.government_pleader);
          }
        }
        
        return agpNames.filter(n => n).join(', ');
      }
    },
    { 
      headerName: 'Court Order', 
      field: 'court_order', 
      sortable: true, 
      filter: 'agTextColumnFilter',
      editable: true,
      width: 200,
      cellRenderer: 'courtOrderRenderer',
      cellStyle: params => {
        if (params.value === 'DISPOSAL') return { backgroundColor: '#d4edda', color: '#155724' };
        if (params.value === 'ADJOURNMENT') return { backgroundColor: '#fff3cd', color: '#856404' };
        if (params.value === 'HEARD & ADJRN') return { backgroundColor: '#cce7ff', color: '#004085' };
        return null;
      }
    },
    { 
      headerName: 'Order Status', 
      field: 'order_status', 
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
    }
  ];

  // Custom cell renderer for court order column
  const CourtOrderRenderer = (props) => {
    const { data, value } = props;
    const orderLink = data?.order_link;
    
    if (orderLink) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <a 
            href={orderLink} 
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: 'var(--primary-color)', 
              textDecoration: 'none',
              fontWeight: 500
            }}
            onClick={(e) => e.stopPropagation()}
          >
            📄 View Order
          </a>
          {value && <span style={{ fontSize: '0.75rem', color: 'var(--gray-600)' }}>({value})</span>}
        </div>
      );
    }
    
    return <span>{value || '-'}</span>;
  };

  // Custom cell renderer for order status badge
  const OrderStatusRenderer = (props) => {
    const { data } = props;
    const orderStatus = data?.order_status || 'not_linked';
    const caseId = data?.id;
    const caseRef = `${data?.case_type}/${data?.case_no}/${data?.case_year}`;
    const isProcessing = processingOrders.has(caseId);
    
    // Define status display properties
    const statusConfig = {
      'not_linked': { label: 'Not Linked', color: '#6c757d' },
      'order_linked': { label: 'Order Linked', color: '#17a2b8' },
      'analysed': { label: 'Analysed', color: '#28a745' },
      'order_failed': { label: 'Order Failed', color: '#dc3545' },
      'order_analysis_failed': { label: 'Analysis Failed', color: '#ffc107' }
    };
    
    const config = statusConfig[orderStatus] || statusConfig['not_linked'];
    
    // For order_linked status, show analyze button
    if (orderStatus === 'order_linked') {
      return (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="badge" style={{ backgroundColor: config.color, color: 'white' }}>{config.label}</span>
          <button 
            className="btn btn-sm btn-warning"
            onClick={() => handleAnalyzeOrder(caseId, caseRef)}
            disabled={isProcessing}
            style={{ fontSize: '0.75rem', padding: '2px 8px' }}
          >
            {isProcessing ? '...' : 'Analyze'}
          </button>
        </div>
      );
    }
    
    return <span className="badge" style={{ backgroundColor: config.color, color: 'white' }}>{config.label}</span>;
  };

  // Order management functions
  const _handleDownloadOrder = async (caseId, caseRef, caseData) => {
    setProcessingOrders(prev => new Set(prev).add(caseId));
    try {
      const response = await authenticatedFetchJSON(`/auto-orders/process-case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: caseId,
          case_ref: caseRef,
          board_date: caseData.board_date,
          max_sequences: maxSequences
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
        const cases = response.data?.order_cases;
        
        let message = `✅ Order analyzed successfully for ${caseRef}!\n\n`;
        
        if (category) {
          message += `📊 Category: ${category}\n`;
        }
        if (date) {
          message += `📅 Order Date: ${date}\n`;
        }
        if (cases && cases.length > 0) {
          message += `\n� Cases Found: ${cases.length}\n`;
          cases.forEach((c, idx) => {
            if (c.petitioner) {
              message += `  Case ${idx + 1} - Petitioner: ${c.petitioner}\n`;
            }
            if (c.respondent) {
              message += `  Case ${idx + 1} - Respondent: ${c.respondent}\n`;
            }
          });
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

  const _viewOrderDetails = (caseId) => {
    setSelectedCaseId(caseId);
    setShowOrderDrawer(true);
  };

  // Batch operations for selected rows
  const handleBatchDownload = async () => {
    if (selectedRows.length === 0) {
      alert('⚠️ Please select at least one row to download orders.');
      return;
    }

    const confirmMsg = `📥 Download orders for ${selectedRows.length} selected case(s)?\n\nThis may take some time.`;
    if (!window.confirm(confirmMsg)) return;

    let successCount = 0;
    let failCount = 0;

    for (const row of selectedRows) {
      const caseId = row.id;
      const caseRef = `${row.case_type}/${row.case_no}/${row.case_year}`;
      
      try {
        setProcessingOrders(prev => new Set(prev).add(caseId));
        
        const response = await authenticatedFetchJSON(`/auto-orders/process-case`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            case_id: caseId,
            case_ref: caseRef,
            board_date: row.board_date,
            max_sequences: maxSequences
          })
        });

        if (response.download_success) {
          successCount++;
        } else {
          failCount++;
        }
      } catch (error) {
        console.error(`Error downloading order for ${caseRef}:`, error);
        failCount++;
      } finally {
        setProcessingOrders(prev => {
          const newSet = new Set(prev);
          newSet.delete(caseId);
          return newSet;
        });
      }
    }

    alert(`✅ Batch download complete!\n\nSuccessful: ${successCount}\nFailed: ${failCount}`);
    await fetchData();
    
    // Clear selection
    if (gridApi) {
      gridApi.deselectAll();
    }
  };

  const handleBatchDelete = async () => {
    if (selectedRows.length === 0) {
      alert('⚠️ Please select at least one row to delete.');
      return;
    }

    const confirmMsg = `🗑️ Delete ${selectedRows.length} selected case(s)?\n\nThis action cannot be undone.`;
    if (!window.confirm(confirmMsg)) return;

    let successCount = 0;
    let failCount = 0;

    for (const row of selectedRows) {
      const caseId = row.id;
      const caseRef = `${row.case_type}/${row.case_no}/${row.case_year}`;
      
      try {
        await authenticatedFetchJSON(`/delete_case/${caseId}`, {
          method: 'DELETE'
        });
        successCount++;
      } catch (error) {
        console.error(`Error deleting case ${caseRef}:`, error);
        failCount++;
      }
    }

    alert(`✅ Batch delete complete!\n\nDeleted: ${successCount}\nFailed: ${failCount}`);
    await fetchData();
    
    // Clear selection
    if (gridApi) {
      gridApi.deselectAll();
    }
  };

  const frameworkComponents = {
    orderStatusRenderer: OrderStatusRenderer,
    courtOrderRenderer: CourtOrderRenderer
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
                <div className="form-group">
                  <label className="form-label">Order Status</label>
                  <select
                    className="form-control"
                    value={searchCriteria.orderStatus}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, orderStatus: e.target.value }))}
                  >
                    <option value="">All Cases</option>
                    <option value="not_linked">Not Linked</option>
                    <option value="order_linked">Order Linked (Not Analysed)</option>
                    <option value="analysed">Linked & Analysed</option>
                    <option value="order_failed">Order Failed</option>
                    <option value="order_analysis_failed">Analysis Failed</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Order Category</label>
                  <select
                    className="form-control"
                    value={searchCriteria.orderCategory}
                    onChange={e => setSearchCriteria(sc => ({ ...sc, orderCategory: e.target.value }))}
                  >
                    <option value="">All Categories</option>
                    <option value="ADJOURNED">Adjourned</option>
                    <option value="HEARD_AND_ADJOURNED">Heard & Adjourned</option>
                    <option value="DISPOSED_OFF">Disposed Off</option>
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
                        caseStage: '',
                        orderStatus: ''
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
        {(appliedCriteria.startDate || appliedCriteria.endDate || appliedCriteria.advocateName || appliedCriteria.caseNumber || appliedCriteria.caseType || appliedCriteria.caseYear || appliedCriteria.caseStage || appliedCriteria.orderStatus) && (
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
                {appliedCriteria.orderStatus && (
                  <span className="badge bg-primary">
                    Order Status: {
                      appliedCriteria.orderStatus === 'not_linked' ? 'Not Linked' :
                      appliedCriteria.orderStatus === 'order_linked' ? 'Order Linked (Not Analysed)' :
                      appliedCriteria.orderStatus === 'analysed' ? 'Linked & Analysed' :
                      appliedCriteria.orderStatus === 'order_failed' ? 'Order Failed' :
                      appliedCriteria.orderStatus === 'order_analysis_failed' ? 'Analysis Failed' :
                      appliedCriteria.orderStatus
                    }
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
          
          {/* Batch Operations Toolbar */}
          <div style={{ 
            padding: 'var(--spacing-md)',
            backgroundColor: 'var(--gray-50)',
            borderBottom: '1px solid var(--gray-200)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--spacing-md)',
            flexWrap: 'wrap'
          }}>
            <span style={{ 
              fontSize: '0.875rem', 
              color: 'var(--gray-700)',
              fontWeight: 500
            }}>
              {selectedRows.length > 0 ? `${selectedRows.length} row(s) selected` : 'Select rows for batch operations'}
            </span>
            <div style={{ display: 'flex', gap: 'var(--spacing-sm)', marginLeft: 'auto', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <label 
                  htmlFor="maxSequencesInput" 
                  style={{ 
                    fontSize: '0.875rem', 
                    color: 'var(--gray-700)',
                    whiteSpace: 'nowrap'
                  }}
                >
                  Max Sequences:
                </label>
                <input
                  id="maxSequencesInput"
                  type="number"
                  min="1"
                  max="100"
                  value={maxSequences}
                  onChange={(e) => {
                    const value = parseInt(e.target.value);
                    if (value >= 1 && value <= 100) {
                      setMaxSequences(value);
                    }
                  }}
                  style={{
                    width: '80px',
                    padding: '0.25rem 0.5rem',
                    fontSize: '0.875rem',
                    border: '1px solid var(--border-color)',
                    borderRadius: '4px',
                    textAlign: 'center'
                  }}
                  title="Number of sequence numbers to try when downloading orders (1-100)"
                />
              </div>
              <button 
                className="btn-professional btn-primary"
                onClick={handleBatchDownload}
                disabled={selectedRows.length === 0}
                style={{ 
                  fontSize: '0.875rem',
                  opacity: selectedRows.length === 0 ? 0.5 : 1,
                  cursor: selectedRows.length === 0 ? 'not-allowed' : 'pointer'
                }}
              >
                📥 Download Selected Orders
              </button>
              <button 
                className="btn-professional"
                onClick={handleBatchDelete}
                disabled={selectedRows.length === 0}
                style={{ 
                  fontSize: '0.875rem',
                  backgroundColor: 'var(--error-color)',
                  color: 'white',
                  opacity: selectedRows.length === 0 ? 0.5 : 1,
                  cursor: selectedRows.length === 0 ? 'not-allowed' : 'pointer'
                }}
              >
                🗑️ Delete Selected
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
                rowSelection="multiple"
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
                  domLayout: 'normal'
                }}
                onGridReady={(params) => {
                  setGridApi(params.api);
                }}
                onSelectionChanged={(params) => {
                  const selectedNodes = params.api.getSelectedRows();
                  setSelectedRows(selectedNodes);
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
