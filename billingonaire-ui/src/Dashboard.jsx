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
  const [loading, setLoading] = useState(true);
  const [agpCurrentPage, setAgpCurrentPage] = useState(0);
  const [monthlyCurrentPage, setMonthlyCurrentPage] = useState(0);
  const ITEMS_PER_PAGE = 20;

  useEffect(() => {
    loadDashboardData();
  }, [year, agpName, weeklyRange]);

  const loadDashboardData = async () => {
    setLoading(true);
    await Promise.all([
      fetchWeeklyStatus(),
      fetchAgpStats(),
      fetchMonthlyAvg()
    ]);
    setLoading(false);
  };

  // Fetch weekly board status
  const fetchWeeklyStatus = async () => {
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
      setWeeklyStatus([]);
    }
  };

  // Fetch AGP wise data
  const fetchAgpStats = async () => {
    let url = `/dashboard/agp-stats`;
    if (agpName) url += `?agp_name=${encodeURIComponent(agpName)}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setAgpStats(data);
    } catch (e) {
      console.error('Failed to fetch AGP stats:', e);
      setAgpStats([]);
    }
  };

  // Fetch monthly average matters per AGP
  const fetchMonthlyAvg = async () => {
    let url = `/dashboard/monthly-avg`;
    if (year) url += `?year=${year}`;
    try {
      const data = await authenticatedFetchJSON(url);
      setMonthlyAvg(data);
    } catch (e) {
      console.error('Failed to fetch monthly avg:', e);
      setMonthlyAvg([]);
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

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Legal Practice Dashboard</h1>
        <p className="dashboard-subtitle">
          Monitor your court matters, AGP statistics, and practice performance
        </p>
      </div>

      {loading ? (
        <div className="text-center" style={{ padding: '3rem' }}>
          <div className="loading-text">
            <span className="loading"></span>
            Loading dashboard data...
          </div>
        </div>
      ) : (
        <>
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
                
                {weeklyStatus.length === 0 ? (
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
                  
                  {agpStats.length === 0 ? (
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
                  {agpStats.length === 0 ? (
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
            {agpStats.length > 0 && (
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
                  
                  {monthlyAvg.length === 0 ? (
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
                  {monthlyAvg.length === 0 ? (
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
        </>
      )}
    </div>
  );
};

export default Dashboard;