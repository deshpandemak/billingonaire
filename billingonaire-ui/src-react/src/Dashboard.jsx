import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from './config';
import Header from './Header';
import { Container } from 'react-bootstrap';

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

  useEffect(() => {
    fetchWeeklyStatus();
    fetchAgpStats();
    fetchMonthlyAvg();
  }, [year, agpName, weeklyRange]);

  // Fetch weekly board status
  const fetchWeeklyStatus = async () => {
    let url = `${API_BASE_URL}/dashboard/weekly-status`;
    const params = [];
    if (weeklyRange.start) params.push(`start_date=${weeklyRange.start}`);
    if (weeklyRange.end) params.push(`end_date=${weeklyRange.end}`);
    if (params.length) url += `?${params.join('&')}`;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch weekly status');
      setWeeklyStatus(await response.json());
    } catch (e) {
      setWeeklyStatus([]);
    }
  };

  // Fetch AGP wise data
  const fetchAgpStats = async () => {
    let url = `${API_BASE_URL}/dashboard/agp-stats`;
    if (agpName) url += `?agp_name=${encodeURIComponent(agpName)}`;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch AGP stats');
      setAgpStats(await response.json());
    } catch (e) {
      setAgpStats([]);
    }
  };

  // Fetch monthly average matters per AGP
  const fetchMonthlyAvg = async () => {
    let url = `${API_BASE_URL}/dashboard/monthly-avg`;
    if (year) url += `?year=${year}`;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch monthly avg');
      setMonthlyAvg(await response.json());
    } catch (e) {
      setMonthlyAvg([]);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header />
      <Container fluid className="flex-grow-1 d-flex flex-column p-0">
        <div className="dashboard-container">
          <h1>Dashboard</h1>
          <div className="dashboard-section">
            <h2>Weekly Board Status</h2>
            <div style={{ marginBottom: '1rem' }}>
              <label>Start Date: <input type="date" value={weeklyRange.start} onChange={e => setWeeklyRange(r => ({ ...r, start: e.target.value }))} /></label>
              <label style={{ marginLeft: '1rem' }}>End Date: <input type="date" value={weeklyRange.end} onChange={e => setWeeklyRange(r => ({ ...r, end: e.target.value }))} /></label>
              <button style={{ marginLeft: '1rem' }} onClick={fetchWeeklyStatus}>Refresh</button>
            </div>
            {weeklyStatus.length === 0 ? (
              <div style={{color:'#888',padding:'1rem'}}>Fetching data...</div>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Total Matters</th>
                </tr>
              </thead>
              <tbody>
                {weeklyStatus.map((row, i) => (
                  <tr key={i}>
                    <td>{row.date}</td>
                    <td>{row.total_matters}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
          <div className="dashboard-section">
            <h2>AGP Wise Data</h2>
            <div style={{ marginBottom: '1rem' }}>
              <label>AGP Name: <input type="text" value={agpName} onChange={e => setAgpName(e.target.value)} /></label>
              <button style={{ marginLeft: '1rem' }} onClick={fetchAgpStats}>Refresh</button>
            </div>
            {agpStats.length === 0 ? (
              <div style={{color:'#888',padding:'1rem'}}>Fetching data...</div>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>AGP Name</th>
                  <th>Matters</th>
                </tr>
              </thead>
              <tbody>
                {agpStats.map((row, i) => (
                  <tr key={i}>
                    <td>{row.agp_name}</td>
                    <td>{row.matters}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
          <div className="dashboard-section">
            <h2>Monthly Avg Matters per AGP</h2>
            <div style={{ marginBottom: '1rem' }}>
              <label>Year: <input type="number" value={year} onChange={e => setYear(e.target.value)} min="2000" max={new Date().getFullYear()} /></label>
              <button style={{ marginLeft: '1rem' }} onClick={fetchMonthlyAvg}>Refresh</button>
            </div>
            {monthlyAvg.length === 0 ? (
              <div style={{color:'#888',padding:'1rem'}}>Fetching data...</div>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>AGP Name</th>
                  <th>Monthly Avg</th>
                </tr>
              </thead>
              <tbody>
                {monthlyAvg.map((row, i) => (
                  <tr key={i}>
                    <td>{row.agp_name}</td>
                    <td>{row.monthly_avg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
        </div>
      </Container>
      <footer className="bg-light text-center text-muted py-3 mt-auto border-top w-100">
        &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
      </footer>
    </div>
  );
};

export default Dashboard;
