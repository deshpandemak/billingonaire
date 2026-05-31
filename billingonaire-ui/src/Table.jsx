import React, { useEffect, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { authenticatedFetchJSON, getApiUrl } from './lib/api';
import './styles/professional.css';
import CaseDetailModal from './components/CaseDetailModal';
import { getLifecycleConfig, getOrderStatusConfig } from './lib/lifecycleUtils';

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
  const [processingOrders, setProcessingOrders] = useState(new Set());
  const [selectedRows, setSelectedRows] = useState([]);
  const [gridApi, setGridApi] = useState(null);
  const [tableMessage, setTableMessage] = useState(null);
  const [showCaseModal, setShowCaseModal] = useState(false);
  const [selectedCaseRef, setSelectedCaseRef] = useState('');
  const [jobStatuses, setJobStatuses] = useState(new Map()); // caseId → {caseRef, status, label, variant}
  const pollTimers = useRef({});

  // Clean up all poll timers on unmount
  useEffect(() => {
    return () => Object.values(pollTimers.current).forEach(clearTimeout);
  }, []);

  useEffect(() => {
    // By default, show last 30 days — narrow enough for fast initial load
    const today = new Date();
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(today.getDate() - 30);

    const endDate = today.toISOString().split('T')[0];
    const startDate = thirtyDaysAgo.toISOString().split('T')[0];

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

  const asArray = (value) => {
    if (Array.isArray(value)) return value.filter(Boolean);
    if (value === null || value === undefined || value === '') return [];
    return [value];
  };

  const getLatestOrder = (row) => {
    const history = Array.isArray(row?.order_history) ? row.order_history : [];
    if (history.length === 0) return {};
    const latest = history[history.length - 1];
    return latest && typeof latest === 'object' ? latest : {};
  };

  const normalizeCaseRecord = (row) => {
    const latestOrder = getLatestOrder(row);
    return {
      ...row,
      order_link: row?.order_link || latestOrder.order_link || null,
      order_status: row?.order_status || latestOrder.order_status || 'not_linked',
      order_category: row?.order_category || latestOrder.order_category || null,
      order_date: row?.order_date || latestOrder.order_date || null,
      order_petitioner: row?.order_petitioner || row?.petitioner || latestOrder.petitioner || null,
      order_respondent: row?.order_respondent || row?.respondent || latestOrder.respondent || null,
      government_pleader: [
        ...asArray(row?.government_pleader),
        ...asArray(row?.assigned_government_pleaders),
        ...asArray(latestOrder.government_pleader)
      ]
    };
  };

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
      const normalizedResult = Array.isArray(result)
        ? result.map((row) => normalizeCaseRecord(row))
        : [];
      setData(normalizedResult);
      setEditedData(JSON.parse(JSON.stringify(normalizedResult)));
      if (gridApi) {
        gridApi.deselectAll();
      }
    } catch (e) {
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
      setTableMessage({ type: 'success', text: 'Changes saved successfully.' });
    } catch (e) {
      setTableMessage({ type: 'error', text: `Failed to save data: ${e.message}` });
    }
  };

  const cancelEdit = () => {
    setEditedData(JSON.parse(JSON.stringify(data)));
  };

  const addRow = () => {
    setEditedData((prev) => [...prev, {}]);
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
      headerName: 'Case',
      field: 'view_case',
      width: 80,
      minWidth: 80,
      pinned: 'left',
      sortable: false,
      filter: false,
      editable: false,
      resizable: false,
      cellRenderer: 'viewCaseRenderer'
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
      headerName: 'GP in Board',
      field: 'gp_in_board',
      sortable: true,
      filter: 'agTextColumnFilter',
      editable: false,
      width: 220,
      tooltipValueGetter: () => 'Government Pleader assigned on the daily board',
      valueGetter: params => {
        const lawyers = [];
        if (params.data?.respondent_lawyer) lawyers.push(params.data.respondent_lawyer);
        if (Array.isArray(params.data?.additional_respondent_lawyers)) {
          lawyers.push(...params.data.additional_respondent_lawyers);
        }
        return [...new Set(lawyers.filter(Boolean))].join(', ') || '-';
      }
    },
    {
      headerName: 'GP in Order',
      field: 'gp_in_order',
      sortable: true,
      filter: 'agTextColumnFilter',
      editable: false,
      width: 220,
      tooltipValueGetter: () => 'Government Pleader named in the downloaded court order',
      valueGetter: params => {
        const gps = [
          ...asArray(params.data?.government_pleader),
          ...asArray(params.data?.assigned_government_pleaders)
        ];
        return [...new Set(gps.filter(Boolean))].join(', ') || '-';
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
      headerName: 'Lifecycle',
      field: 'lifecycle_status',
      sortable: true,
      filter: 'agTextColumnFilter',
      editable: false,
      width: 160,
      cellRenderer: 'lifecycleStatusRenderer'
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

  // Cell renderer for lifecycle status chips
  const LifecycleStatusRenderer = (props) => {
    const status = props.data?.lifecycle_status;
    if (!status) return <span className="text-muted" style={{ fontSize: '0.75rem' }}>—</span>;
    const cfg = getLifecycleConfig(status);
    const variantColors = {
      secondary: '#6c757d', info: '#17a2b8', success: '#28a745',
      danger: '#dc3545', warning: '#fd7e14', primary: '#0d6efd',
    };
    const bg = variantColors[cfg.variant] || '#6c757d';
    const color = cfg.variant === 'warning' ? '#212529' : 'white';
    const tipText = cfg.tooltip + (cfg.next ? `\n→ ${cfg.next}` : '');
    return (
      <span
        className="badge"
        style={{ backgroundColor: bg, color, cursor: 'help', fontSize: '0.7rem' }}
        title={tipText}
      >
        {cfg.icon} {cfg.label}
      </span>
    );
  };

  // Cell renderer for the View Case button
  const ViewCaseRenderer = (props) => {
    const { data } = props;
    if (!data?.case_type && !data?.case_no) return null;
    const caseRef = `${data.case_type}/${data.case_no}/${data.case_year}`;
    return (
      <button
        className="btn btn-sm btn-outline-primary"
        onClick={() => { setSelectedCaseRef(caseRef); setShowCaseModal(true); }}
        style={{ fontSize: '0.7rem', padding: '2px 8px' }}
        title={`View full case history for ${caseRef}`}
      >
        View
      </button>
    );
  };

  // Custom cell renderer for court order column
  const CourtOrderRenderer = (props) => {
    const { data, value } = props;
    const orderLink = data?.order_link;
    const caseId = data?.id;
    const caseRef = `${data?.case_type}/${data?.case_no}/${data?.case_year}`;

    if (orderLink) {
      // Always proxy through the backend — the GCS bucket is private so direct
      // browser access to storage.googleapis.com returns 403. The proxy uses
      // Cloud Run ADC and triggers an automatic re-fetch when the link is stale.
      const href = getApiUrl(`/orders/pdf/${caseId}`);

      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--primary-color)', textDecoration: 'none', fontWeight: 500 }}
            onClick={(e) => e.stopPropagation()}
          >
            📄 View Order
          </a>
          <button
            title="Force re-fetch: clear order history and re-download from court (admin only)"
            onClick={(e) => { e.stopPropagation(); handleForceReset(caseId, caseRef); }}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--gray-500)', fontSize: '0.8rem', padding: '0 2px',
            }}
          >
            ↻
          </button>
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

    const cfg = getOrderStatusConfig(orderStatus);
    const variantColors = {
      secondary: '#6c757d', info: '#17a2b8', success: '#28a745',
      danger: '#dc3545', warning: '#fd7e14', primary: '#0d6efd',
    };
    const bgColor = variantColors[cfg.variant] || '#6c757d';
    const textColor = cfg.variant === 'warning' ? '#212529' : 'white';

    if (orderStatus === 'linked' || orderStatus === 'order_analysis_failed') {
      return (
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <span
            className="badge"
            style={{ backgroundColor: bgColor, color: textColor, cursor: 'help' }}
            title={cfg.tooltip}
          >
            {cfg.label}
          </span>
          <button
            className="btn btn-sm btn-warning"
            onClick={() => handleAnalyzeOrder(caseId, caseRef)}
            disabled={isProcessing}
            style={{ fontSize: '0.7rem', padding: '1px 6px' }}
            title="Run order analysis to extract case details"
          >
            {isProcessing ? '…' : 'Analyse'}
          </button>
        </div>
      );
    }

    return (
      <span
        className="badge"
        style={{ backgroundColor: bgColor, color: textColor, cursor: cfg.tooltip ? 'help' : 'default' }}
        title={cfg.tooltip}
      >
        {cfg.label}
      </span>
    );
  };

  // Order management functions
  const handleForceReset = async (caseId, caseRef) => {
    if (!window.confirm(
      `Force re-fetch for ${caseRef}?\n\nThis will clear all stored order links and re-download every order PDF from the court, uploading them to permanent storage. Previous links will be lost.`
    )) return;

    setProcessingOrders(prev => new Set(prev).add(caseId));
    setTableMessage(null);

    try {
      // 1. Reset all history for the case
      const resetResp = await authenticatedFetchJSON(`/cases/${encodeURIComponent(caseRef)}/reset`, {
        method: 'POST',
      });
      if (!resetResp.success) {
        throw new Error(resetResp.error || 'Reset failed');
      }

      // 2. Queue a fresh download for this board entry
      const procResp = await authenticatedFetchJSON(`/auto-orders/process-case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: caseId, case_ref: caseRef }),
      });

      if (procResp.download_success || (procResp.success && procResp.status === 'queued')) {
        setTableMessage({ type: 'success', text: `Re-fetch queued for ${caseRef} (${resetResp.board_entries_reset} entries reset).` });
        setJobStatuses(prev => new Map(prev).set(caseId, {
          caseRef, status: 'fetch_queued', label: jobLabel('fetch_queued'), variant: 'info',
        }));
        startPollingJob(caseId, caseRef);
      } else {
        setTableMessage({ type: 'success', text: `${caseRef} reset (${resetResp.board_entries_reset} entries). Download will run in background.` });
        await fetchData();
      }
    } catch (err) {
      setTableMessage({ type: 'error', text: `Force re-fetch failed for ${caseRef}: ${err.message}` });
      setProcessingOrders(prev => { const s = new Set(prev); s.delete(caseId); return s; });
    }
  };

  const handleAnalyzeOrder = async (caseId, caseRef) => {
    setProcessingOrders(prev => new Set(prev).add(caseId));
    try {
      const response = await authenticatedFetchJSON(`/auto-orders/analyze-case/${caseId}`, {
        method: 'POST'
      });

      if (response.success) {
        const category = response.data?.order_category;
        const date = response.data?.order_date;
        const detail = [category, date].filter(Boolean).join(' · ');
        setTableMessage({ type: 'success', text: `Order analysed for ${caseRef}${detail ? `: ${detail}` : ''}.` });
        await fetchData();
      } else {
        setTableMessage({ type: 'error', text: `Analysis failed for ${caseRef}: ${response.error || 'Unknown error'}` });
      }
    } catch (error) {
      setTableMessage({ type: 'error', text: `Error analysing order for ${caseRef}: ${error.message}` });
    } finally {
      setProcessingOrders(prev => {
        const newSet = new Set(prev);
        newSet.delete(caseId);
        return newSet;
      });
    }
  };

  const JOB_TERMINAL = new Set([
    'analysed',
    'fetch_not_due',
    'fetch_failed',
    'fetch_failed_retryable',
    'fetch_failed_terminal',
    'analysis_failed',
    'analysis_failed_retryable',
    'analysis_failed_terminal',
    'manual_review_required',
  ]);
  const JOB_SUCCESS  = new Set(['analysed']);

  const jobLabel = (status) => {
    const labels = {
      fetch_queued: 'Queued',
      fetch_in_progress: 'Downloading…',
      fetch_succeeded: 'Analysing…',
      fetch_not_due: 'Not due yet',
      analysis_queued: 'Analysing…',
      analysis_in_progress: 'Analysing…',
      analysed: 'Done ✓',
      fetch_failed: 'Download failed',
      fetch_failed_retryable: 'Download failed',
      fetch_failed_terminal: 'Download failed',
      analysis_failed: 'Analysis failed',
      analysis_failed_retryable: 'Analysis failed',
      analysis_failed_terminal: 'Analysis failed',
      manual_review_required: 'Needs review',
    };
    return labels[status] || status;
  };

  const jobVariant = (status) => {
    if (JOB_SUCCESS.has(status)) return 'success';
    if (status === 'fetch_not_due') return 'warning';
    if (['fetch_failed', 'fetch_failed_retryable', 'fetch_failed_terminal',
         'analysis_failed', 'analysis_failed_retryable', 'analysis_failed_terminal'].includes(status)) return 'error';
    if (status === 'manual_review_required') return 'warning';
    return 'info';
  };

  const startPollingJob = (caseId, caseRef) => {
    // Stop any existing timer for this case
    if (pollTimers.current[caseId]) clearTimeout(pollTimers.current[caseId]);

    const poll = async () => {
      try {
        const res = await authenticatedFetchJSON(`/auto-orders/job-status/${caseId}`);
        const status = res.status || 'unknown';

        // Always log the full response so failures are visible in DevTools console
        console.log(`[job-status] ${caseRef} (${caseId}):`, res);

        const errorReason = res.error_reason || res.last_event?.reason || null;
        const baseLabel = jobLabel(status);
        const displayLabel = errorReason && JOB_TERMINAL.has(status) && status !== 'analysed'
          ? `${baseLabel}: ${errorReason}`
          : baseLabel;

        setJobStatuses(prev => new Map(prev).set(caseId, {
          caseRef,
          status,
          label: displayLabel,
          errorReason,
          variant: jobVariant(status),
        }));

        if (!JOB_TERMINAL.has(status)) {
          pollTimers.current[caseId] = setTimeout(poll, 3000);
        } else {
          delete pollTimers.current[caseId];
          setProcessingOrders(prev => { const s = new Set(prev); s.delete(caseId); return s; });
          // Refresh row data once the last job finishes
          setJobStatuses(prev => {
            const allDone = [...prev.values()].every(j => JOB_TERMINAL.has(j.status));
            if (allDone) fetchData();
            return prev;
          });
        }
      } catch (err) {
        console.warn(`[job-status] poll error for ${caseRef}:`, err);
        // transient error — retry after a longer wait
        pollTimers.current[caseId] = setTimeout(poll, 6000);
      }
    };

    poll();
  };

  // Batch operations for selected rows
  const handleBatchDownload = async () => {
    if (selectedRows.length === 0) {
      alert('⚠️ Please select at least one row to download orders.');
      return;
    }

    // Clear previous job statuses
    setJobStatuses(new Map());
    setTableMessage(null);

    let queuedCount = 0;
    let failCount = 0;

    for (const row of selectedRows) {
      const caseId = row.id;
      const caseRef = `${row.case_type}/${row.case_no}/${row.case_year}`;

      // Show as queued immediately in the status panel
      setJobStatuses(prev => new Map(prev).set(caseId, {
        caseRef,
        status: 'submitting',
        label: 'Submitting…',
        variant: 'info',
      }));
      setProcessingOrders(prev => new Set(prev).add(caseId));

      try {
        const response = await authenticatedFetchJSON(`/auto-orders/process-case`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            case_id: caseId,
            case_ref: caseRef,
            board_date: row.board_date,
          })
        });

        if (response.download_success || (response.success && response.status === 'queued')) {
          queuedCount++;
          setJobStatuses(prev => new Map(prev).set(caseId, {
            caseRef, status: 'fetch_queued', label: jobLabel('fetch_queued'), variant: 'info',
          }));
          startPollingJob(caseId, caseRef);
        } else {
          failCount++;
          setJobStatuses(prev => new Map(prev).set(caseId, {
            caseRef, status: 'fetch_failed', label: 'Queue failed', variant: 'error',
          }));
          setProcessingOrders(prev => { const s = new Set(prev); s.delete(caseId); return s; });
        }
      } catch {
        failCount++;
        setJobStatuses(prev => new Map(prev).set(caseId, {
          caseRef, status: 'fetch_failed', label: 'Queue failed', variant: 'error',
        }));
        setProcessingOrders(prev => { const s = new Set(prev); s.delete(caseId); return s; });
      }
    }

    if (failCount > 0 && queuedCount === 0) {
      setTableMessage({ type: 'error', text: `Failed to queue ${failCount} case(s).` });
    }

    // Clear grid selection
    if (gridApi) gridApi.deselectAll();
  };

  const frameworkComponents = {
    orderStatusRenderer: OrderStatusRenderer,
    courtOrderRenderer: CourtOrderRenderer,
    viewCaseRenderer: ViewCaseRenderer,
    lifecycleStatusRenderer: LifecycleStatusRenderer
  };

  return (
    <>
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
                    <option value="linked">Order Linked (Not Analysed)</option>
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
                      const today = new Date();
                      const thirtyDaysAgo = new Date();
                      thirtyDaysAgo.setDate(today.getDate() - 30);
                      const defaults = {
                        startDate: thirtyDaysAgo.toISOString().split('T')[0],
                        endDate: today.toISOString().split('T')[0],
                        advocateName: '',
                        caseNumber: '',
                        caseType: '',
                        caseYear: '',
                        caseStage: '',
                        orderStatus: '',
                        orderCategory: ''
                      };
                      setSearchCriteria(defaults);
                      setSearchError('');
                      fetchData(defaults);
                    }}
                    style={{
                      opacity: isSearching ? 0.7 : 1,
                      cursor: isSearching ? 'not-allowed' : 'pointer'
                    }}
                  >
                    Clear Filters
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

        {/* Future-date board banner */}
        {appliedCriteria.startDate && appliedCriteria.startDate > new Date().toISOString().split('T')[0] && (
          <div
            style={{
              marginBottom: 'var(--spacing-md)',
              padding: '0.6rem 1rem',
              backgroundColor: '#fff3cd',
              border: '1px solid #ffc107',
              borderRadius: 'var(--radius-md)',
              color: '#856404',
              fontSize: '0.875rem'
            }}
          >
            📅 The selected date range is in the future. Orders will be fetched automatically after each board date passes.
          </div>
        )}

        {/* Dismissible applied filter chips */}
        {Object.values(appliedCriteria).some(Boolean) && (
          <div style={{
            marginBottom: 'var(--spacing-lg)',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '0.4rem'
          }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--gray-600)', marginRight: '0.25rem' }}>
              Filters:
            </span>
            {[
              { key: 'startDate',    label: 'From',          value: appliedCriteria.startDate },
              { key: 'endDate',      label: 'To',            value: appliedCriteria.endDate },
              { key: 'advocateName', label: 'Advocate',      value: appliedCriteria.advocateName },
              { key: 'caseNumber',   label: 'Case No',       value: appliedCriteria.caseNumber },
              { key: 'caseType',     label: 'Type',          value: appliedCriteria.caseType },
              { key: 'caseYear',     label: 'Year',          value: appliedCriteria.caseYear },
              { key: 'caseStage',    label: 'Stage',         value: appliedCriteria.caseStage },
              { key: 'orderStatus',  label: 'Order Status',  value: appliedCriteria.orderStatus },
              { key: 'orderCategory',label: 'Category',      value: appliedCriteria.orderCategory },
            ].filter(f => f.value).map(f => (
              <span
                key={f.key}
                className="badge bg-primary d-inline-flex align-items-center gap-1"
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem' }}
              >
                {f.label}: {f.value}
                <button
                  type="button"
                  aria-label={`Remove ${f.label} filter`}
                  onClick={() => {
                    const updated = { ...appliedCriteria, [f.key]: '' };
                    setAppliedCriteria(updated);
                    setSearchCriteria(updated);
                    fetchData(updated);
                  }}
                  style={{
                    background: 'none', border: 'none', color: 'white',
                    cursor: 'pointer', padding: '0 0 0 2px', lineHeight: 1, fontSize: '0.85rem'
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Inline feedback message */}
        {tableMessage && (
          <div
            className={tableMessage.type === 'success' ? 'alert-success' : tableMessage.type === 'info' ? 'alert' : 'alert-error'}
            style={{
              marginBottom: 'var(--spacing-md)',
              padding: 'var(--spacing-sm) var(--spacing-md)',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              backgroundColor: tableMessage.type === 'info' ? '#e0f0ff' : undefined,
              border: tableMessage.type === 'info' ? '1px solid #90caf9' : undefined,
              color: tableMessage.type === 'info' ? '#1565c0' : undefined,
            }}
          >
            <span>{tableMessage.text}</span>
            <button
              onClick={() => setTableMessage(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem', marginLeft: '1rem' }}
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )}

        {/* Download job status panel */}
        {jobStatuses.size > 0 && (
          <div style={{
            marginBottom: 'var(--spacing-md)',
            border: '1px solid var(--gray-200)',
            borderRadius: 'var(--radius-md)',
            overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: 'var(--spacing-sm) var(--spacing-md)',
              backgroundColor: 'var(--gray-50)',
              borderBottom: '1px solid var(--gray-200)',
            }}>
              <strong style={{ fontSize: '0.875rem' }}>Download Status</strong>
              {[...jobStatuses.values()].every(j => JOB_TERMINAL.has(j.status)) && (
                <button
                  onClick={() => setJobStatuses(new Map())}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--gray-500)' }}
                >
                  Dismiss
                </button>
              )}
            </div>
            <div style={{ maxHeight: 200, overflowY: 'auto' }}>
              {[...jobStatuses.entries()].map(([caseId, job]) => {
                const bg = job.variant === 'success' ? '#f0fdf4' : job.variant === 'error' ? '#fef2f2' : job.variant === 'warning' ? '#fffbeb' : '#f0f9ff';
                const color = job.variant === 'success' ? '#166534' : job.variant === 'error' ? '#991b1b' : job.variant === 'warning' ? '#92400e' : '#1e40af';
                return (
                  <div key={caseId} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                    padding: '6px var(--spacing-md)',
                    borderBottom: '1px solid var(--gray-100)',
                    backgroundColor: bg,
                    fontSize: '0.82rem',
                    gap: '8px',
                  }}>
                    <span style={{ fontFamily: 'monospace', color: 'var(--gray-700)', flexShrink: 0 }}>{job.caseRef}</span>
                    <span style={{ fontWeight: 600, color, textAlign: 'right' }}
                          title={job.errorReason || undefined}>
                      {job.label}
                    </span>
                  </div>
                );
              })}
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
                noRowsOverlayComponent={() => (
                  <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--gray-600)' }}>
                    <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📭</div>
                    <strong>No cases found for the selected filters.</strong>
                    <p style={{ margin: '0.5rem 0 0', fontSize: '0.875rem' }}>
                      Try widening the date range, removing a filter, or uploading today&apos;s board PDF.
                    </p>
                  </div>
                )}
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

    <CaseDetailModal
      caseRef={selectedCaseRef}
      show={showCaseModal}
      onHide={() => setShowCaseModal(false)}
    />
    </>
  );
};

export default Table;
