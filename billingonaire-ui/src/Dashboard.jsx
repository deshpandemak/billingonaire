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

ChartJS.register(
  CategoryScale, LinearScale, BarElement, LineElement, PointElement,
  Title, Tooltip, Legend, ArcElement
);

const ITEMS_PER_PAGE = 20;

// ─── Small helpers ────────────────────────────────────────────────────────────
const StatCard = ({ value, label, color, loading }) => (
  <div className="stat-card" style={{ textAlign: 'center' }}>
    {loading
      ? <div className="loading-text"><span className="loading" /></div>
      : <h4 style={{ color: color || 'var(--primary-color)', fontSize: '1.6rem', margin: 0 }}>{value ?? '—'}</h4>}
    <p style={{ margin: '0.25rem 0 0', color: 'var(--gray-600)', fontSize: '0.82rem' }}>{label}</p>
  </div>
);

const Paginator = ({ current, total, onChange }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.75rem', padding: '0.4rem 0.5rem', background: 'var(--gray-50)', borderRadius: 'var(--radius-sm)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--gray-600)' }}>
      Page {current + 1} of {total}
    </span>
    <div style={{ display: 'flex', gap: '0.4rem' }}>
      <button className="btn-professional btn-secondary" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick={() => onChange(Math.max(0, current - 1))} disabled={current === 0}>← Prev</button>
      <button className="btn-professional btn-secondary" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick={() => onChange(Math.min(total - 1, current + 1))} disabled={current >= total - 1}>Next →</button>
    </div>
  </div>
);

const SectionCard = ({ title, children, action }) => (
  <div className="card-professional">
    <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <h2 className="section-title" style={{ margin: 0 }}>{title}</h2>
      {action}
    </div>
    <div className="card-body">{children}</div>
  </div>
);

const LoadingPlaceholder = ({ text = 'Loading…' }) => (
  <div className="text-center p-4">
    <div className="loading-text"><span className="loading" />{text}</div>
  </div>
);

const ErrorPlaceholder = ({ msg, onRetry }) => (
  <div className="text-center p-4">
    <p style={{ color: 'var(--error-color)' }}>{msg}</p>
    {onRetry && <button className="btn-professional btn-primary" onClick={onRetry}>Retry</button>}
  </div>
);

// ─── Chart base options ───────────────────────────────────────────────────────
const chartOptions = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { position: 'bottom' }, title: { display: false } },
  scales: {
    y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.07)' } },
    x: { grid: { display: false } },
  },
};

const CHART_COLORS = [
  'rgba(59,130,246,0.8)', 'rgba(16,185,129,0.8)', 'rgba(245,158,11,0.8)',
  'rgba(239,68,68,0.8)', 'rgba(139,92,246,0.8)', 'rgba(236,72,153,0.8)',
  'rgba(14,165,233,0.8)', 'rgba(34,197,94,0.8)',
];

