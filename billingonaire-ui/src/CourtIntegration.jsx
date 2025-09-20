import React, { useState } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const CourtIntegration = () => {
  const [caseRef, setCaseRef] = useState('');
  const [date, setDate] = useState('');
  const [bench, setBench] = useState('mumbai');
  const [caseDetails, setCaseDetails] = useState(null);
  const [caseOrders, setCaseOrders] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleGetCaseDetails = async () => {
    if (!caseRef.trim()) {
      setError('Please enter a case reference (e.g., WP/294/2025)');
      return;
    }

    setLoading(true);
    setError(null);
    setCaseDetails(null);

    try {
      const params = new URLSearchParams({
        case_ref: caseRef.trim(),
        bench: bench
      });
      
      const result = await authenticatedFetchJSON(`/court/case-details?${params}`);
      setCaseDetails(result);
      console.log('📋 Case Details:', result);
    } catch (e) {
      console.error('Failed to fetch case details:', e);
      setError(`Failed to fetch case details: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleGetCaseOrders = async () => {
    if (!caseRef.trim()) {
      setError('Please enter a case reference (e.g., WP/294/2025)');
      return;
    }

    setLoading(true);
    setError(null);
    setCaseOrders(null);

    try {
      const params = new URLSearchParams({
        case_ref: caseRef.trim(),
        bench: bench
      });
      
      if (date.trim()) {
        params.append('date', date.trim());
      }
      
      const result = await authenticatedFetchJSON(`/court/case-orders?${params}`);
      setCaseOrders(result);
      console.log('📜 Case Orders:', result);
    } catch (e) {
      console.error('Failed to fetch case orders:', e);
      setError(`Failed to fetch case orders: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const formatCaseDetails = (details) => {
    if (!details) return null;

    if (details.status === 'captcha_required') {
      return (
        <div className="alert alert-warning">
          <h6>⚠️ Manual Verification Required</h6>
          <p>{details.message}</p>
          <p><strong>Case:</strong> {details.case_ref}</p>
          <p><strong>Instructions:</strong> {details.instructions}</p>
          <a 
            href={details.search_url} 
            target="_blank" 
            rel="noopener noreferrer"
            className="btn btn-outline-primary btn-sm"
          >
            🌐 Visit Court Website
          </a>
        </div>
      );
    }

    if (details.error) {
      return (
        <div className="alert alert-danger">
          <h6>❌ Error</h6>
          <p>{details.error}</p>
        </div>
      );
    }

    return (
      <div className="card">
        <div className="card-header">
          <h6>📋 Case Details: {details.case_ref}</h6>
        </div>
        <div className="card-body">
          {details.petitioner && (
            <p><strong>Petitioner:</strong> {details.petitioner}</p>
          )}
          {details.respondent && (
            <p><strong>Respondent:</strong> {details.respondent}</p>
          )}
          {details.case_status && (
            <p><strong>Status:</strong> {details.case_status}</p>
          )}
          {details.stage && (
            <p><strong>Stage:</strong> {details.stage}</p>
          )}
          {details.next_date && (
            <p><strong>Next Date:</strong> {details.next_date}</p>
          )}
        </div>
      </div>
    );
  };

  const formatCaseOrders = (ordersData) => {
    if (!ordersData) return null;

    const orders = ordersData.orders || [];
    
    return (
      <div className="card">
        <div className="card-header">
          <h6>📜 Case Orders: {ordersData.case_ref}</h6>
          {ordersData.date && <small>Date: {ordersData.date}</small>}
        </div>
        <div className="card-body">
          {orders.map((order, index) => (
            <div key={index} className="mb-3">
              {order.status === 'captcha_required' ? (
                <div className="alert alert-warning">
                  <p>{order.message}</p>
                  <p><strong>Instructions:</strong> {order.instructions}</p>
                </div>
              ) : order.error ? (
                <div className="alert alert-danger">
                  <p>{order.error}</p>
                </div>
              ) : (
                <div className="border p-3 rounded">
                  <p>{JSON.stringify(order, null, 2)}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="container-fluid mt-4">
      <div className="row">
        <div className="col-12">
          <div className="card">
            <div className="card-header">
              <h5>🏛️ Bombay High Court Integration</h5>
              <p className="text-muted mb-0">Fetch case details and orders from the court website</p>
            </div>
            <div className="card-body">
              {/* Input Form */}
              <div className="row mb-4">
                <div className="col-md-4">
                  <label className="form-label">Case Reference</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="e.g., WP/294/2025"
                    value={caseRef}
                    onChange={(e) => setCaseRef(e.target.value)}
                  />
                  <small className="text-muted">Format: CASE_TYPE/NUMBER/YEAR</small>
                </div>
                <div className="col-md-3">
                  <label className="form-label">Court Bench</label>
                  <select
                    className="form-select"
                    value={bench}
                    onChange={(e) => setBench(e.target.value)}
                  >
                    <option value="mumbai">Mumbai (Original Side)</option>
                    <option value="mumbai_appellate">Mumbai (Appellate Side)</option>
                    <option value="aurangabad">Aurangabad Bench</option>
                    <option value="nagpur">Nagpur Bench</option>
                    <option value="goa">Goa Bench</option>
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">Date (Optional)</label>
                  <input
                    type="date"
                    className="form-control"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                  <small className="text-muted">For case orders</small>
                </div>
                <div className="col-md-2">
                  <label className="form-label">&nbsp;</label>
                  <div className="d-flex flex-column gap-2">
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={handleGetCaseDetails}
                      disabled={loading}
                    >
                      {loading ? '⏳' : '📋'} Case Details
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={handleGetCaseOrders}
                      disabled={loading}
                    >
                      {loading ? '⏳' : '📜'} Case Orders
                    </button>
                  </div>
                </div>
              </div>

              {/* Error Display */}
              {error && (
                <div className="alert alert-danger">
                  {error}
                </div>
              )}

              {/* Loading */}
              {loading && (
                <div className="text-center py-4">
                  <div className="spinner-border text-primary" role="status">
                    <span className="visually-hidden">Loading...</span>
                  </div>
                  <p className="mt-2">Fetching court data...</p>
                </div>
              )}

              {/* Results */}
              <div className="row">
                {caseDetails && (
                  <div className="col-md-6 mb-3">
                    {formatCaseDetails(caseDetails)}
                  </div>
                )}
                {caseOrders && (
                  <div className="col-md-6 mb-3">
                    {formatCaseOrders(caseOrders)}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CourtIntegration;