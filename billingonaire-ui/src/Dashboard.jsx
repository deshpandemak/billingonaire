import React, { useEffect, useState } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import { Container } from 'react-bootstrap';
import './styles/professional.css';

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
            <div className="card-professional">
              <div className="card-header">
                <h2 className="section-title">👤 AGP Statistics</h2>
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
                  <table className="table-professional">
                    <thead>
                      <tr>
                        <th>AGP Name</th>
                        <th>Total Matters</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agpStats.map((row, i) => (
                        <tr key={i}>
                          <td>{row.agp_name}</td>
                          <td><strong>{row.matters}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Monthly Average Section */}
          <div className="dashboard-section">
            <div className="card-professional">
              <div className="card-header">
                <h2 className="section-title">📈 Monthly Average Matters per AGP</h2>
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
                  <table className="table-professional">
                    <thead>
                      <tr>
                        <th>AGP Name</th>
                        <th>Monthly Average</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monthlyAvg.map((row, i) => (
                        <tr key={i}>
                          <td>{row.agp_name}</td>
                          <td><strong>{row.monthly_avg}</strong> matters/month</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default Dashboard;