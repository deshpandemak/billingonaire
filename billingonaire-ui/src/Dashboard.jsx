import React, { useEffect, useState, useCallback } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import { useToast } from './components/ToastProvider';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from 'chart.js';
import { Bar, Doughnut } from 'react-chartjs-2';
import {
  ComposedChart,
  Bar as RechartsBar,
  Line as RechartsLine,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend as RechartsLegend,
  ResponsiveContainer,
} from 'recharts';
import './styles/professional.css';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

const Dashboard = () => {
  const { addToast } = useToast();
  const currentDate = new Date();
  const currentYear = currentDate.getFullYear();
  const currentQuarter = Math.floor(currentDate.getMonth() / 3) + 1;

  const [orderStats, setOrderStats] = useState(null);
  const [agpStats, setAgpStats] = useState([]);
  const [monthlyAvg, setMonthlyAvg] = useState([]);
  const [year, setYear] = useState(new Date().getFullYear().toString());
  const [agpName, setAgpName] = useState('');
  const [agpLoading, setAgpLoading] = useState(true);
  const [monthlyLoading, setMonthlyLoading] = useState(true);
  const [agpError, setAgpError] = useState('');
  const [monthlyError, setMonthlyError] = useState('');
  const [agpCurrentPage, setAgpCurrentPage] = useState(0);
  const [monthlyCurrentPage, setMonthlyCurrentPage] = useState(0);
  const ITEMS_PER_PAGE = 20;

  const [mattersByDateRange, setMattersByDateRange] = useState({ data: [], summary: {} });
  const [analyticsLoading, setAnalyticsLoading] = useState({
    matters: true
  });
  const [analyticsError, setAnalyticsError] = useState({
    matters: ''
  });
  const [dateRange, setDateRange] = useState({
    start: '',
    end: ''
  });

  const [boardSummary, setBoardSummary] = useState({ rows: [], summary: {}, filters: {} });
  const [boardSummaryLoading, setBoardSummaryLoading] = useState(true);
  const [boardSummaryError, setBoardSummaryError] = useState('');
  const [boardCurrentPage, setBoardCurrentPage] = useState(0);

  const [boardFilterType, setBoardFilterType] = useState('quarter');
  const [boardYear, setBoardYear] = useState(currentYear.toString());
  const [boardQuarter, setBoardQuarter] = useState(currentQuarter.toString());
  const [boardDateRange, setBoardDateRange] = useState({ start: '', end: '' });
  const [boardLimit, setBoardLimit] = useState(180);

  const [selectedBoardDates, setSelectedBoardDates] = useState([]);
  const [selectedDistribution, setSelectedDistribution] = useState({
    distribution: [],
    total_cases: 0,
    selected_dates: [],
    board_breakdown: []
  });
  const [selectedDistributionLoading, setSelectedDistributionLoading] = useState(false);
  const [selectedDistributionError, setSelectedDistributionError] = useState('');
  const [selectedDateCases, setSelectedDateCases] = useState([]);
  const [selectedDateCasesLoading, setSelectedDateCasesLoading] = useState(false);
  const [selectedDateCasesError, setSelectedDateCasesError] = useState('');
  const [selectedCaseRefs, setSelectedCaseRefs] = useState([]);

  const [queueStatus, setQueueStatus] = useState({
    fetch_queue_size: 0,
    analysis_queue_size: 0,
    fetch_processing_active: false,
    analysis_processing_active: false,
    status: 'inactive',
    message: ''
  });
  const [queueStatusLoading, setQueueStatusLoading] = useState(true);
  const [queueStatusError, setQueueStatusError] = useState('');
  const [jobActionLoading, setJobActionLoading] = useState('');
  const [jobActionMessage, setJobActionMessage] = useState('');
  const [jobActionError, setJobActionError] = useState('');

  const fetchAgpStats = useCallback(async () => {
    setAgpLoading(true);
    setAgpError('');
    setAgpCurrentPage(0); // Reset pagination on new data
    let url = `/dashboard/agp-stats`;
    if (agpName) url += `?agp_name=${encodeURIComponent(agpName)}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setAgpStats(data);
    } catch (e) {

      setAgpError('Failed to load AGP statistics');
      setAgpStats([]);
    } finally {
      setAgpLoading(false);
    }
  }, [agpName]);

  // Fetch monthly average matters per AGP with independent loading
  const fetchMonthlyAvg = useCallback(async () => {
    setMonthlyLoading(true);
    setMonthlyError('');
    setMonthlyCurrentPage(0); // Reset pagination on new data
    let url = `/dashboard/monthly-avg`;
    if (year) url += `?year=${year}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setMonthlyAvg(data);
    } catch (e) {

      setMonthlyError('Failed to load monthly averages');
      setMonthlyAvg([]);
    } finally {
      setMonthlyLoading(false);
    }
  }, [year]);

  const fetchMattersByDateRange = useCallback(async () => {
    setAnalyticsLoading(prev => ({ ...prev, matters: true }));
    setAnalyticsError(prev => ({ ...prev, matters: '' }));
    let url = `/dashboard/matters-by-date-range`;
    const params = [];
    if (dateRange.start) params.push(`start_date=${dateRange.start}`);
    if (dateRange.end) params.push(`end_date=${dateRange.end}`);
    if (params.length) url += `?${params.join('&')}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setMattersByDateRange(data);
    } catch (e) {

      setAnalyticsError(prev => ({ ...prev, matters: 'Failed to load matters data' }));
      setMattersByDateRange({ data: [], summary: {} });
    } finally {
      setAnalyticsLoading(prev => ({ ...prev, matters: false }));
    }
  }, [dateRange.start, dateRange.end]);

  const fetchBoardDateSummary = useCallback(async () => {
    setBoardSummaryLoading(true);
    setBoardSummaryError('');

    const params = new URLSearchParams();
    params.set('limit', String(boardLimit || 180));

    if (boardFilterType === 'quarter') {
      if (boardYear) {
        params.set('year', boardYear);
      }
      if (boardQuarter) {
        params.set('quarter', boardQuarter);
      }
    } else if (boardFilterType === 'year') {
      if (boardYear) {
        params.set('year', boardYear);
      }
    } else {
      if (boardDateRange.start) {
        params.set('start_date', boardDateRange.start);
      }
      if (boardDateRange.end) {
        params.set('end_date', boardDateRange.end);
      }
    }

    const url = `/dashboard/board-date-summary?${params.toString()}`;

    try {
      const data = await authenticatedFetchJSON(url);
      setBoardSummary(data);
      setBoardCurrentPage(0);

      const dateSet = new Set((data.rows || []).map(row => row.board_date));
      setSelectedBoardDates(prev => prev.filter(date => dateSet.has(date)));
    } catch (e) {

      setBoardSummaryError('Failed to load board date summary');
      setBoardSummary({ rows: [], summary: {}, filters: {} });
      setSelectedBoardDates([]);
    } finally {
      setBoardSummaryLoading(false);
    }
  }, [boardDateRange.end, boardDateRange.start, boardFilterType, boardLimit, boardQuarter, boardYear]);

  const fetchSelectedBoardDistribution = useCallback(async () => {
    if (!selectedBoardDates.length) {
      setSelectedDistributionError('Select at least one board date first');
      return;
    }

    setSelectedDistributionLoading(true);
    setSelectedDistributionError('');

    const params = new URLSearchParams();
    selectedBoardDates.forEach(date => params.append('board_dates', date));

    try {
      const data = await authenticatedFetchJSON(`/dashboard/board-date-agp-distribution?${params.toString()}`);
      setSelectedDistribution(data);
    } catch (e) {

      setSelectedDistributionError('Failed to load AGP distribution for selected board dates');
      setSelectedDistribution({ distribution: [], total_cases: 0, selected_dates: [], board_breakdown: [] });
    } finally {
      setSelectedDistributionLoading(false);
    }
  }, [selectedBoardDates]);

  const fetchSelectedDateCases = useCallback(async () => {
    if (!selectedBoardDates.length) {
      setSelectedDateCases([]);
      setSelectedCaseRefs([]);
      return;
    }

    setSelectedDateCasesLoading(true);
    setSelectedDateCasesError('');

    const params = new URLSearchParams();
    selectedBoardDates.forEach(date => params.append('board_dates', date));
    params.set('limit', '2000');

    try {
      const data = await authenticatedFetchJSON(`/dashboard/board-date-cases?${params.toString()}`);
      const cases = data.cases || [];
      setSelectedDateCases(cases);

      const caseRefSet = new Set(cases.map(item => item.case_ref));
      setSelectedCaseRefs(prev => prev.filter(ref => caseRefSet.has(ref)));
    } catch (e) {

      setSelectedDateCasesError('Failed to load case list for selected dates');
      setSelectedDateCases([]);
      setSelectedCaseRefs([]);
    } finally {
      setSelectedDateCasesLoading(false);
    }
  }, [selectedBoardDates]);

  const fetchQueueStatus = useCallback(async () => {
    setQueueStatusLoading(true);
    setQueueStatusError('');
    try {
      const data = await authenticatedFetchJSON('/queue/status');
      setQueueStatus(data || {});
    } catch (e) {

      setQueueStatusError('Unable to fetch queue status right now');
    } finally {
      setQueueStatusLoading(false);
    }
  }, []);

  const queueFetchJobs = useCallback(async () => {
    setJobActionLoading('fetch');
    setJobActionError('');
    setJobActionMessage('');

    try {
      const filters = {};

      if (boardFilterType === 'quarter' || boardFilterType === 'year') {
        if (boardYear) {
          filters.case_year = boardYear;
        }
      }

      if (boardFilterType === 'date_range') {
        if (boardDateRange.start) {
          filters.date_from = boardDateRange.start;
        }
        if (boardDateRange.end) {
          filters.date_to = boardDateRange.end;
        }
      }

      const result = await authenticatedFetchJSON('/jobs/fetch-orders', {
        method: 'POST',
        body: JSON.stringify({
          filters,
          board_dates: selectedBoardDates,
          case_refs: selectedCaseRefs,
          limit: Math.min(Number(boardLimit) || 100, 300),
          max_sequences: 50
        })
      });

      setJobActionMessage(
        `Queued fetch jobs: ${result.queued || 0}, skipped not due: ${result.skipped_not_due || 0}${selectedCaseRefs.length ? `, selected cases: ${selectedCaseRefs.length}` : selectedBoardDates.length ? `, selected dates: ${selectedBoardDates.length}` : ''}`
      );
      await fetchQueueStatus();
    } catch (e) {

      setJobActionError('Failed to queue fetch jobs. Admin access may be required.');
    } finally {
      setJobActionLoading('');
    }
  }, [boardDateRange.end, boardDateRange.start, boardFilterType, boardLimit, boardYear, fetchQueueStatus, selectedBoardDates, selectedCaseRefs]);

  const queueAnalyzeJobs = useCallback(async () => {
    setJobActionLoading('analysis');
    setJobActionError('');
    setJobActionMessage('');

    try {
      const result = await authenticatedFetchJSON('/jobs/analyze-orders', {
        method: 'POST',
        body: JSON.stringify({
          board_dates: selectedBoardDates,
          case_refs: selectedCaseRefs,
          limit: Math.min(Number(boardLimit) || 100, 300)
        })
      });

      setJobActionMessage(
        `Queued analysis jobs: ${result.queued || 0}, skipped: ${result.skipped || 0}${selectedCaseRefs.length ? `, selected cases: ${selectedCaseRefs.length}` : selectedBoardDates.length ? `, selected dates: ${selectedBoardDates.length}` : ''}`
      );
      await fetchQueueStatus();
    } catch (e) {

      setJobActionError('Failed to queue analysis jobs. Admin access may be required.');
    } finally {
      setJobActionLoading('');
    }
  }, [boardLimit, fetchQueueStatus, selectedBoardDates, selectedCaseRefs]);

  const restartWorkers = useCallback(async () => {
    setJobActionLoading('restart');
    setJobActionError('');
    setJobActionMessage('');

    try {
      const result = await authenticatedFetchJSON('/queue/restart', {
        method: 'POST',
        body: JSON.stringify({})
      });
      setJobActionMessage(result.message || 'Background workers restarted');
      await fetchQueueStatus();
    } catch (e) {

      setJobActionError('Failed to restart workers. Admin access may be required.');
    } finally {
      setJobActionLoading('');
    }
  }, [fetchQueueStatus]);

  useEffect(() => {
    fetchAgpStats();
  }, [fetchAgpStats]);

  useEffect(() => {
    fetchMonthlyAvg();
  }, [fetchMonthlyAvg]);

  // Fetch new analytics data on component mount and when date range changes
  useEffect(() => {
    fetchMattersByDateRange();
  }, [fetchMattersByDateRange]);

  useEffect(() => {
    fetchBoardDateSummary();
  }, [fetchBoardDateSummary]);

  useEffect(() => {
    fetchSelectedDateCases();
  }, [fetchSelectedDateCases]);

  useEffect(() => {
    fetchQueueStatus();
    const interval = window.setInterval(() => {
      fetchQueueStatus();
    }, 15000);
    return () => window.clearInterval(interval);
  }, [fetchQueueStatus]);

  // Fetch order stats for the stuck-orders alert card
  useEffect(() => {
    authenticatedFetchJSON('/orders/overview-stats')
      .then(data => setOrderStats(data))
      .catch(() => { /* non-critical */ });
  }, []);

  // Helper function for pagination
  const getPaginatedData = (data, currentPage) => {
    const startIndex = currentPage * ITEMS_PER_PAGE;
    const endIndex = startIndex + ITEMS_PER_PAGE;
    return data.slice(startIndex, endIndex);
  };

  const getTotalPages = (dataLength) => {
    return Math.ceil(dataLength / ITEMS_PER_PAGE);
  };

  const toggleBoardDateSelection = (boardDate) => {
    setSelectedBoardDates((prev) => {
      if (prev.includes(boardDate)) {
        return prev.filter(d => d !== boardDate);
      }
      return [...prev, boardDate];
    });
  };

  const selectAllBoardDatesOnPage = () => {
    const pageRows = getPaginatedData(boardSummary.rows || [], boardCurrentPage);
    const pageDates = pageRows.map(row => row.board_date);
    setSelectedBoardDates((prev) => {
      const merged = new Set(prev);
      pageDates.forEach(date => merged.add(date));
      return Array.from(merged);
    });
  };

  const clearBoardDateSelection = () => {
    setSelectedBoardDates([]);
    setSelectedDistribution({ distribution: [], total_cases: 0, selected_dates: [], board_breakdown: [] });
    setSelectedDistributionError('');
    setSelectedDateCases([]);
    setSelectedCaseRefs([]);
    setSelectedDateCasesError('');
  };

  const toggleCaseSelection = (caseRef) => {
    setSelectedCaseRefs((prev) => {
      if (prev.includes(caseRef)) {
        return prev.filter(ref => ref !== caseRef);
      }
      return [...prev, caseRef];
    });
  };

  const selectAllCasesForSelectedDates = () => {
    setSelectedCaseRefs((selectedDateCases || []).map(item => item.case_ref));
  };

  const clearCaseSelection = () => {
    setSelectedCaseRefs([]);
  };

  // Chart configurations
  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom',
      },
      title: {
        display: false,
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        grid: {
          color: 'rgba(0, 0, 0, 0.1)',
        },
      },
      x: {
        grid: {
          display: false,
        },
      },
    },
  };

  // AGP Stats Chart Data
  const agpChartData = {
    labels: agpStats.slice(0, 10).map(item => item.agp_name), // Top 10 for readability
    datasets: [
      {
        label: 'Total Matters',
        data: agpStats.slice(0, 10).map(item => item.matters),
        backgroundColor: 'rgba(59, 130, 246, 0.6)',
        borderColor: 'rgba(59, 130, 246, 1)',
        borderWidth: 1,
      },
    ],
  };

  // Monthly Average Chart Data
  const monthlyChartData = {
    labels: monthlyAvg.slice(0, 10).map(item => item.agp_name), // Top 10 for readability
    datasets: [
      {
        label: 'Monthly Average',
        data: monthlyAvg.slice(0, 10).map(item => parseFloat(item.monthly_avg)),
        backgroundColor: 'rgba(16, 185, 129, 0.6)',
        borderColor: 'rgba(16, 185, 129, 1)',
        borderWidth: 1,
      },
    ],
  };

  // Doughnut chart for AGP distribution
  const agpDoughnutData = {
    labels: agpStats.slice(0, 8).map(item => item.agp_name), // Top 8 for doughnut
    datasets: [
      {
        data: agpStats.slice(0, 8).map(item => item.matters),
        backgroundColor: [
          'rgba(59, 130, 246, 0.8)',
          'rgba(16, 185, 129, 0.8)',
          'rgba(245, 158, 11, 0.8)',
          'rgba(239, 68, 68, 0.8)',
          'rgba(139, 92, 246, 0.8)',
          'rgba(236, 72, 153, 0.8)',
          'rgba(14, 165, 233, 0.8)',
          'rgba(34, 197, 94, 0.8)',
        ],
        borderWidth: 2,
        borderColor: '#fff',
      },
    ],
  };

  const selectedDistributionChartData = {
    labels: (selectedDistribution.distribution || []).slice(0, 12).map(item => item.agp_name),
    datasets: [
      {
        label: 'Assigned Matters',
        data: (selectedDistribution.distribution || []).slice(0, 12).map(item => item.matters),
        backgroundColor: 'rgba(37, 99, 235, 0.75)',
        borderColor: 'rgba(29, 78, 216, 1)',
        borderWidth: 1,
      },
    ],
  };


  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Legal Practice Dashboard</h1>
        <p className="dashboard-subtitle">
          Monitor your court matters, AGP statistics, and practice performance
        </p>
      </div>

      {/* Stuck Orders Alert */}
      {orderStats && (() => {
        const lc = orderStats.lifecycle_counts || orderStats.status_counts || {};
        const fetchPending = (lc.fetch_queued || 0) + (lc.fetch_in_progress || 0);
        const analysisPending = (lc.analysis_queued || 0) + (lc.analysis_in_progress || 0);
        const fetchFailed = lc.fetch_failed || 0;
        const analysisFailed = lc.order_analysis_failed || 0;
        const needsReview = lc.manual_review_required || 0;
        const workersStalled = !queueStatusLoading
          && queueStatus.fetch_queue_size > 0
          && !queueStatus.fetch_processing_active;

        const hasAlert = workersStalled || fetchFailed > 0 || analysisFailed > 0 || needsReview > 0;
        if (!hasAlert && fetchPending === 0 && analysisPending === 0) return null;

        return (
          <div className="dashboard-section">
            <div
              style={{
                border: `1px solid ${workersStalled || fetchFailed > 0 ? 'var(--error-color)' : 'var(--warning-color, #f59e0b)'}`,
                borderRadius: 'var(--radius-md)',
                padding: '1rem 1.25rem',
                backgroundColor: workersStalled || fetchFailed > 0 ? 'rgba(239,68,68,0.05)' : 'rgba(245,158,11,0.07)',
              }}
            >
              <div className="d-flex flex-wrap gap-4 align-items-center justify-content-between">
                <div>
                  <strong style={{ fontSize: '0.95rem' }}>
                    {workersStalled ? 'Workers are off — orders stuck in queue' : 'Pipeline Status'}
                  </strong>
                  {workersStalled && (
                    <span
                      style={{ marginLeft: '0.5rem', fontSize: '0.8rem', color: 'var(--error-color)' }}
                    >
                      {queueStatus.fetch_queue_size} item{queueStatus.fetch_queue_size !== 1 ? 's' : ''} waiting, fetch workers inactive
                    </span>
                  )}
                </div>
                <div className="d-flex flex-wrap gap-3" style={{ fontSize: '0.85rem' }}>
                  {fetchPending > 0 && (
                    <span>
                      <span className="badge bg-primary me-1">{fetchPending}</span>
                      Fetch pending
                    </span>
                  )}
                  {analysisPending > 0 && (
                    <span>
                      <span className="badge bg-info me-1">{analysisPending}</span>
                      Analysis pending
                    </span>
                  )}
                  {fetchFailed > 0 && (
                    <span>
                      <span className="badge bg-danger me-1">{fetchFailed}</span>
                      Download failed
                    </span>
                  )}
                  {analysisFailed > 0 && (
                    <span>
                      <span className="badge bg-warning text-dark me-1">{analysisFailed}</span>
                      Analysis failed
                    </span>
                  )}
                  {needsReview > 0 && (
                    <span>
                      <span className="badge bg-warning text-dark me-1">{needsReview}</span>
                      Needs review
                    </span>
                  )}
                </div>
                {workersStalled && (
                  <button
                    className="btn-professional btn-primary"
                    style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem' }}
                    onClick={restartWorkers}
                    disabled={jobActionLoading === 'restart'}
                  >
                    {jobActionLoading === 'restart' ? 'Restarting…' : 'Restart Workers'}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">Queue Operations and Job Controls</h2>
          </div>
          <div className="card-body">
            {queueStatusLoading ? (
              <div className="text-center p-3">
                <div className="loading-text">
                  <span className="loading"></span>
                  Refreshing queue status...
                </div>
              </div>
            ) : queueStatusError ? (
              <div className="text-center p-3">
                <p style={{ color: 'var(--error-color)' }}>{queueStatusError}</p>
                <button className="btn-professional btn-primary" onClick={fetchQueueStatus}>
                  Retry Queue Status
                </button>
              </div>
            ) : (
              <>
                <div className="row mb-4">
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--primary-color)' }}>{queueStatus.fetch_queue_size || 0}</h4>
                      <p>Fetch Queue</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--secondary-color)' }}>{queueStatus.analysis_queue_size || 0}</h4>
                      <p>Analysis Queue</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: queueStatus.fetch_processing_active ? 'var(--success-color)' : 'var(--gray-500)' }}>
                        {queueStatus.fetch_processing_active ? 'ON' : 'OFF'}
                      </h4>
                      <p>Fetch Workers</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: queueStatus.analysis_processing_active ? 'var(--success-color)' : 'var(--gray-500)' }}>
                        {queueStatus.analysis_processing_active ? 'ON' : 'OFF'}
                      </h4>
                      <p>Analysis Workers</p>
                    </div>
                  </div>
                </div>

                <p style={{ marginBottom: 'var(--spacing-md)', color: 'var(--gray-600)' }}>
                  {queueStatus.message || 'Queue status available'}
                </p>

                <div className="d-flex flex-wrap gap-2 mb-2">
                  <button
                    className="btn-professional btn-primary"
                    onClick={queueFetchJobs}
                    disabled={jobActionLoading === 'fetch'}
                  >
                    {jobActionLoading === 'fetch' ? 'Queueing Fetch...' : 'Queue Fetch Jobs'}
                  </button>
                  <button
                    className="btn-professional btn-primary"
                    onClick={queueAnalyzeJobs}
                    disabled={jobActionLoading === 'analysis'}
                  >
                    {jobActionLoading === 'analysis' ? 'Queueing Analysis...' : 'Queue Analysis Jobs'}
                  </button>
                  <button
                    className="btn-professional btn-secondary"
                    onClick={restartWorkers}
                    disabled={jobActionLoading === 'restart'}
                  >
                    {jobActionLoading === 'restart' ? 'Restarting...' : 'Restart Workers'}
                  </button>
                  <button className="btn-professional btn-secondary" onClick={fetchQueueStatus}>
                    Refresh Queue Status
                  </button>
                </div>

                <p style={{ color: 'var(--gray-600)', marginBottom: 'var(--spacing-sm)' }}>
                  {selectedCaseRefs.length
                    ? `Queue actions will target selected cases (${selectedCaseRefs.length}).`
                    : selectedBoardDates.length
                    ? `Queue actions will target selected board dates (${selectedBoardDates.length}).`
                    : 'Queue actions currently target the active dashboard filters.'}
                </p>

                {jobActionMessage && (
                  <p style={{ color: 'var(--success-color)', marginTop: 'var(--spacing-sm)' }}>{jobActionMessage}</p>
                )}
                {jobActionError && (
                  <p style={{ color: 'var(--error-color)', marginTop: 'var(--spacing-sm)' }}>{jobActionError}</p>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">Board Upload Inventory and Pleader Allocation</h2>
          </div>
          <div className="card-body">
            <div className="d-flex flex-wrap gap-3 mb-4" style={{ alignItems: 'end' }}>
              <div className="form-group" style={{ minWidth: '180px' }}>
                <label className="form-label">Filter Type</label>
                <select
                  className="form-control"
                  value={boardFilterType}
                  onChange={(e) => setBoardFilterType(e.target.value)}
                >
                  <option value="quarter">Year and Quarter</option>
                  <option value="year">Year</option>
                  <option value="date_range">Date Range</option>
                </select>
              </div>

              {(boardFilterType === 'quarter' || boardFilterType === 'year') && (
                <div className="form-group" style={{ minWidth: '120px' }}>
                  <label className="form-label">Year</label>
                  <input
                    type="number"
                    className="form-control"
                    value={boardYear}
                    min="2000"
                    max={currentYear + 5}
                    onChange={(e) => setBoardYear(e.target.value)}
                  />
                </div>
              )}

              {boardFilterType === 'quarter' && (
                <div className="form-group" style={{ minWidth: '120px' }}>
                  <label className="form-label">Quarter</label>
                  <select
                    className="form-control"
                    value={boardQuarter}
                    onChange={(e) => setBoardQuarter(e.target.value)}
                  >
                    <option value="1">Q1</option>
                    <option value="2">Q2</option>
                    <option value="3">Q3</option>
                    <option value="4">Q4</option>
                  </select>
                </div>
              )}

              {boardFilterType === 'date_range' && (
                <>
                  <div className="form-group" style={{ minWidth: '160px' }}>
                    <label className="form-label">Start Date</label>
                    <input
                      type="date"
                      className="form-control"
                      value={boardDateRange.start}
                      onChange={(e) => setBoardDateRange(prev => ({ ...prev, start: e.target.value }))}
                    />
                  </div>
                  <div className="form-group" style={{ minWidth: '160px' }}>
                    <label className="form-label">End Date</label>
                    <input
                      type="date"
                      className="form-control"
                      value={boardDateRange.end}
                      onChange={(e) => setBoardDateRange(prev => ({ ...prev, end: e.target.value }))}
                    />
                  </div>
                </>
              )}

              <div className="form-group" style={{ minWidth: '120px' }}>
                <label className="form-label">Rows</label>
                <input
                  type="number"
                  className="form-control"
                  value={boardLimit}
                  min="20"
                  max="1000"
                  onChange={(e) => setBoardLimit(Number(e.target.value || 180))}
                />
              </div>

              <div className="form-group">
                <button className="btn-professional btn-primary" onClick={fetchBoardDateSummary}>
                  Apply Filters
                </button>
              </div>
            </div>

            {boardSummaryLoading ? (
              <div className="text-center p-4">
                <div className="loading-text">
                  <span className="loading"></span>
                  Loading board date summary...
                </div>
              </div>
            ) : boardSummaryError ? (
              <div className="text-center p-4">
                <p style={{ color: 'var(--error-color)' }}>{boardSummaryError}</p>
                <button className="btn-professional btn-primary" onClick={fetchBoardDateSummary}>
                  Retry
                </button>
              </div>
            ) : (
              <>
                <div className="row mb-4">
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--primary-color)' }}>{boardSummary.summary.total_board_dates || 0}</h4>
                      <p>Board Dates</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--secondary-color)' }}>{boardSummary.summary.total_cases || 0}</h4>
                      <p>Total Cases</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--accent-color)' }}>{selectedBoardDates.length}</h4>
                      <p>Selected Dates</p>
                    </div>
                  </div>
                </div>

                <div className="d-flex flex-wrap gap-2 mb-3">
                  <button className="btn-professional btn-secondary" onClick={selectAllBoardDatesOnPage}>
                    Select All on Page
                  </button>
                  <button className="btn-professional btn-secondary" onClick={clearBoardDateSelection}>
                    Clear Selection
                  </button>
                  <button
                    className="btn-professional btn-primary"
                    onClick={fetchSelectedBoardDistribution}
                    disabled={!selectedBoardDates.length || selectedDistributionLoading}
                  >
                    {selectedDistributionLoading ? 'Analyzing...' : 'Analyze Selected Dates'}
                  </button>
                </div>

                <div style={{
                  maxHeight: '420px',
                  overflowY: 'auto',
                  border: '1px solid var(--gray-200)',
                  borderRadius: 'var(--radius-md)'
                }}>
                  <table className="table-professional" style={{ margin: 0 }}>
                    <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--gray-50)', zIndex: 10 }}>
                      <tr>
                        <th>Select</th>
                        <th>Board Date</th>
                        <th>Cases on Board</th>
                        <th>Distinct Respondent Lawyers</th>
                        <th>Distinct Petitioner Lawyers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getPaginatedData(boardSummary.rows || [], boardCurrentPage).map((row) => {
                        const isSelected = selectedBoardDates.includes(row.board_date);
                        return (
                          <tr
                            key={row.board_date}
                            onClick={() => toggleBoardDateSelection(row.board_date)}
                            style={{ cursor: 'pointer', backgroundColor: isSelected ? 'rgba(37, 99, 235, 0.08)' : 'transparent' }}
                          >
                            <td>
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleBoardDateSelection(row.board_date)}
                                onClick={(e) => e.stopPropagation()}
                              />
                            </td>
                            <td><strong>{row.board_date}</strong></td>
                            <td>{row.cases_count}</td>
                            <td>{row.unique_respondent_lawyers}</td>
                            <td>{row.unique_petitioner_lawyers}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {(boardSummary.rows || []).length > 0 && (
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: 'var(--spacing-md)',
                    padding: 'var(--spacing-sm)',
                    backgroundColor: 'var(--gray-50)',
                    borderRadius: 'var(--radius-sm)'
                  }}>
                    <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)' }}>
                      Showing {boardCurrentPage * ITEMS_PER_PAGE + 1} - {Math.min((boardCurrentPage + 1) * ITEMS_PER_PAGE, (boardSummary.rows || []).length)} of {(boardSummary.rows || []).length}
                    </span>
                    <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                      <button
                        className="btn-professional btn-secondary"
                        style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                        onClick={() => setBoardCurrentPage(Math.max(0, boardCurrentPage - 1))}
                        disabled={boardCurrentPage === 0}
                      >
                        â† Previous
                      </button>
                      <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)', alignSelf: 'center' }}>
                        Page {boardCurrentPage + 1} of {getTotalPages((boardSummary.rows || []).length)}
                      </span>
                      <button
                        className="btn-professional btn-secondary"
                        style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                        onClick={() => setBoardCurrentPage(Math.min(getTotalPages((boardSummary.rows || []).length) - 1, boardCurrentPage + 1))}
                        disabled={boardCurrentPage >= getTotalPages((boardSummary.rows || []).length) - 1}
                      >
                        Next â†’
                      </button>
                    </div>
                  </div>
                )}

                {selectedDistributionError && (
                  <div className="mt-3">
                    <p style={{ color: 'var(--error-color)' }}>{selectedDistributionError}</p>
                  </div>
                )}

                {(selectedDistribution.distribution || []).length > 0 && (
                  <div style={{ marginTop: 'var(--spacing-xl)' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--spacing-xl)' }}>
                      <div className="card-professional">
                        <div className="card-header">
                          <h2 className="section-title">AGP Allocation for Selected Dates</h2>
                        </div>
                        <div className="card-body">
                          <p style={{ marginBottom: 'var(--spacing-sm)', color: 'var(--gray-600)' }}>
                            Selected dates: {(selectedDistribution.selected_dates || []).length} | Total selected cases: {selectedDistribution.total_cases || 0}
                          </p>
                          <div style={{ height: '360px', position: 'relative' }}>
                            <Bar
                              data={selectedDistributionChartData}
                              options={{
                                ...chartOptions,
                                indexAxis: 'y',
                                plugins: {
                                  ...chartOptions.plugins,
                                  tooltip: {
                                    callbacks: {
                                      label: function(context) {
                                        return `${context.label}: ${context.parsed.x} matters`;
                                      }
                                    }
                                  }
                                }
                              }}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="card-professional">
                        <div className="card-header">
                          <h2 className="section-title">AGP Allocation Table</h2>
                        </div>
                        <div className="card-body">
                          <div style={{ maxHeight: '360px', overflowY: 'auto' }}>
                            <table className="table-professional">
                              <thead>
                                <tr>
                                  <th>Government Pleader</th>
                                  <th>Assigned Cases</th>
                                  <th>Share</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(selectedDistribution.distribution || []).map((row) => (
                                  <tr key={row.agp_name}>
                                    <td>{row.agp_name}</td>
                                    <td><strong>{row.matters}</strong></td>
                                    <td>{row.percentage}%</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <div style={{ marginTop: 'var(--spacing-xl)' }}>
                  <div className="card-professional">
                    <div className="card-header">
                      <h2 className="section-title">Cases for Selected Board Dates</h2>
                    </div>
                    <div className="card-body">
                      {selectedDateCasesLoading ? (
                        <div className="text-center p-3">
                          <div className="loading-text">
                            <span className="loading"></span>
                            Loading cases...
                          </div>
                        </div>
                      ) : selectedDateCasesError ? (
                        <div className="text-center p-3">
                          <p style={{ color: 'var(--error-color)' }}>{selectedDateCasesError}</p>
                        </div>
                      ) : !selectedBoardDates.length ? (
                        <p style={{ color: 'var(--gray-600)' }}>
                          Select one or more board dates to see case-level details.
                        </p>
                      ) : (
                        <>
                          <div className="d-flex flex-wrap gap-2 mb-2">
                            <button className="btn-professional btn-secondary" onClick={selectAllCasesForSelectedDates}>
                              Select All Cases
                            </button>
                            <button className="btn-professional btn-secondary" onClick={clearCaseSelection}>
                              Clear Case Selection
                            </button>
                            <p style={{ color: 'var(--gray-600)', margin: 0, alignSelf: 'center' }}>
                              Total cases: {selectedDateCases.length} | Selected: {selectedCaseRefs.length}
                            </p>
                          </div>

                          <div style={{ maxHeight: '320px', overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                            <table className="table-professional" style={{ margin: 0 }}>
                              <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--gray-50)', zIndex: 10 }}>
                                <tr>
                                  <th>Select</th>
                                  <th>Board Date</th>
                                  <th>Case Ref</th>
                                  <th>Respondent Lawyer</th>
                                  <th>Petitioner Lawyer</th>
                                </tr>
                              </thead>
                              <tbody>
                                {selectedDateCases.map((item) => {
                                  const isSelected = selectedCaseRefs.includes(item.case_ref);
                                  return (
                                    <tr
                                      key={`${item.case_id}-${item.case_ref}`}
                                      onClick={() => toggleCaseSelection(item.case_ref)}
                                      style={{ cursor: 'pointer', backgroundColor: isSelected ? 'rgba(16, 185, 129, 0.08)' : 'transparent' }}
                                    >
                                      <td>
                                        <input
                                          type="checkbox"
                                          checked={isSelected}
                                          onChange={() => toggleCaseSelection(item.case_ref)}
                                          onClick={(e) => e.stopPropagation()}
                                        />
                                      </td>
                                      <td>{item.board_date}</td>
                                      <td><strong>{item.case_ref}</strong></td>
                                      <td>{item.respondent_lawyer || '-'}</td>
                                      <td>{item.petitioner_lawyer || '-'}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* NEW ANALYTICS SECTION - Total Matters by Date Range with Average */}
      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">ðŸ“Š Total Matters by Date Range (Last 5 Days Default)</h2>
          </div>
          <div className="card-body">
            <div className="d-flex flex-wrap gap-3 mb-4">
              <div className="form-group" style={{ minWidth: '150px' }}>
                <label className="form-label">Start Date</label>
                <input
                  type="date"
                  className="form-control"
                  value={dateRange.start}
                  onChange={e => setDateRange(prev => ({ ...prev, start: e.target.value }))}
                  placeholder="Defaults to 5 days ago"
                />
              </div>
              <div className="form-group" style={{ minWidth: '150px' }}>
                <label className="form-label">End Date</label>
                <input
                  type="date"
                  className="form-control"
                  value={dateRange.end}
                  onChange={e => setDateRange(prev => ({ ...prev, end: e.target.value }))}
                  placeholder="Defaults to today"
                />
              </div>
              <div className="form-group d-flex align-items-end">
                <button
                  className="btn-professional btn-primary"
                  onClick={fetchMattersByDateRange}
                >
                  Refresh Data
                </button>
              </div>
            </div>

            {analyticsLoading.matters ? (
              <div className="text-center p-4">
                <div className="loading-text">
                  <span className="loading"></span>
                  Loading matters data...
                </div>
              </div>
            ) : analyticsError.matters ? (
              <div className="text-center p-4">
                <p style={{ color: 'var(--error-color)' }}>{analyticsError.matters}</p>
                <button className="btn-professional btn-primary" onClick={fetchMattersByDateRange}>
                  Retry
                </button>
              </div>
            ) : mattersByDateRange.data.length === 0 ? (
              <div className="text-center p-4">
                <p style={{ color: 'var(--gray-500)' }}>No data available for selected date range</p>
              </div>
            ) : (
              <>
                <div className="row mb-4">
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--primary-color)' }}>{mattersByDateRange.summary.total_matters || 0}</h4>
                      <p>Total Matters</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--secondary-color)' }}>{mattersByDateRange.summary.average_per_day || 0}</h4>
                      <p>Daily Average</p>
                    </div>
                  </div>
                  <div className="col-md-3">
                    <div className="stat-card">
                      <h4 style={{ color: 'var(--accent-color)' }}>{mattersByDateRange.summary.days_covered || 0}</h4>
                      <p>Days Covered</p>
                    </div>
                  </div>
                </div>

                <div style={{ height: '400px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={mattersByDateRange.data}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 12 }}
                        angle={-45}
                        textAnchor="end"
                        height={80}
                      />
                      <YAxis />
                      <RechartsTooltip
                        formatter={(value, name) => [
                          name === 'total_matters' ? `${value} matters` : `${value} avg`,
                          name === 'total_matters' ? 'Total Matters' : 'Average'
                        ]}
                        labelFormatter={(label) => `Date: ${label}`}
                      />
                      <RechartsLegend />
                      <RechartsBar
                        dataKey="total_matters"
                        fill="#3b82f6"
                        name="Total Matters"
                        opacity={0.8}
                      />
                      <RechartsLine
                        type="monotone"
                        dataKey="average"
                        stroke="#ef4444"
                        strokeWidth={3}
                        name="Daily Average"
                        dot={{ fill: '#ef4444', strokeWidth: 2, r: 4 }}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
          </div>
        </div>
      </div>


          {/* AGP Statistics Section */}
          <div className="dashboard-section">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--spacing-xl)', marginBottom: 'var(--spacing-xl)' }}>
              {/* AGP Data Table */}
              <div className="card-professional">
                <div className="card-header">
                  <h2 className="section-title">ðŸ‘¤ AGP Statistics ({agpStats.length} records)</h2>
                </div>
                <div className="card-body">
                  <div className="d-flex flex-wrap gap-3 mb-4">
                    <div className="form-group" style={{ minWidth: '200px' }}>
                      <label className="form-label">AGP Name (Optional)</label>
                      <input
                        type="text"
                        className="form-control"
                        placeholder="Enter AGP name to filter"
                        value={agpName}
                        onChange={e => setAgpName(e.target.value)}
                      />
                    </div>
                    <div className="form-group d-flex align-items-end">
                      <button
                        className="btn-professional btn-primary"
                        onClick={fetchAgpStats}
                      >
                        Refresh Data
                      </button>
                    </div>
                  </div>

                  {agpLoading ? (
                    <div className="text-center p-4">
                      <div className="loading-text">
                        <span className="loading"></span>
                        Loading AGP statistics...
                      </div>
                    </div>
                  ) : agpError ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--error-color)' }}>{agpError}</p>
                      <button className="btn-professional btn-primary" onClick={fetchAgpStats}>
                        Retry
                      </button>
                    </div>
                  ) : agpStats.length === 0 ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--gray-500)' }}>No AGP data available</p>
                    </div>
                  ) : (
                    <>
                      {/* Scrollable Table Container */}
                      <div style={{
                        maxHeight: '400px',
                        overflowY: 'auto',
                        border: '1px solid var(--gray-200)',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--gray-25)'
                      }}>
                        <table className="table-professional" style={{ margin: 0 }}>
                          <thead style={{
                            position: 'sticky',
                            top: 0,
                            backgroundColor: 'var(--gray-50)',
                            zIndex: 10
                          }}>
                            <tr>
                              <th>AGP Name</th>
                              <th>Total Matters</th>
                            </tr>
                          </thead>
                          <tbody>
                            {getPaginatedData(agpStats, agpCurrentPage).map((row, i) => (
                              <tr key={i}>
                                <td>{row.agp_name}</td>
                                <td><strong>{row.matters}</strong></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination Controls */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginTop: 'var(--spacing-md)',
                        padding: 'var(--spacing-sm)',
                        backgroundColor: 'var(--gray-50)',
                        borderRadius: 'var(--radius-sm)'
                      }}>
                        <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)' }}>
                          Showing {agpCurrentPage * ITEMS_PER_PAGE + 1} - {Math.min((agpCurrentPage + 1) * ITEMS_PER_PAGE, agpStats.length)} of {agpStats.length}
                        </span>
                        <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                          <button
                            className="btn-professional btn-secondary"
                            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            onClick={() => setAgpCurrentPage(Math.max(0, agpCurrentPage - 1))}
                            disabled={agpCurrentPage === 0}
                          >
                            â† Previous
                          </button>
                          <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)', alignSelf: 'center' }}>
                            Page {agpCurrentPage + 1} of {getTotalPages(agpStats.length)}
                          </span>
                          <button
                            className="btn-professional btn-secondary"
                            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            onClick={() => setAgpCurrentPage(Math.min(getTotalPages(agpStats.length) - 1, agpCurrentPage + 1))}
                            disabled={agpCurrentPage >= getTotalPages(agpStats.length) - 1}
                          >
                            Next â†’
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* AGP Distribution Chart */}
              <div className="card-professional">
                <div className="card-header">
                  <h2 className="section-title">ðŸ“Š AGP Distribution</h2>
                </div>
                <div className="card-body">
                  {agpLoading ? (
                    <div className="text-center p-4">
                      <div className="loading-text">
                        <span className="loading"></span>
                        Loading chart...
                      </div>
                    </div>
                  ) : agpStats.length === 0 ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--gray-500)' }}>No data available for chart</p>
                    </div>
                  ) : (
                    <div style={{ height: '400px', position: 'relative' }}>
                      <Doughnut
                        data={agpDoughnutData}
                        options={{
                          responsive: true,
                          maintainAspectRatio: false,
                          plugins: {
                            legend: {
                              position: 'right',
                              labels: {
                                boxWidth: 12,
                                padding: 15,
                                font: {
                                  size: 11
                                }
                              }
                            },
                            tooltip: {
                              callbacks: {
                                label: function(context) {
                                  const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                  const percentage = ((context.parsed / total) * 100).toFixed(1);
                                  return `${context.label}: ${context.parsed} (${percentage}%)`;
                                }
                              }
                            }
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* AGP Bar Chart */}
            {!agpLoading && agpStats.length > 0 && (
              <div className="card-professional">
                <div className="card-header">
                  <h2 className="section-title">ðŸ“ˆ Top 10 AGPs by Case Load</h2>
                </div>
                <div className="card-body">
                  <div style={{ height: '300px', position: 'relative' }}>
                    <Bar data={agpChartData} options={chartOptions} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Monthly Average Section */}
          <div className="dashboard-section">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--spacing-xl)' }}>
              {/* Monthly Average Data Table */}
              <div className="card-professional">
                <div className="card-header">
                  <h2 className="section-title">ðŸ“ˆ Monthly Average Matters per AGP ({monthlyAvg.length} records)</h2>
                </div>
                <div className="card-body">
                  <div className="d-flex flex-wrap gap-3 mb-4">
                    <div className="form-group" style={{ minWidth: '150px' }}>
                      <label className="form-label">Year</label>
                      <input
                        type="number"
                        className="form-control"
                        value={year}
                        onChange={e => setYear(e.target.value)}
                        min="2000"
                        max={new Date().getFullYear()}
                      />
                    </div>
                    <div className="form-group d-flex align-items-end">
                      <button
                        className="btn-professional btn-primary"
                        onClick={fetchMonthlyAvg}
                      >
                        Refresh Data
                      </button>
                    </div>
                  </div>

                  {monthlyLoading ? (
                    <div className="text-center p-4">
                      <div className="loading-text">
                        <span className="loading"></span>
                        Loading monthly averages...
                      </div>
                    </div>
                  ) : monthlyError ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--error-color)' }}>{monthlyError}</p>
                      <button className="btn-professional btn-primary" onClick={fetchMonthlyAvg}>
                        Retry
                      </button>
                    </div>
                  ) : monthlyAvg.length === 0 ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--gray-500)' }}>No monthly average data available for {year}</p>
                    </div>
                  ) : (
                    <>
                      {/* Scrollable Table Container */}
                      <div style={{
                        maxHeight: '400px',
                        overflowY: 'auto',
                        border: '1px solid var(--gray-200)',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--gray-25)'
                      }}>
                        <table className="table-professional" style={{ margin: 0 }}>
                          <thead style={{
                            position: 'sticky',
                            top: 0,
                            backgroundColor: 'var(--gray-50)',
                            zIndex: 10
                          }}>
                            <tr>
                              <th>AGP Name</th>
                              <th>Monthly Average</th>
                            </tr>
                          </thead>
                          <tbody>
                            {getPaginatedData(monthlyAvg, monthlyCurrentPage).map((row, i) => (
                              <tr key={i}>
                                <td>{row.agp_name}</td>
                                <td><strong>{row.monthly_avg}</strong> matters/month</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination Controls */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginTop: 'var(--spacing-md)',
                        padding: 'var(--spacing-sm)',
                        backgroundColor: 'var(--gray-50)',
                        borderRadius: 'var(--radius-sm)'
                      }}>
                        <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)' }}>
                          Showing {monthlyCurrentPage * ITEMS_PER_PAGE + 1} - {Math.min((monthlyCurrentPage + 1) * ITEMS_PER_PAGE, monthlyAvg.length)} of {monthlyAvg.length}
                        </span>
                        <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                          <button
                            className="btn-professional btn-secondary"
                            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            onClick={() => setMonthlyCurrentPage(Math.max(0, monthlyCurrentPage - 1))}
                            disabled={monthlyCurrentPage === 0}
                          >
                            â† Previous
                          </button>
                          <span style={{ fontSize: '0.875rem', color: 'var(--gray-600)', alignSelf: 'center' }}>
                            Page {monthlyCurrentPage + 1} of {getTotalPages(monthlyAvg.length)}
                          </span>
                          <button
                            className="btn-professional btn-secondary"
                            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            onClick={() => setMonthlyCurrentPage(Math.min(getTotalPages(monthlyAvg.length) - 1, monthlyCurrentPage + 1))}
                            disabled={monthlyCurrentPage >= getTotalPages(monthlyAvg.length) - 1}
                          >
                            Next â†’
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Monthly Average Chart */}
              <div className="card-professional">
                <div className="card-header">
                  <h2 className="section-title">ðŸ“Š Top 10 Monthly Averages</h2>
                </div>
                <div className="card-body">
                  {monthlyLoading ? (
                    <div className="text-center p-4">
                      <div className="loading-text">
                        <span className="loading"></span>
                        Loading chart...
                      </div>
                    </div>
                  ) : monthlyAvg.length === 0 ? (
                    <div className="text-center p-4">
                      <p style={{ color: 'var(--gray-500)' }}>No data available for chart</p>
                    </div>
                  ) : (
                    <div style={{ height: '400px', position: 'relative' }}>
                      <Bar
                        data={monthlyChartData}
                        options={{
                          ...chartOptions,
                          plugins: {
                            ...chartOptions.plugins,
                            tooltip: {
                              callbacks: {
                                label: function(context) {
                                  return `${context.dataset.label}: ${context.parsed.y.toFixed(1)} matters/month`;
                                }
                              }
                            }
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
    </div>
  );
};

export default Dashboard;