// ─── Main component ───────────────────────────────────────────────────────────
const Dashboard = () => {
  const { addToast } = useToast();
  const currentDate  = new Date();
  const currentYear  = currentDate.getFullYear();
  const currentQuarter = Math.floor(currentDate.getMonth() / 3) + 1;

  // User profile (for role-gating admin section)
  const [userProfile, setUserProfile] = useState(null);
  const isAdmin = userProfile?.role === 'admin';

  // Overview stats (top cards)
  const [overviewStats, setOverviewStats] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  // AGP stats
  const [agpStats, setAgpStats]       = useState([]);
  const [agpLoading, setAgpLoading]   = useState(true);
  const [agpError, setAgpError]       = useState('');
  const [agpName, setAgpName]         = useState('');
  const [agpPage, setAgpPage]         = useState(0);

  // Monthly averages
  const [monthlyAvg, setMonthlyAvg]         = useState([]);
  const [monthlyLoading, setMonthlyLoading] = useState(true);
  const [monthlyError, setMonthlyError]     = useState('');
  const [year, setYear]                     = useState(currentYear.toString());
  const [monthlyPage, setMonthlyPage]       = useState(0);

  // Matters by date range
  const [mattersByDate, setMattersByDate]   = useState({ data: [], summary: {} });
  const [mattersLoading, setMattersLoading] = useState(true);
  const [mattersError, setMattersError]     = useState('');
  const [dateRange, setDateRange]           = useState({ start: '', end: '' });

  // Board date summary
  const [boardSummary, setBoardSummary]       = useState({ rows: [], summary: {}, filters: {} });
  const [boardLoading, setBoardLoading]       = useState(true);
  const [boardError, setBoardError]           = useState('');
  const [boardPage, setBoardPage]             = useState(0);
  const [boardFilterType, setBoardFilterType] = useState('quarter');
  const [boardYear, setBoardYear]             = useState(currentYear.toString());
  const [boardQuarter, setBoardQuarter]       = useState(currentQuarter.toString());
  const [boardDateRange, setBoardDateRange]   = useState({ start: '', end: '' });
  const [boardLimit, setBoardLimit]           = useState(180);

  // Selection for targeted queue actions
  const [selectedDates, setSelectedDates]   = useState([]);
  const [selectedCaseRefs, setSelectedCaseRefs] = useState([]);
  const [distribution, setDistribution]     = useState({ distribution: [], total_cases: 0, selected_dates: [], board_breakdown: [] });
  const [distLoading, setDistLoading]       = useState(false);
  const [distError, setDistError]           = useState('');
  const [dateCases, setDateCases]           = useState([]);
  const [dateCasesLoading, setDateCasesLoading] = useState(false);
  const [dateCasesError, setDateCasesError] = useState('');

  // Queue / pipeline (admin)
  const [queueStatus, setQueueStatus]       = useState({ fetch_queue_size: 0, analysis_queue_size: 0, fetch_processing_active: false, analysis_processing_active: false, status: 'inactive', message: '' });
  const [queueLoading, setQueueLoading]     = useState(true);
  const [queueError, setQueueError]         = useState('');
  const [jobLoading, setJobLoading]         = useState('');
  const [jobMessage, setJobMessage]         = useState('');
  const [jobError, setJobError]             = useState('');
  const [showAdmin, setShowAdmin]           = useState(false);

  // ─── Fetch helpers ──────────────────────────────────────────────────────────

  const fetchUserProfile = useCallback(async () => {
    try {
      const data = await authenticatedFetchJSON('/user/profile');
      setUserProfile(data);
    } catch (_) { /* non-critical */ }
  }, []);

  const fetchOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const data = await authenticatedFetchJSON('/orders/overview-stats');
      setOverviewStats(data);
    } catch (_) {
      setOverviewStats(null);
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const fetchAgpStats = useCallback(async () => {
    setAgpLoading(true); setAgpError(''); setAgpPage(0);
    try {
      const url = agpName ? `/dashboard/agp-stats?agp_name=${encodeURIComponent(agpName)}` : '/dashboard/agp-stats';
      setAgpStats(await authenticatedFetchJSON(url));
    } catch (_) {
      setAgpError('Failed to load AGP statistics'); setAgpStats([]);
    } finally { setAgpLoading(false); }
  }, [agpName]);

  const fetchMonthlyAvg = useCallback(async () => {
    setMonthlyLoading(true); setMonthlyError(''); setMonthlyPage(0);
    try {
      setMonthlyAvg(await authenticatedFetchJSON(`/dashboard/monthly-avg${year ? `?year=${year}` : ''}`));
    } catch (_) {
      setMonthlyError('Failed to load monthly averages'); setMonthlyAvg([]);
    } finally { setMonthlyLoading(false); }
  }, [year]);

  const fetchMatters = useCallback(async () => {
    setMattersLoading(true); setMattersError('');
    const params = [];
    if (dateRange.start) params.push(`start_date=${dateRange.start}`);
    if (dateRange.end)   params.push(`end_date=${dateRange.end}`);
    try {
      setMattersByDate(await authenticatedFetchJSON(`/dashboard/matters-by-date-range${params.length ? '?' + params.join('&') : ''}`));
    } catch (_) {
      setMattersError('Failed to load matters data'); setMattersByDate({ data: [], summary: {} });
    } finally { setMattersLoading(false); }
  }, [dateRange.start, dateRange.end]);

  const fetchBoardSummary = useCallback(async () => {
    setBoardLoading(true); setBoardError('');
    const p = new URLSearchParams();
    p.set('limit', String(boardLimit || 180));
    if (boardFilterType === 'quarter') {
      if (boardYear)    p.set('year', boardYear);
      if (boardQuarter) p.set('quarter', boardQuarter);
    } else if (boardFilterType === 'year') {
      if (boardYear)    p.set('year', boardYear);
    } else {
      if (boardDateRange.start) p.set('start_date', boardDateRange.start);
      if (boardDateRange.end)   p.set('end_date',   boardDateRange.end);
    }
    try {
      const data = await authenticatedFetchJSON(`/dashboard/board-date-summary?${p.toString()}`);
      setBoardSummary(data);
      setBoardPage(0);
      const dateSet = new Set((data.rows || []).map(r => r.board_date));
      setSelectedDates(prev => prev.filter(d => dateSet.has(d)));
    } catch (_) {
      setBoardError('Failed to load board date summary'); setBoardSummary({ rows: [], summary: {}, filters: {} }); setSelectedDates([]);
    } finally { setBoardLoading(false); }
  }, [boardDateRange.end, boardDateRange.start, boardFilterType, boardLimit, boardQuarter, boardYear]);

  const fetchDistribution = useCallback(async () => {
    if (!selectedDates.length) { setDistError('Select at least one board date first'); return; }
    setDistLoading(true); setDistError('');
    const p = new URLSearchParams();
    selectedDates.forEach(d => p.append('board_dates', d));
    try {
      setDistribution(await authenticatedFetchJSON(`/dashboard/board-date-agp-distribution?${p.toString()}`));
    } catch (_) {
      setDistError('Failed to load distribution'); setDistribution({ distribution: [], total_cases: 0, selected_dates: [], board_breakdown: [] });
    } finally { setDistLoading(false); }
  }, [selectedDates]);

  const fetchDateCases = useCallback(async () => {
    if (!selectedDates.length) { setDateCases([]); setSelectedCaseRefs([]); return; }
    setDateCasesLoading(true); setDateCasesError('');
    const p = new URLSearchParams();
    selectedDates.forEach(d => p.append('board_dates', d));
    p.set('limit', '2000');
    try {
      const data = await authenticatedFetchJSON(`/dashboard/board-date-cases?${p.toString()}`);
      const cases = data.cases || [];
      setDateCases(cases);
      const refSet = new Set(cases.map(c => c.case_ref));
      setSelectedCaseRefs(prev => prev.filter(r => refSet.has(r)));
    } catch (_) {
      setDateCasesError('Failed to load case list'); setDateCases([]); setSelectedCaseRefs([]);
    } finally { setDateCasesLoading(false); }
  }, [selectedDates]);

  const fetchQueueStatus = useCallback(async () => {
    setQueueLoading(true); setQueueError('');
    try { setQueueStatus(await authenticatedFetchJSON('/queue/status') || {}); }
    catch (_) { setQueueError('Unable to fetch queue status'); }
    finally { setQueueLoading(false); }
  }, []);

  // ─── Queue actions ──────────────────────────────────────────────────────────

  const queueFetch = useCallback(async () => {
    setJobLoading('fetch'); setJobError(''); setJobMessage('');
    try {
      const filters = {};
      if (boardFilterType !== 'date_range' && boardYear) filters.case_year = boardYear;
      if (boardFilterType === 'date_range') {
        if (boardDateRange.start) filters.date_from = boardDateRange.start;
        if (boardDateRange.end)   filters.date_to   = boardDateRange.end;
      }
      const r = await authenticatedFetchJSON('/jobs/fetch-orders', {
        method: 'POST',
        body: JSON.stringify({ filters, board_dates: selectedDates, case_refs: selectedCaseRefs, limit: Math.min(Number(boardLimit) || 100, 300), max_sequences: 50 }),
      });
      setJobMessage(`Queued ${r.queued || 0} fetch jobs, skipped ${r.skipped_not_due || 0}`);
      await fetchQueueStatus();
    } catch (_) { setJobError('Failed to queue fetch jobs — admin access required.'); }
    finally { setJobLoading(''); }
  }, [boardDateRange, boardFilterType, boardLimit, boardYear, fetchQueueStatus, selectedCaseRefs, selectedDates]);

  const queueAnalysis = useCallback(async () => {
    setJobLoading('analysis'); setJobError(''); setJobMessage('');
    try {
      const r = await authenticatedFetchJSON('/jobs/analyze-orders', {
        method: 'POST',
        body: JSON.stringify({ board_dates: selectedDates, case_refs: selectedCaseRefs, limit: Math.min(Number(boardLimit) || 100, 300) }),
      });
      setJobMessage(`Queued ${r.queued || 0} analysis jobs, skipped ${r.skipped || 0}`);
      await fetchQueueStatus();
    } catch (_) { setJobError('Failed to queue analysis jobs — admin access required.'); }
    finally { setJobLoading(''); }
  }, [boardLimit, fetchQueueStatus, selectedCaseRefs, selectedDates]);

  const restartWorkers = useCallback(async () => {
    setJobLoading('restart'); setJobError(''); setJobMessage('');
    try {
      const r = await authenticatedFetchJSON('/queue/restart', { method: 'POST', body: JSON.stringify({}) });
      setJobMessage(r.message || 'Background workers restarted');
      await fetchQueueStatus();
    } catch (_) { setJobError('Failed to restart workers — admin access required.'); }
    finally { setJobLoading(''); }
  }, [fetchQueueStatus]);

  // ─── Effects — staggered to avoid 7 simultaneous Firestore scans ────────────
  useEffect(() => { fetchUserProfile(); }, [fetchUserProfile]);
  useEffect(() => { fetchBoardSummary(); }, [fetchBoardSummary]);
  useEffect(() => { const t = setTimeout(fetchOverview,   150); return () => clearTimeout(t); }, [fetchOverview]);
  useEffect(() => { const t = setTimeout(fetchAgpStats,   300); return () => clearTimeout(t); }, [fetchAgpStats]);
  useEffect(() => { const t = setTimeout(fetchMonthlyAvg, 450); return () => clearTimeout(t); }, [fetchMonthlyAvg]);
  useEffect(() => { const t = setTimeout(fetchMatters,    600); return () => clearTimeout(t); }, [fetchMatters]);
  useEffect(() => { fetchDateCases(); }, [fetchDateCases]);
  useEffect(() => {
    fetchQueueStatus();
    const id = window.setInterval(fetchQueueStatus, 15000);
    return () => window.clearInterval(id);
  }, [fetchQueueStatus]);

  // ─── Helpers ─────────────────────────────────────────────────────────────────
  const paginate = (arr, page) => arr.slice(page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE);
  const totalPages = len => Math.max(1, Math.ceil(len / ITEMS_PER_PAGE));

  const toggleDate = d => setSelectedDates(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d]);
  const selectPageDates = () => {
    const page = paginate(boardSummary.rows || [], boardPage).map(r => r.board_date);
    setSelectedDates(prev => Array.from(new Set([...prev, ...page])));
  };
  const clearSelection = () => {
    setSelectedDates([]);
    setDistribution({ distribution: [], total_cases: 0, selected_dates: [], board_breakdown: [] });
    setDistError(''); setDateCases([]); setSelectedCaseRefs([]); setDateCasesError('');
  };
  const toggleCase = ref => setSelectedCaseRefs(prev => prev.includes(ref) ? prev.filter(r => r !== ref) : [...prev, ref]);

  // ─── Chart data ───────────────────────────────────────────────────────────────
  const agpChartData = {
    labels: agpStats.slice(0, 10).map(i => i.agp_name),
    datasets: [{ label: 'Total Matters', data: agpStats.slice(0, 10).map(i => i.matters), backgroundColor: 'rgba(59,130,246,0.65)', borderColor: 'rgba(59,130,246,1)', borderWidth: 1 }],
  };
  const agpDoughnutData = {
    labels: agpStats.slice(0, 8).map(i => i.agp_name),
    datasets: [{ data: agpStats.slice(0, 8).map(i => i.matters), backgroundColor: CHART_COLORS, borderWidth: 2, borderColor: '#fff' }],
  };
  const monthlyChartData = {
    labels: monthlyAvg.slice(0, 10).map(i => i.agp_name),
    datasets: [{ label: 'Monthly Average', data: monthlyAvg.slice(0, 10).map(i => parseFloat(i.monthly_avg)), backgroundColor: 'rgba(16,185,129,0.65)', borderColor: 'rgba(16,185,129,1)', borderWidth: 1 }],
  };
  const distChartData = {
    labels: (distribution.distribution || []).slice(0, 12).map(i => i.agp_name),
    datasets: [{ label: 'Assigned Matters', data: (distribution.distribution || []).slice(0, 12).map(i => i.matters), backgroundColor: 'rgba(37,99,235,0.75)', borderColor: 'rgba(29,78,216,1)', borderWidth: 1 }],
  };

  // ─── Pipeline health indicators ───────────────────────────────────────────────
  const workersStalled = !queueLoading && queueStatus.fetch_queue_size > 0 && !queueStatus.fetch_processing_active;
  const totalQueued = (queueStatus.fetch_queue_size || 0) + (queueStatus.analysis_queue_size || 0);
  const pipelineOk = !workersStalled && totalQueued === 0;

  // ─── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="dashboard-container">
      {/* ── Header ── */}
      <div className="dashboard-header">
        <h1 className="dashboard-title">Legal Practice Dashboard</h1>
        <p className="dashboard-subtitle">Court matters, order analysis and AGP performance at a glance</p>
      </div>

      {/* ── 1. Summary stat cards ── */}
      <div className="dashboard-section">
        <div className="row g-3">
          <div className="col-6 col-md-3">
            <StatCard
              value={overviewStats?.total_cases?.toLocaleString()}
              label="Total Board Cases"
              color="var(--primary-color)"
              loading={overviewLoading}
            />
          </div>
          <div className="col-6 col-md-3">
            <StatCard
              value={overviewStats?.cases_with_orders?.toLocaleString()}
              label="Orders Fetched"
              color="var(--secondary-color)"
              loading={overviewLoading}
            />
          </div>
          <div className="col-6 col-md-3">
            <StatCard
              value={overviewStats ? `${overviewStats.analysis_completion_rate}%` : null}
              label="Analysis Complete"
              color={overviewStats?.analysis_completion_rate >= 80 ? 'var(--success-color)' : 'var(--warning-color, #f59e0b)'}
              loading={overviewLoading}
            />
          </div>
          <div className="col-6 col-md-3">
            <StatCard
              value={queueLoading ? null : pipelineOk ? 'Healthy' : `${totalQueued} queued`}
              label="Pipeline Status"
              color={pipelineOk ? 'var(--success-color)' : workersStalled ? 'var(--error-color)' : 'var(--warning-color, #f59e0b)'}
              loading={queueLoading}
            />
          </div>
        </div>
      </div>

      {/* ── 2. Board Date Inventory (primary operational view) ── */}
      <div className="dashboard-section">
        <SectionCard
          title="Board Upload Inventory"
          action={
            <span style={{ fontSize: '0.8rem', color: 'var(--gray-500)' }}>
              {boardSummary.summary.total_board_dates || 0} dates · {boardSummary.summary.total_cases || 0} cases
            </span>
          }
        >
          {/* Filter controls */}
          <div className="d-flex flex-wrap gap-3 mb-4" style={{ alignItems: 'flex-end' }}>
            <div className="form-group" style={{ minWidth: 160 }}>
              <label className="form-label">Filter</label>
              <select className="form-control" value={boardFilterType} onChange={e => setBoardFilterType(e.target.value)}>
                <option value="quarter">Year & Quarter</option>
                <option value="year">Year</option>
                <option value="date_range">Date Range</option>
              </select>
            </div>
            {(boardFilterType === 'quarter' || boardFilterType === 'year') && (
              <div className="form-group" style={{ minWidth: 110 }}>
                <label className="form-label">Year</label>
                <input type="number" className="form-control" value={boardYear} min="2000" max={currentYear + 5} onChange={e => setBoardYear(e.target.value)} />
              </div>
            )}
            {boardFilterType === 'quarter' && (
              <div className="form-group" style={{ minWidth: 110 }}>
                <label className="form-label">Quarter</label>
                <select className="form-control" value={boardQuarter} onChange={e => setBoardQuarter(e.target.value)}>
                  <option value="1">Q1</option><option value="2">Q2</option><option value="3">Q3</option><option value="4">Q4</option>
                </select>
              </div>
            )}
            {boardFilterType === 'date_range' && (
              <>
                <div className="form-group" style={{ minWidth: 150 }}>
                  <label className="form-label">From</label>
                  <input type="date" className="form-control" value={boardDateRange.start} onChange={e => setBoardDateRange(p => ({ ...p, start: e.target.value }))} />
                </div>
                <div className="form-group" style={{ minWidth: 150 }}>
                  <label className="form-label">To</label>
                  <input type="date" className="form-control" value={boardDateRange.end} onChange={e => setBoardDateRange(p => ({ ...p, end: e.target.value }))} />
                </div>
              </>
            )}
            <div className="form-group" style={{ minWidth: 100 }}>
              <label className="form-label">Rows</label>
              <input type="number" className="form-control" value={boardLimit} min="20" max="1000" onChange={e => setBoardLimit(Number(e.target.value || 180))} />
            </div>
            <div className="form-group">
              <button className="btn-professional btn-primary" onClick={fetchBoardSummary}>Apply</button>
            </div>
          </div>

          {boardLoading ? <LoadingPlaceholder text="Loading board dates…" />
            : boardError ? <ErrorPlaceholder msg={boardError} onRetry={fetchBoardSummary} />
            : (
              <>
                {/* Selection toolbar */}
                <div className="d-flex flex-wrap gap-2 mb-3" style={{ alignItems: 'center' }}>
                  <button className="btn-professional btn-secondary" onClick={selectPageDates}>Select Page</button>
                  <button className="btn-professional btn-secondary" onClick={clearSelection} disabled={!selectedDates.length}>Clear ({selectedDates.length})</button>
                  <button className="btn-professional btn-primary" onClick={fetchDistribution} disabled={!selectedDates.length || distLoading}>
                    {distLoading ? 'Analyzing…' : 'Analyse Selected'}
                  </button>
                  {selectedDates.length > 0 && (
                    <span style={{ fontSize: '0.82rem', color: 'var(--gray-600)' }}>{selectedDates.length} date{selectedDates.length > 1 ? 's' : ''} selected</span>
                  )}
                </div>

                <div style={{ maxHeight: 400, overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                  <table className="table-professional" style={{ margin: 0 }}>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--gray-50)', zIndex: 10 }}>
                      <tr>
                        <th style={{ width: 40 }}></th>
                        <th>Board Date</th>
                        <th>Cases</th>
                        <th>Respondent Lawyers</th>
                        <th>Petitioner Lawyers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginate(boardSummary.rows || [], boardPage).map(row => {
                        const sel = selectedDates.includes(row.board_date);
                        return (
                          <tr key={row.board_date} onClick={() => toggleDate(row.board_date)} style={{ cursor: 'pointer', background: sel ? 'rgba(37,99,235,0.07)' : undefined }}>
                            <td><input type="checkbox" checked={sel} onChange={() => toggleDate(row.board_date)} onClick={e => e.stopPropagation()} /></td>
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
                {(boardSummary.rows || []).length > ITEMS_PER_PAGE && (
                  <Paginator current={boardPage} total={totalPages((boardSummary.rows || []).length)} onChange={setBoardPage} />
                )}
              </>
            )}

          {/* AGP distribution for selected dates */}
          {distError && <p style={{ color: 'var(--error-color)', marginTop: '0.75rem' }}>{distError}</p>}
          {(distribution.distribution || []).length > 0 && (
            <div style={{ marginTop: '1.5rem', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div>
                <h6 style={{ marginBottom: '0.5rem' }}>AGP Allocation — {distribution.total_cases} cases across {(distribution.selected_dates || []).length} date{(distribution.selected_dates || []).length !== 1 ? 's' : ''}</h6>
                <div style={{ height: 300, position: 'relative' }}>
                  <Bar data={distChartData} options={{ ...chartOptions, indexAxis: 'y' }} />
                </div>
              </div>
              <div>
                <h6 style={{ marginBottom: '0.5rem' }}>Distribution Table</h6>
                <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                  <table className="table-professional" style={{ margin: 0 }}>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--gray-50)' }}>
                      <tr><th>Government Pleader</th><th>Cases</th><th>Share</th></tr>
                    </thead>
                    <tbody>
                      {(distribution.distribution || []).map(r => (
                        <tr key={r.agp_name}><td>{r.agp_name}</td><td><strong>{r.matters}</strong></td><td>{r.percentage}%</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Cases for selected dates */}
          {selectedDates.length > 0 && (
            <div style={{ marginTop: '1.5rem' }}>
              <h6 style={{ marginBottom: '0.5rem' }}>Cases for Selected Board Dates</h6>
              {dateCasesLoading ? <LoadingPlaceholder text="Loading cases…" />
                : dateCasesError ? <p style={{ color: 'var(--error-color)' }}>{dateCasesError}</p>
                : (
                  <>
                    <div className="d-flex flex-wrap gap-2 mb-2" style={{ alignItems: 'center' }}>
                      <button className="btn-professional btn-secondary" onClick={() => setSelectedCaseRefs(dateCases.map(c => c.case_ref))}>Select All</button>
                      <button className="btn-professional btn-secondary" onClick={() => setSelectedCaseRefs([])}>Clear</button>
                      <span style={{ fontSize: '0.82rem', color: 'var(--gray-600)' }}>{dateCases.length} cases · {selectedCaseRefs.length} selected</span>
                    </div>
                    <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                      <table className="table-professional" style={{ margin: 0 }}>
                        <thead style={{ position: 'sticky', top: 0, background: 'var(--gray-50)', zIndex: 10 }}>
                          <tr><th style={{ width: 40 }}></th><th>Date</th><th>Case Ref</th><th>Respondent Lawyer</th><th>Petitioner Lawyer</th></tr>
                        </thead>
                        <tbody>
                          {dateCases.map(item => {
                            const sel = selectedCaseRefs.includes(item.case_ref);
                            return (
                              <tr key={`${item.case_id}-${item.case_ref}`} onClick={() => toggleCase(item.case_ref)} style={{ cursor: 'pointer', background: sel ? 'rgba(16,185,129,0.07)' : undefined }}>
                                <td><input type="checkbox" checked={sel} onChange={() => toggleCase(item.case_ref)} onClick={e => e.stopPropagation()} /></td>
                                <td>{item.board_date}</td>
                                <td><strong>{item.case_ref}</strong></td>
                                <td>{item.respondent_lawyer || '—'}</td>
                                <td>{item.petitioner_lawyer || '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
            </div>
          )}
        </SectionCard>
      </div>

      {/* ── 3. Matters over time ── */}
      <div className="dashboard-section">
        <SectionCard title="Matters Over Time">
          <div className="d-flex flex-wrap gap-3 mb-4" style={{ alignItems: 'flex-end' }}>
            <div className="form-group" style={{ minWidth: 150 }}>
              <label className="form-label">From</label>
              <input type="date" className="form-control" value={dateRange.start} onChange={e => setDateRange(p => ({ ...p, start: e.target.value }))} />
            </div>
            <div className="form-group" style={{ minWidth: 150 }}>
              <label className="form-label">To</label>
              <input type="date" className="form-control" value={dateRange.end} onChange={e => setDateRange(p => ({ ...p, end: e.target.value }))} />
            </div>
            <div className="form-group">
              <button className="btn-professional btn-primary" onClick={fetchMatters}>Refresh</button>
            </div>
          </div>

          {mattersLoading ? <LoadingPlaceholder text="Loading matters data…" />
            : mattersError ? <ErrorPlaceholder msg={mattersError} onRetry={fetchMatters} />
            : mattersByDate.data.length === 0 ? <p style={{ color: 'var(--gray-500)' }}>No data for selected range.</p>
            : (
              <>
                <div className="row g-3 mb-4">
                  <div className="col-4"><StatCard value={mattersByDate.summary.total_matters || 0} label="Total Matters" color="var(--primary-color)" /></div>
                  <div className="col-4"><StatCard value={mattersByDate.summary.average_per_day || 0} label="Daily Average" color="var(--secondary-color)" /></div>
                  <div className="col-4"><StatCard value={mattersByDate.summary.days_covered || 0} label="Days Covered" color="var(--accent-color)" /></div>
                </div>
                <div style={{ height: 360 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={mattersByDate.data}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={70} />
                      <YAxis />
                      <RechartsTooltip formatter={(v, n) => [n === 'total_matters' ? `${v} matters` : `${v} avg`, n === 'total_matters' ? 'Total' : 'Average']} labelFormatter={l => `Date: ${l}`} />
                      <RechartsLegend />
                      <RechartsBar dataKey="total_matters" fill="#3b82f6" name="Total Matters" opacity={0.8} />
                      <RechartsLine type="monotone" dataKey="average" stroke="#ef4444" strokeWidth={2} name="Daily Average" dot={{ fill: '#ef4444', r: 3 }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
        </SectionCard>
      </div>

      {/* ── 4. AGP Statistics ── */}
      <div className="dashboard-section">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
          <SectionCard title={`AGP Statistics (${agpStats.length} records)`}>
            <div className="d-flex flex-wrap gap-3 mb-4" style={{ alignItems: 'flex-end' }}>
              <div className="form-group" style={{ minWidth: 180 }}>
                <label className="form-label">Filter by name</label>
                <input type="text" className="form-control" placeholder="Enter AGP name" value={agpName} onChange={e => setAgpName(e.target.value)} />
              </div>
              <div className="form-group"><button className="btn-professional btn-primary" onClick={fetchAgpStats}>Refresh</button></div>
            </div>
            {agpLoading ? <LoadingPlaceholder />
              : agpError ? <ErrorPlaceholder msg={agpError} onRetry={fetchAgpStats} />
              : agpStats.length === 0 ? <p style={{ color: 'var(--gray-500)' }}>No data.</p>
              : (
                <>
                  <div style={{ maxHeight: 380, overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                    <table className="table-professional" style={{ margin: 0 }}>
                      <thead style={{ position: 'sticky', top: 0, background: 'var(--gray-50)', zIndex: 10 }}>
                        <tr><th>AGP Name</th><th>Total Matters</th></tr>
                      </thead>
                      <tbody>
                        {paginate(agpStats, agpPage).map((r, i) => (
                          <tr key={i}><td>{r.agp_name}</td><td><strong>{r.matters}</strong></td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {agpStats.length > ITEMS_PER_PAGE && <Paginator current={agpPage} total={totalPages(agpStats.length)} onChange={setAgpPage} />}
                </>
              )}
          </SectionCard>

          <SectionCard title="AGP Distribution">
            {agpLoading ? <LoadingPlaceholder />
              : agpStats.length === 0 ? <p style={{ color: 'var(--gray-500)' }}>No data.</p>
              : <div style={{ height: 380, position: 'relative' }}><Doughnut data={agpDoughnutData} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => { const tot = ctx.dataset.data.reduce((a, b) => a + b, 0); return `${ctx.label}: ${ctx.parsed} (${((ctx.parsed / tot) * 100).toFixed(1)}%)`; } } } } }} /></div>}
          </SectionCard>
        </div>

        {!agpLoading && agpStats.length > 0 && (
          <SectionCard title="Top 10 AGPs by Case Load">
            <div style={{ height: 280, position: 'relative' }}><Bar data={agpChartData} options={chartOptions} /></div>
          </SectionCard>
        )}
      </div>

      {/* ── 5. Monthly Averages ── */}
      <div className="dashboard-section">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
          <SectionCard title={`Monthly Average Matters (${monthlyAvg.length} AGPs)`}>
            <div className="d-flex flex-wrap gap-3 mb-4" style={{ alignItems: 'flex-end' }}>
              <div className="form-group" style={{ minWidth: 130 }}>
                <label className="form-label">Year</label>
                <input type="number" className="form-control" value={year} min="2000" max={currentYear} onChange={e => setYear(e.target.value)} />
              </div>
              <div className="form-group"><button className="btn-professional btn-primary" onClick={fetchMonthlyAvg}>Refresh</button></div>
            </div>
            {monthlyLoading ? <LoadingPlaceholder />
              : monthlyError ? <ErrorPlaceholder msg={monthlyError} onRetry={fetchMonthlyAvg} />
              : monthlyAvg.length === 0 ? <p style={{ color: 'var(--gray-500)' }}>No data for {year}.</p>
              : (
                <>
                  <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
                    <table className="table-professional" style={{ margin: 0 }}>
                      <thead style={{ position: 'sticky', top: 0, background: 'var(--gray-50)', zIndex: 10 }}>
                        <tr><th>AGP Name</th><th>Monthly Avg</th></tr>
                      </thead>
                      <tbody>
                        {paginate(monthlyAvg, monthlyPage).map((r, i) => (
                          <tr key={i}><td>{r.agp_name}</td><td><strong>{r.monthly_avg}</strong> / month</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {monthlyAvg.length > ITEMS_PER_PAGE && <Paginator current={monthlyPage} total={totalPages(monthlyAvg.length)} onChange={setMonthlyPage} />}
                </>
              )}
          </SectionCard>

          <SectionCard title="Top 10 Monthly Averages">
            {monthlyLoading ? <LoadingPlaceholder />
              : monthlyAvg.length === 0 ? <p style={{ color: 'var(--gray-500)' }}>No data.</p>
              : <div style={{ height: 380, position: 'relative' }}><Bar data={monthlyChartData} options={chartOptions} /></div>}
          </SectionCard>
        </div>
      </div>

      {/* ── 6. Admin / Pipeline Operations (collapsible) ── */}
      <div className="dashboard-section">
        <div style={{ border: '1px solid var(--gray-200)', borderRadius: 'var(--radius-md)' }}>
          <button
            onClick={() => setShowAdmin(v => !v)}
            style={{ width: '100%', textAlign: 'left', padding: '0.85rem 1.25rem', background: 'var(--gray-50)', border: 'none', borderRadius: showAdmin ? 'var(--radius-md) var(--radius-md) 0 0' : 'var(--radius-md)', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontWeight: 600, color: 'var(--gray-700)' }}
          >
            <span>
              System Administration &amp; Pipeline Controls
              {workersStalled && <span style={{ marginLeft: '0.75rem', fontSize: '0.78rem', fontWeight: 400, color: 'var(--error-color)' }}>⚠ Workers stalled</span>}
              {!pipelineOk && !workersStalled && totalQueued > 0 && <span style={{ marginLeft: '0.75rem', fontSize: '0.78rem', fontWeight: 400, color: 'var(--warning-color, #f59e0b)' }}>{totalQueued} in queue</span>}
            </span>
            <span style={{ fontSize: '0.9rem' }}>{showAdmin ? '▲' : '▼'}</span>
          </button>

          {showAdmin && (
            <div style={{ padding: '1.25rem', borderTop: '1px solid var(--gray-200)' }}>
              {/* Pipeline health alert */}
              {(!pipelineOk || workersStalled) && (
                <div style={{ marginBottom: '1rem', padding: '0.85rem 1rem', background: workersStalled ? 'rgba(239,68,68,0.06)' : 'rgba(245,158,11,0.07)', border: `1px solid ${workersStalled ? 'var(--error-color)' : 'var(--warning-color, #f59e0b)'}`, borderRadius: 'var(--radius-sm)' }}>
                  <div className="d-flex flex-wrap gap-3 align-items-center justify-content-between">
                    <strong style={{ fontSize: '0.9rem' }}>{workersStalled ? 'Fetch workers have stalled — orders stuck in queue' : 'Pipeline activity'}</strong>
                    <div className="d-flex flex-wrap gap-3" style={{ fontSize: '0.83rem' }}>
                      {(queueStatus.fetch_queue_size || 0) > 0 && <span><span className="badge bg-primary me-1">{queueStatus.fetch_queue_size}</span>Fetch queued</span>}
                      {(queueStatus.analysis_queue_size || 0) > 0 && <span><span className="badge bg-info me-1">{queueStatus.analysis_queue_size}</span>Analysis queued</span>}
                    </div>
                    {workersStalled && (
                      <button className="btn-professional btn-primary" style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem' }} onClick={restartWorkers} disabled={jobLoading === 'restart'}>
                        {jobLoading === 'restart' ? 'Restarting…' : 'Restart Workers'}
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Queue stats */}
              {queueLoading ? <LoadingPlaceholder text="Loading queue status…" />
                : queueError ? <ErrorPlaceholder msg={queueError} onRetry={fetchQueueStatus} />
                : (
                  <>
                    <div className="row g-3 mb-4">
                      {[
                        { v: queueStatus.fetch_queue_size || 0, l: 'Fetch Queue', c: 'var(--primary-color)' },
                        { v: queueStatus.analysis_queue_size || 0, l: 'Analysis Queue', c: 'var(--secondary-color)' },
                        { v: queueStatus.fetch_processing_active ? 'Active' : 'Off', l: 'Fetch Workers', c: queueStatus.fetch_processing_active ? 'var(--success-color)' : 'var(--gray-500)' },
                        { v: queueStatus.analysis_processing_active ? 'Active' : 'Off', l: 'Analysis Workers', c: queueStatus.analysis_processing_active ? 'var(--success-color)' : 'var(--gray-500)' },
                      ].map(({ v, l, c }) => (
                        <div key={l} className="col-6 col-md-3"><StatCard value={v} label={l} color={c} /></div>
                      ))}
                    </div>

                    {queueStatus.message && <p style={{ color: 'var(--gray-600)', marginBottom: '1rem', fontSize: '0.875rem' }}>{queueStatus.message}</p>}

                    <div className="d-flex flex-wrap gap-2 mb-2">
                      <button className="btn-professional btn-primary" onClick={queueFetch} disabled={jobLoading === 'fetch'}>{jobLoading === 'fetch' ? 'Queueing…' : 'Queue Fetch Jobs'}</button>
                      <button className="btn-professional btn-primary" onClick={queueAnalysis} disabled={jobLoading === 'analysis'}>{jobLoading === 'analysis' ? 'Queueing…' : 'Queue Analysis Jobs'}</button>
                      <button className="btn-professional btn-secondary" onClick={restartWorkers} disabled={jobLoading === 'restart'}>{jobLoading === 'restart' ? 'Restarting…' : 'Restart Workers'}</button>
                      <button className="btn-professional btn-secondary" onClick={fetchQueueStatus}>Refresh Status</button>
                    </div>

                    <p style={{ color: 'var(--gray-600)', fontSize: '0.83rem' }}>
                      {selectedCaseRefs.length
                        ? `Actions will target ${selectedCaseRefs.length} selected case${selectedCaseRefs.length > 1 ? 's' : ''}.`
                        : selectedDates.length
                        ? `Actions will target ${selectedDates.length} selected board date${selectedDates.length > 1 ? 's' : ''}.`
                        : 'Actions will target the active board filter.'}
                    </p>

                    {jobMessage && <p style={{ color: 'var(--success-color)', marginTop: '0.5rem' }}>{jobMessage}</p>}
                    {jobError   && <p style={{ color: 'var(--error-color)',   marginTop: '0.5rem' }}>{jobError}</p>}
                  </>
                )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
