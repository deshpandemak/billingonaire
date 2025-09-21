import React, { useEffect, useState } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import { Container } from 'react-bootstrap';
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
import { Bar, Line, Doughnut } from 'react-chartjs-2';
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
  PieChart,
  Pie,
  Cell
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
  const [weeklyStatus, setWeeklyStatus] = useState([]);
  const [agpStats, setAgpStats] = useState([]);
  const [monthlyAvg, setMonthlyAvg] = useState([]);
  const [year, setYear] = useState(new Date().getFullYear().toString());
  const [agpName, setAgpName] = useState('');
  const [weeklyRange, setWeeklyRange] = useState({
    start: '',
    end: ''
  });
  const [weeklyLoading, setWeeklyLoading] = useState(true);
  const [agpLoading, setAgpLoading] = useState(true);
  const [monthlyLoading, setMonthlyLoading] = useState(true);
  const [weeklyError, setWeeklyError] = useState('');
  const [agpError, setAgpError] = useState('');
  const [monthlyError, setMonthlyError] = useState('');
  const [agpCurrentPage, setAgpCurrentPage] = useState(0);
  const [monthlyCurrentPage, setMonthlyCurrentPage] = useState(0);
  const ITEMS_PER_PAGE = 20;

  // New analytics state
  const [mattersByDateRange, setMattersByDateRange] = useState({ data: [], summary: {} });
  const [agpDistribution, setAgpDistribution] = useState({
    weekly: { distribution: [], total_matters: 0, period_type: 'weekly' },
    monthly: { distribution: [], total_matters: 0, period_type: 'monthly' },
    yearly: { distribution: [], total_matters: 0, period_type: 'yearly' }
  });
  const [analyticsLoading, setAnalyticsLoading] = useState({
    matters: true,
    weekly: true,
    monthly: true,
    yearly: true
  });
  const [analyticsError, setAnalyticsError] = useState({
    matters: '',
    weekly: '',
    monthly: '',
    yearly: ''
  });
  const [dateRange, setDateRange] = useState({
    start: '',
    end: ''
  });

  // Independent loading for each widget
  useEffect(() => {
    fetchWeeklyStatus();
  }, [weeklyRange.start, weeklyRange.end]);

  useEffect(() => {
    fetchAgpStats();
  }, [agpName]);

  useEffect(() => {
    fetchMonthlyAvg();
  }, [year]);

  // Fetch new analytics data on component mount and when date range changes
  useEffect(() => {
    fetchMattersByDateRange();
  }, [dateRange.start, dateRange.end]);

  useEffect(() => {
    fetchAgpDistribution();
  }, []);

  // Fetch weekly board status with independent loading
  const fetchWeeklyStatus = async () => {
    setWeeklyLoading(true);
    setWeeklyError('');
    let url = `/dashboard/weekly-status`;
    const params = [];
    if (weeklyRange.start) params.push(`start_date=${weeklyRange.start}`);
    if (weeklyRange.end) params.push(`end_date=${weeklyRange.end}`);
    if (params.length) url += `?${params.join('&')}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setWeeklyStatus(data);
    } catch (e) {
      console.error('Failed to fetch weekly status:', e);
      setWeeklyError('Failed to load weekly status');
      setWeeklyStatus([]);
    } finally {
      setWeeklyLoading(false);
    }
  };

  // Fetch AGP wise data with independent loading
  const fetchAgpStats = async () => {
    setAgpLoading(true);
    setAgpError('');
    setAgpCurrentPage(0); // Reset pagination on new data
    let url = `/dashboard/agp-stats`;
    if (agpName) url += `?agp_name=${encodeURIComponent(agpName)}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setAgpStats(data);
    } catch (e) {
      console.error('Failed to fetch AGP stats:', e);
      setAgpError('Failed to load AGP statistics');
      setAgpStats([]);
    } finally {
      setAgpLoading(false);
    }
  };

  // Fetch monthly average matters per AGP with independent loading
  const fetchMonthlyAvg = async () => {
    setMonthlyLoading(true);
    setMonthlyError('');
    setMonthlyCurrentPage(0); // Reset pagination on new data
    let url = `/dashboard/monthly-avg`;
    if (year) url += `?year=${year}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setMonthlyAvg(data);
    } catch (e) {
      console.error('Failed to fetch monthly avg:', e);
      setMonthlyError('Failed to load monthly averages');
      setMonthlyAvg([]);
    } finally {
      setMonthlyLoading(false);
    }
  };

  // New analytics fetch functions
  const fetchMattersByDateRange = async () => {
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
      console.error('Failed to fetch matters by date range:', e);
      setAnalyticsError(prev => ({ ...prev, matters: 'Failed to load matters data' }));
      setMattersByDateRange({ data: [], summary: {} });
    } finally {
      setAnalyticsLoading(prev => ({ ...prev, matters: false }));
    }
  };

  const fetchAgpDistribution = async () => {
    // Fetch all three distribution types in parallel
    const endpoints = [
      { key: 'weekly', url: '/dashboard/agp-distribution-weekly' },
      { key: 'monthly', url: '/dashboard/agp-distribution-monthly' },
      { key: 'yearly', url: '/dashboard/agp-distribution-yearly' }
    ];

    // Set all loading states
    setAnalyticsLoading(prev => ({
      ...prev,
      weekly: true,
      monthly: true,
      yearly: true
    }));

    // Clear all errors
    setAnalyticsError(prev => ({
      ...prev,
      weekly: '',
      monthly: '',
      yearly: ''
    }));

    // Fetch all endpoints
    for (const endpoint of endpoints) {
      try {
        const data = await authenticatedFetchJSON(endpoint.url);
        setAgpDistribution(prev => ({
          ...prev,
          [endpoint.key]: data
        }));
      } catch (e) {
        console.error(`Failed to fetch ${endpoint.key} AGP distribution:`, e);
        setAnalyticsError(prev => ({ 
          ...prev, 
          [endpoint.key]: `Failed to load ${endpoint.key} distribution` 
        }));
        setAgpDistribution(prev => ({
          ...prev,
          [endpoint.key]: { distribution: [], total_matters: 0, period_type: endpoint.key }
        }));
      } finally {
        setAnalyticsLoading(prev => ({ ...prev, [endpoint.key]: false }));
      }
    }
  };

  // Helper function for pagination
  const getPaginatedData = (data, currentPage) => {
    const startIndex = currentPage * ITEMS_PER_PAGE;
    const endIndex = startIndex + ITEMS_PER_PAGE;
    return data.slice(startIndex, endIndex);
  };

  const getTotalPages = (dataLength) => {
    return Math.ceil(dataLength / ITEMS_PER_PAGE);
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

  // Color palette for AGP distribution charts
  const COLORS = [
    '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
    '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'
  ];

  // AGP Distribution chart components
  const renderAgpDistributionChart = (distributionData, title, periodType) => {
    if (!distributionData || !distributionData.distribution || distributionData.distribution.length === 0) {
      return (
        <div className="text-center p-4">
          <p style={{ color: 'var(--gray-500)' }}>No data available for {periodType} distribution</p>
        </div>
      );
    }

    const data = distributionData.distribution.slice(0, 8); // Top 8 for readability

    return (
      <div style={{ height: '300px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={100}
              paddingAngle={2}
              dataKey="matters"
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <RechartsTooltip 
              formatter={(value, name, props) => [
                `${value} matters (${props.payload.percentage}%)`,
                'Cases'
              ]}
              labelFormatter={(label) => `AGP: ${label}`}
            />
            <RechartsLegend 
              formatter={(value) => value.length > 20 ? value.substring(0, 20) + '...' : value}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Legal Practice Dashboard</h1>
        <p className="dashboard-subtitle">
          Monitor your court matters, AGP statistics, and practice performance
        </p>
      </div>

      {/* NEW ANALYTICS SECTION - Total Matters by Date Range with Average */}
      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📊 Total Matters by Date Range (Last 5 Days Default)</h2>
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

      {/* NEW ANALYTICS SECTION - AGP Distribution by Time Periods */}
      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">🎯 AGP Distribution by Time Periods</h2>
          </div>
          <div className="card-body">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--spacing-xl)' }}>
              
              {/* Weekly Distribution */}
              <div className="chart-container">
                <h4 style={{ textAlign: 'center', marginBottom: 'var(--spacing-md)', color: 'var(--primary-color)' }}>
                  📅 Weekly (Monday to Date)
                </h4>
                {analyticsLoading.weekly ? (
                  <div className="text-center p-4">
                    <div className="loading-text">
                      <span className="loading"></span>
                      Loading...
                    </div>
                  </div>
                ) : analyticsError.weekly ? (
                  <div className="text-center p-4">
                    <p style={{ color: 'var(--error-color)', fontSize: '0.9rem' }}>{analyticsError.weekly}</p>
                  </div>
                ) : (
                  <>
                    <div className="text-center mb-3">
                      <h5 style={{ color: 'var(--secondary-color)' }}>
                        {agpDistribution.weekly.total_matters} Total Matters
                      </h5>
                      <small style={{ color: 'var(--gray-500)' }}>
                        {agpDistribution.weekly.date_range?.start} to {agpDistribution.weekly.date_range?.end}
                      </small>
                    </div>
                    {renderAgpDistributionChart(agpDistribution.weekly, 'Weekly Distribution', 'weekly')}
                  </>
                )}
              </div>

              {/* Monthly Distribution */}
              <div className="chart-container">
                <h4 style={{ textAlign: 'center', marginBottom: 'var(--spacing-md)', color: 'var(--primary-color)' }}>
                  📆 Monthly (Month to Date)
                </h4>
                {analyticsLoading.monthly ? (
                  <div className="text-center p-4">
                    <div className="loading-text">
                      <span className="loading"></span>
                      Loading...
                    </div>
                  </div>
                ) : analyticsError.monthly ? (
                  <div className="text-center p-4">
                    <p style={{ color: 'var(--error-color)', fontSize: '0.9rem' }}>{analyticsError.monthly}</p>
                  </div>
                ) : (
                  <>
                    <div className="text-center mb-3">
                      <h5 style={{ color: 'var(--secondary-color)' }}>
                        {agpDistribution.monthly.total_matters} Total Matters
                      </h5>
                      <small style={{ color: 'var(--gray-500)' }}>
                        {agpDistribution.monthly.date_range?.start} to {agpDistribution.monthly.date_range?.end}
                      </small>
                    </div>
                    {renderAgpDistributionChart(agpDistribution.monthly, 'Monthly Distribution', 'monthly')}
                  </>
                )}
              </div>

              {/* Yearly Distribution */}
              <div className="chart-container">
                <h4 style={{ textAlign: 'center', marginBottom: 'var(--spacing-md)', color: 'var(--primary-color)' }}>
                  📅 Yearly (Year to Date)
                </h4>
                {analyticsLoading.yearly ? (
                  <div className="text-center p-4">
                    <div className="loading-text">
                      <span className="loading"></span>
                      Loading...
                    </div>
                  </div>
                ) : analyticsError.yearly ? (
                  <div className="text-center p-4">
                    <p style={{ color: 'var(--error-color)', fontSize: '0.9rem' }}>{analyticsError.yearly}</p>
                  </div>
                ) : (
                  <>
                    <div className="text-center mb-3">
                      <h5 style={{ color: 'var(--secondary-color)' }}>
                        {agpDistribution.yearly.total_matters} Total Matters
                      </h5>
                      <small style={{ color: 'var(--gray-500)' }}>
                        {agpDistribution.yearly.date_range?.start} to {agpDistribution.yearly.date_range?.end}
                      </small>
                    </div>
                    {renderAgpDistributionChart(agpDistribution.yearly, 'Yearly Distribution', 'yearly')}
                  </>
                )}
              </div>

            </div>
          </div>
        </div>
      </div>

      {/* Weekly Board Status Section */}
          <div className="dashboard-section">
            <div className="card-professional">
              <div className="card-header">
                <h2 className="section-title">📅 Weekly Board Status</h2>
              </div>
              <div className="card-body">
                <div className="d-flex flex-wrap gap-3 mb-4">
                  <div className="form-group" style={{ minWidth: '150px' }}>
                    <label className="form-label">Start Date</label>
                    <input 
                      type="date" 
                      className="form-control"
                      value={weeklyRange.start} 
                      onChange={e => setWeeklyRange(r => ({ ...r, start: e.target.value }))} 
                    />
                  </div>
                  <div className="form-group" style={{ minWidth: '150px' }}>
                    <label className="form-label">End Date</label>
                    <input 
                      type="date" 
                      className="form-control"
                      value={weeklyRange.end} 
                      onChange={e => setWeeklyRange(r => ({ ...r, end: e.target.value }))} 
                    />
                  </div>
                  <div className="form-group d-flex align-items-end">
                    <button 
                      className="btn-professional btn-primary"
                      onClick={fetchWeeklyStatus}
                    >
                      Refresh Data
                    </button>
                  </div>
                </div>
                
                {weeklyLoading ? (
                  <div className="text-center p-4">
                    <div className="loading-text">
                      <span className="loading"></span>
                      Loading weekly status...
                    </div>
                  </div>
                ) : weeklyError ? (
                  <div className="text-center p-4">
                    <p style={{ color: 'var(--error-color)' }}>{weeklyError}</p>
                    <button className="btn-professional btn-primary" onClick={fetchWeeklyStatus}>
                      Retry
                    </button>
                  </div>
                ) : weeklyStatus.length === 0 ? (
                  <div className="text-center p-4">
                    <p style={{ color: 'var(--gray-500)' }}>No data available for the selected date range</p>
                  </div>
                ) : (
                  <table className="table-professional">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Total Matters</th>
                      </tr>
                    </thead>
                    <tbody>
                      {weeklyStatus.map((row, i) => (
                        <tr key={i}>
                          <td>{new Date(row.date).toLocaleDateString()}</td>
                          <td><strong>{row.total_matters}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
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
                  <h2 className="section-title">👤 AGP Statistics ({agpStats.length} records)</h2>
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
                            ← Previous
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
                            Next →
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
                  <h2 className="section-title">📊 AGP Distribution</h2>
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
                  <h2 className="section-title">📈 Top 10 AGPs by Case Load</h2>
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
                  <h2 className="section-title">📈 Monthly Average Matters per AGP ({monthlyAvg.length} records)</h2>
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
                            ← Previous
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
                            Next →
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
                  <h2 className="section-title">📊 Top 10 Monthly Averages</h2>
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