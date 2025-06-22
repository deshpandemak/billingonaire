import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from './config';

const Dashboard = () => {
  const [weeklyStatus, setWeeklyStatus] = useState([]);
  const [agpStats, setAgpStats] = useState([]);
  const [monthlyAvg, setMonthlyAvg] = useState([]);

  useEffect(() => {
    fetchWeeklyStatus();
    fetchAgpStats();
    fetchMonthlyAvg();
  }, []);

  // Fetch weekly board status
  const fetchWeeklyStatus = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/dashboard/weekly-status`);
      if (!response.ok) throw new Error('Failed to fetch weekly status');
      setWeeklyStatus(await response.json());
    } catch (e) {
      setWeeklyStatus([]);
    }
  };

  // Fetch AGP wise data
  const fetchAgpStats = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/dashboard/agp-stats`);
      if (!response.ok) throw new Error('Failed to fetch AGP stats');
      setAgpStats(await response.json());
    } catch (e) {
      setAgpStats([]);
    }
  };

  // Fetch monthly average matters per AGP
  const fetchMonthlyAvg = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/dashboard/monthly-avg`);
      if (!response.ok) throw new Error('Failed to fetch monthly avg');
      setMonthlyAvg(await response.json());
    } catch (e) {
      setMonthlyAvg([]);
    }
  };

  return (
    <div className="dashboard-container">
      <h1>Dashboard</h1>
      <div className="dashboard-section">
        <h2>Weekly Board Status</h2>
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
      <style>{`
        .dashboard-container { max-width: 900px; margin: 0 auto; padding: 2rem; }
        .dashboard-section { margin-bottom: 2rem; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
        th { background: #f5f5f5; }
      `}</style>
    </div>
  );
};

export default Dashboard;
