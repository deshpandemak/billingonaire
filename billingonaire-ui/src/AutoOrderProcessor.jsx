import React, { useState, useEffect } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const AutoOrderProcessor = () => {
  const [processing, setProcessing] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [stats, setStats] = useState(null);

  // Processing filters
  const [processFilters, setProcessFilters] = useState({
    case_type: '',
    case_year: '',
    date_from: '',
    date_to: '',
    limit: 50
  });

  // Search filters
  const [searchFilters, setSearchFilters] = useState({
    petitioner_search: '',
    respondent_search: '',
    case_type: '',
    case_year: '',
    order_category: '',
    limit: 100
  });

  // Processing results
  const [processResults, setProcessResults] = useState(null);

  useEffect(() => {
    loadSearchIndexStats();
  }, []);

  const loadSearchIndexStats = async () => {
    try {
      const stats = await authenticatedFetchJSON('/auto-orders/search-index-stats');
      setStats(stats);
    } catch (e) {
      console.error('Failed to load search index stats:', e);
    }
  };

  const handleAutoProcessCases = async () => {
    setProcessing(true);
    setError(null);
    setSuccess(null);

    try {
      const filters = {};
      if (processFilters.case_type) filters.case_type = processFilters.case_type;
      if (processFilters.case_year) filters.case_year = processFilters.case_year;
      if (processFilters.date_from) filters.date_from = processFilters.date_from;
      if (processFilters.date_to) filters.date_to = processFilters.date_to;

      const result = await authenticatedFetchJSON('/auto-orders/process-cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: filters,
          limit: processFilters.limit
        })
      });

      if (result.success) {
        setProcessResults(result.results);
        setSuccess(`Processing completed! ${result.results.successful_downloads} downloads, ${result.results.successful_analyses} analyses successful.`);
        // Refresh stats after processing
        loadSearchIndexStats();
      } else {
        setError(result.error || 'Processing failed');
      }
    } catch (e) {
      console.error('Auto processing failed:', e);
      setError(`Auto processing failed: ${e.message}`);
    } finally {
      setProcessing(false);
    }
  };

  const handleSearchOrders = async () => {
    setSearchLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      
      if (searchFilters.petitioner_search) params.append('petitioner_search', searchFilters.petitioner_search);
      if (searchFilters.respondent_search) params.append('respondent_search', searchFilters.respondent_search);
      if (searchFilters.case_type) params.append('case_type', searchFilters.case_type);
      if (searchFilters.case_year) params.append('case_year', searchFilters.case_year);
      if (searchFilters.order_category) params.append('order_category', searchFilters.order_category);
      params.append('limit', searchFilters.limit.toString());

      const result = await authenticatedFetchJSON(`/auto-orders/search?${params}`);

      if (result.success) {
        setSearchResults(result.results);
      } else {
        setError(result.error || 'Search failed');
      }
    } catch (e) {
      console.error('Search failed:', e);
      setError(`Search failed: ${e.message}`);
    } finally {
      setSearchLoading(false);
    }
  };

  const _handleBulkProcess = async (caseIds) => {
    setProcessing(true);
    setError(null);

    try {
      const result = await authenticatedFetchJSON('/auto-orders/bulk-process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_ids: caseIds })
      });

      if (result.success) {
        setSuccess(`Bulk processing completed! ${result.results.successful} successful, ${result.results.failed} failed.`);
        loadSearchIndexStats();
      } else {
        setError(result.error || 'Bulk processing failed');
      }
    } catch (e) {
      console.error('Bulk processing failed:', e);
      setError(`Bulk processing failed: ${e.message}`);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="container-fluid mt-4">
      <div className="row">
        <div className="col-12">
          <div className="card">
            <div className="card-header">
              <h5>🤖 Auto Order Processing & Search</h5>
              <p className="text-muted mb-0">Automatically download, analyze, and search court orders</p>
            </div>
            <div className="card-body">

              {/* Statistics */}
              {stats && (
                <div className="row mb-4">
                  <div className="col-md-12">
                    <div className="alert alert-info">
                      <h6>📊 Search Index Statistics</h6>
                      <div className="row">
                        <div className="col-md-3">
                          <strong>Total Indexed Orders:</strong> {stats.total_indexed_orders}
                        </div>
                        <div className="col-md-3">
                          <strong>Categories:</strong>
                          {Object.entries(stats.category_distribution || {}).map(([category, count]) => (
                            <div key={category}>{category}: {count}</div>
                          ))}
                        </div>
                        <div className="col-md-3">
                          <strong>Case Types:</strong>
                          {Object.entries(stats.case_type_distribution || {}).slice(0, 3).map(([type, count]) => (
                            <div key={type}>{type}: {count}</div>
                          ))}
                        </div>
                        <div className="col-md-3">
                          <strong>Years:</strong>
                          {Object.entries(stats.year_distribution || {}).slice(0, 3).map(([year, count]) => (
                            <div key={year}>{year}: {count}</div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Error/Success Messages */}
              {error && <div className="alert alert-danger">{error}</div>}
              {success && <div className="alert alert-success">{success}</div>}

              {/* Auto Processing Section */}
              <div className="row mb-4">
                <div className="col-md-6">
                  <div className="card">
                    <div className="card-header">
                      <h6>📥 Auto Download & Analyze Orders</h6>
                    </div>
                    <div className="card-body">
                      <div className="row mb-3">
                        <div className="col-md-6">
                          <label className="form-label">Case Type</label>
                          <select
                            className="form-select"
                            value={processFilters.case_type}
                            onChange={(e) => setProcessFilters({...processFilters, case_type: e.target.value})}
                          >
                            <option value="">All Types</option>
                            <option value="WP">WP (Writ Petition)</option>
                            <option value="PIL">PIL (Public Interest Litigation)</option>
                            <option value="CP">CP (Company Petition)</option>
                            <option value="IA">IA (Interim Application)</option>
                            <option value="RPW">RPW (Review Petition Writ)</option>
                          </select>
                        </div>
                        <div className="col-md-6">
                          <label className="form-label">Case Year</label>
                          <input
                            type="number"
                            className="form-control"
                            value={processFilters.case_year}
                            onChange={(e) => setProcessFilters({...processFilters, case_year: e.target.value})}
                            placeholder="e.g., 2024"
                            min="2020"
                            max="2030"
                          />
                        </div>
                      </div>
                      <div className="row mb-3">
                        <div className="col-md-6">
                          <label className="form-label">Date From</label>
                          <input
                            type="date"
                            className="form-control"
                            value={processFilters.date_from}
                            onChange={(e) => setProcessFilters({...processFilters, date_from: e.target.value})}
                          />
                        </div>
                        <div className="col-md-6">
                          <label className="form-label">Date To</label>
                          <input
                            type="date"
                            className="form-control"
                            value={processFilters.date_to}
                            onChange={(e) => setProcessFilters({...processFilters, date_to: e.target.value})}
                          />
                        </div>
                      </div>
                      <div className="row mb-3">
                        <div className="col-md-6">
                          <label className="form-label">Limit</label>
                          <input
                            type="number"
                            className="form-control"
                            value={processFilters.limit}
                            onChange={(e) => setProcessFilters({...processFilters, limit: parseInt(e.target.value)})}
                            min="1"
                            max="100"
                          />
                        </div>
                      </div>
                      <button
                        className="btn btn-primary w-100"
                        onClick={handleAutoProcessCases}
                        disabled={processing}
                      >
                        {processing ? '⏳ Processing...' : '🚀 Start Auto Processing'}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Search Section */}
                <div className="col-md-6">
                  <div className="card">
                    <div className="card-header">
                      <h6>🔍 Search Processed Orders</h6>
                    </div>
                    <div className="card-body">
                      <div className="row mb-3">
                        <div className="col-md-6">
                          <label className="form-label">Petitioner Name</label>
                          <input
                            type="text"
                            className="form-control"
                            value={searchFilters.petitioner_search}
                            onChange={(e) => setSearchFilters({...searchFilters, petitioner_search: e.target.value})}
                            placeholder="Search petitioner..."
                          />
                        </div>
                        <div className="col-md-6">
                          <label className="form-label">Respondent Name</label>
                          <input
                            type="text"
                            className="form-control"
                            value={searchFilters.respondent_search}
                            onChange={(e) => setSearchFilters({...searchFilters, respondent_search: e.target.value})}
                            placeholder="Search respondent..."
                          />
                        </div>
                      </div>
                      <div className="row mb-3">
                        <div className="col-md-4">
                          <label className="form-label">Case Type</label>
                          <select
                            className="form-select"
                            value={searchFilters.case_type}
                            onChange={(e) => setSearchFilters({...searchFilters, case_type: e.target.value})}
                          >
                            <option value="">All Types</option>
                            <option value="WP">WP</option>
                            <option value="PIL">PIL</option>
                            <option value="CP">CP</option>
                            <option value="IA">IA</option>
                            <option value="RPW">RPW</option>
                          </select>
                        </div>
                        <div className="col-md-4">
                          <label className="form-label">Year</label>
                          <input
                            type="number"
                            className="form-control"
                            value={searchFilters.case_year}
                            onChange={(e) => setSearchFilters({...searchFilters, case_year: e.target.value})}
                            placeholder="Year"
                          />
                        </div>
                        <div className="col-md-4">
                          <label className="form-label">Order Category</label>
                          <select
                            className="form-select"
                            value={searchFilters.order_category}
                            onChange={(e) => setSearchFilters({...searchFilters, order_category: e.target.value})}
                          >
                            <option value="">All Categories</option>
                            <option value="ADJOURNED">Adjourned</option>
                            <option value="HEARD_AND_ADJOURNED">Heard & Adjourned</option>
                            <option value="DISPOSED_OFF">Disposed Off</option>
                          </select>
                        </div>
                      </div>
                      <button
                        className="btn btn-success w-100"
                        onClick={handleSearchOrders}
                        disabled={searchLoading}
                      >
                        {searchLoading ? '⏳ Searching...' : '🔍 Search Orders'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Processing Results */}
              {processResults && (
                <div className="row mb-4">
                  <div className="col-12">
                    <div className="card">
                      <div className="card-header">
                        <h6>📊 Processing Results</h6>
                      </div>
                      <div className="card-body">
                        <div className="row">
                          <div className="col-md-3">
                            <div className="text-center">
                              <h4 className="text-primary">{processResults.total_cases}</h4>
                              <small>Total Cases</small>
                            </div>
                          </div>
                          <div className="col-md-3">
                            <div className="text-center">
                              <h4 className="text-success">{processResults.successful_downloads}</h4>
                              <small>Downloads</small>
                            </div>
                          </div>
                          <div className="col-md-3">
                            <div className="text-center">
                              <h4 className="text-info">{processResults.successful_analyses}</h4>
                              <small>Analyses</small>
                            </div>
                          </div>
                          <div className="col-md-3">
                            <div className="text-center">
                              <h4 className="text-danger">{processResults.failed_downloads}</h4>
                              <small>Failed</small>
                            </div>
                          </div>
                        </div>
                        
                        {processResults.errors && processResults.errors.length > 0 && (
                          <div className="mt-3">
                            <h6>Errors:</h6>
                            <div className="alert alert-warning">
                              {processResults.errors.slice(0, 5).map((error, index) => (
                                <div key={index}>{error}</div>
                              ))}
                              {processResults.errors.length > 5 && (
                                <div>... and {processResults.errors.length - 5} more errors</div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Search Results */}
              {searchResults.length > 0 && (
                <div className="row">
                  <div className="col-12">
                    <div className="card">
                      <div className="card-header">
                        <h6>🔍 Search Results ({searchResults.length} found)</h6>
                      </div>
                      <div className="card-body">
                        <div className="table-responsive" style={{ maxHeight: '600px', overflowY: 'auto' }}>
                          <table className="table table-hover">
                            <thead className="table-light sticky-top">
                              <tr>
                                <th>Case Reference</th>
                                <th>Petitioner</th>
                                <th>Respondent</th>
                                <th>Order Category</th>
                                <th>Order Date</th>
                                <th>Court Order</th>
                              </tr>
                            </thead>
                            <tbody>
                              {searchResults.map((result, index) => (
                                <tr key={index}>
                                  <td>
                                    <strong>{result.case_ref}</strong>
                                    <br />
                                    <small className="text-muted">
                                      Board: {result.board_date}
                                    </small>
                                  </td>
                                  <td>
                                    {result.petitioner_names && result.petitioner_names.length > 0 ? (
                                      <div>
                                        {result.petitioner_names.slice(0, 2).map((name, i) => (
                                          <div key={i}>{name}</div>
                                        ))}
                                        {result.petitioner_names.length > 2 && (
                                          <small className="text-muted">
                                            +{result.petitioner_names.length - 2} more
                                          </small>
                                        )}
                                      </div>
                                    ) : (
                                      <span className="text-muted">-</span>
                                    )}
                                  </td>
                                  <td>
                                    {result.respondent_names && result.respondent_names.length > 0 ? (
                                      <div>
                                        {result.respondent_names.slice(0, 2).map((name, i) => (
                                          <div key={i}>{name}</div>
                                        ))}
                                        {result.respondent_names.length > 2 && (
                                          <small className="text-muted">
                                            +{result.respondent_names.length - 2} more
                                          </small>
                                        )}
                                      </div>
                                    ) : (
                                      <span className="text-muted">-</span>
                                    )}
                                  </td>
                                  <td>
                                    <span className={`badge ${
                                      result.order_category === 'DISPOSED_OFF' ? 'bg-success' :
                                      result.order_category === 'HEARD_AND_ADJOURNED' ? 'bg-info' :
                                      result.order_category === 'ADJOURNED' ? 'bg-warning' : 'bg-secondary'
                                    }`}>
                                      {result.order_category}
                                    </span>
                                  </td>
                                  <td>
                                    {result.order_date ? (
                                      new Date(result.order_date).toLocaleDateString()
                                    ) : (
                                      <span className="text-muted">-</span>
                                    )}
                                  </td>
                                  <td>
                                    {result.order_link ? (
                                      <a
                                        href={result.order_link}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="btn btn-sm btn-outline-primary"
                                      >
                                        📄 View Order
                                      </a>
                                    ) : (
                                      <span className="text-muted">No link</span>
                                    )}
                                  </td>
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

            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AutoOrderProcessor;