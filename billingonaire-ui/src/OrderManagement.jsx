import React, { useState, useEffect, useCallback } from 'react';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const OrderManagement = () => {
  const [casesWithoutOrders, setCasesWithoutOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedCase, setSelectedCase] = useState(null);
  const [orderStatus, setOrderStatus] = useState('not_present');
  const [orderLink, setOrderLink] = useState('');
  const [orderText, setOrderText] = useState('');
  const [notes, setNotes] = useState('');
  const [pagination, setPagination] = useState({ offset: 0, limit: 50, hasMore: true });

  // Filter states
  const [filterBench, setFilterBench] = useState('all');
  const [filterCaseType, setFilterCaseType] = useState('all');
  const [filterYear, setFilterYear] = useState('all');

  // Bulk processing states
  const [selectedCases, setSelectedCases] = useState(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [bulkMaxSequences, setBulkMaxSequences] = useState(50);
  const [bulkResults, setBulkResults] = useState(null);

  useEffect(() => {
    loadCasesWithoutOrders();
  }, [loadCasesWithoutOrders]);

  const loadCasesWithoutOrders = useCallback(async (offset = 0) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: pagination.limit.toString(),
        offset: offset.toString()
      });

      const result = await authenticatedFetchJSON(`/orders/cases-without-orders?${params}`);

      if (result.error) {
        setError(result.error);
      } else {
        if (offset === 0) {
          setCasesWithoutOrders(result.cases || []);
        } else {
          setCasesWithoutOrders(prev => [...prev, ...(result.cases || [])]);
        }

        setPagination(prev => ({
          ...prev,
          offset: offset,
          hasMore: result.has_more || false
        }));
      }
    } catch (e) {
      console.error('Failed to load cases:', e);
      setError(`Failed to load cases: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [pagination.limit]);

  const loadMoreCases = () => {
    if (!loading && pagination.hasMore) {
      loadCasesWithoutOrders(pagination.offset + pagination.limit);
    }
  };

  const handleCaseSelection = (caseItem) => {
    setSelectedCase(caseItem);
    setOrderStatus('not_present');
    setOrderLink('');
    setOrderText('');
    setNotes('');
  };

  const handleCreateOrderLink = async () => {
    if (!selectedCase) return;

    setLoading(true);
    try {
      const orderData = {
        case_id: selectedCase.id,
        status: orderStatus,
        order_link: orderLink,
        order_text: orderText,
        court_bench: filterBench !== 'all' ? filterBench : 'mumbai',
        notes: notes
      };

      const result = await authenticatedFetchJSON('/orders/create-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderData)
      });

      if (result.success) {
        // Remove the case from the list since it now has an order
        setCasesWithoutOrders(prev => prev.filter(c => c.id !== selectedCase.id));
        setSelectedCase(null);
        alert('Order link created successfully!');
      } else {
        setError(result.error);
      }
    } catch (e) {
      console.error('Failed to create order link:', e);
      setError(`Failed to create order link: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAutoFetchOrder = async (caseItem) => {
    if (!caseItem) return;

    setLoading(true);
    setError(null);

    try {
      // Determine court bench based on case type and patterns
      let bench = 'mumbai';
      if (caseItem.case_type && (caseItem.case_type.includes('APPEAL') || caseItem.case_type === 'CA')) {
        bench = 'mumbai_appellate';
      }

      const params = new URLSearchParams({
        case_ref: caseItem.case_ref,
        bench: bench
      });

      const result = await authenticatedFetchJSON(`/court/case-details?${params}`);

      if (result.status === 'captcha_required') {
        // Mark as failed and provide court website link
        setSelectedCase(caseItem);
        setOrderStatus('failed');
        setNotes(`CAPTCHA verification required. Visit: ${result.search_url}`);
        alert(`CAPTCHA verification required for case ${caseItem.case_ref}. Please visit the court website manually.`);
        // Open court website in new tab
        window.open(result.search_url, '_blank');
      } else if (result.error) {
        setSelectedCase(caseItem);
        setOrderStatus('failed');
        setNotes(`Auto-fetch error: ${result.error}`);
        setError(`Auto-fetch failed for ${caseItem.case_ref}: ${result.error}`);
      } else {
        // Process successful response
        setSelectedCase(caseItem);
        if (result.order_links && result.order_links.length > 0) {
          setOrderLink(result.order_links[0].url);
          setOrderStatus('linked');
          setNotes('Auto-fetch successful');
        } else {
          setOrderStatus('failed');
          setNotes('Auto-fetch completed but no orders found');
        }
      }
    } catch (e) {
      console.error('Auto-fetch failed:', e);
      setSelectedCase(caseItem);
      setOrderStatus('failed');
      setNotes(`Auto-fetch exception: ${e.message}`);
      setError(`Auto-fetch failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Bulk processing functions
  const handleBulkCaseSelection = (caseId, checked) => {
    const newSelected = new Set(selectedCases);
    if (checked) {
      newSelected.add(caseId);
    } else {
      newSelected.delete(caseId);
    }
    setSelectedCases(newSelected);
  };

  const handleSelectAll = (checked) => {
    if (checked) {
      setSelectedCases(new Set(filteredCases.map(c => c.id)));
    } else {
      setSelectedCases(new Set());
    }
  };

  const handleBulkProcessOrders = async () => {
    if (selectedCases.size === 0) {
      setError('Please select at least one case for bulk processing');
      return;
    }

    setBulkProcessing(true);
    setError(null);
    setBulkResults(null);

    try {
      const result = await authenticatedFetchJSON('/orders/bulk-process-orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_ids: Array.from(selectedCases),
          max_sequences: bulkMaxSequences
        })
      });

      if (result.success) {
        setBulkResults(result.results);
        // Refresh the cases list to show updated status
        loadCasesWithoutOrders(0);
        setSelectedCases(new Set());
        alert(`Bulk processing completed! ${result.results.successful} successful, ${result.results.failed} failed.`);
      } else {
        setError(result.error || 'Bulk processing failed');
      }
    } catch (e) {
      console.error('Bulk processing failed:', e);
      setError(`Bulk processing failed: ${e.message}`);
    } finally {
      setBulkProcessing(false);
    }
  };

  const filteredCases = casesWithoutOrders.filter(caseItem => {
    if (filterBench !== 'all' && !caseItem.case_ref.includes('WP') && filterBench === 'mumbai_appellate') {
      return false;
    }
    if (filterCaseType !== 'all' && caseItem.case_type !== filterCaseType) {
      return false;
    }
    if (filterYear !== 'all' && caseItem.case_year !== filterYear) {
      return false;
    }
    return true;
  });

  const uniqueCaseTypes = [...new Set(casesWithoutOrders.map(c => c.case_type))].filter(Boolean);
  const uniqueYears = [...new Set(casesWithoutOrders.map(c => c.case_year))].filter(Boolean).sort().reverse();

  return (
    <div className="container-fluid mt-4">
      <div className="row">
        <div className="col-12">
          <div className="card">
            <div className="card-header">
              <h5>📋 Order Management System</h5>
              <p className="text-muted mb-0">Manage cases without linked court orders</p>
            </div>
            <div className="card-body">

              {/* Filters */}
              <div className="row mb-4">
                <div className="col-md-3">
                  <label className="form-label">Filter by Bench</label>
                  <select
                    className="form-select"
                    value={filterBench}
                    onChange={(e) => setFilterBench(e.target.value)}
                  >
                    <option value="all">All Benches</option>
                    <option value="mumbai">Mumbai (Original Side)</option>
                    <option value="mumbai_appellate">Mumbai (Appellate Side)</option>
                    <option value="aurangabad">Aurangabad Bench</option>
                    <option value="nagpur">Nagpur Bench</option>
                    <option value="goa">Goa Bench</option>
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">Filter by Case Type</label>
                  <select
                    className="form-select"
                    value={filterCaseType}
                    onChange={(e) => setFilterCaseType(e.target.value)}
                  >
                    <option value="all">All Types</option>
                    {uniqueCaseTypes.map(type => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">Filter by Year</label>
                  <select
                    className="form-select"
                    value={filterYear}
                    onChange={(e) => setFilterYear(e.target.value)}
                  >
                    <option value="all">All Years</option>
                    {uniqueYears.map(year => (
                      <option key={year} value={year}>{year}</option>
                    ))}
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">&nbsp;</label>
                  <div>
                    <button
                      className="btn btn-outline-primary"
                      onClick={() => loadCasesWithoutOrders(0)}
                      disabled={loading}
                    >
                      🔄 Refresh
                    </button>
                  </div>
                </div>
              </div>

              {/* Bulk Processing Controls */}
              <div className="row mb-4">
                <div className="col-12">
                  <div className="card">
                    <div className="card-header">
                      <h6>⚡ Bulk Order Processing</h6>
                    </div>
                    <div className="card-body">
                      <div className="row align-items-end">
                        <div className="col-md-3">
                          <label className="form-label">Max Sequence Orders to Try</label>
                          <input
                            type="number"
                            className="form-control"
                            value={bulkMaxSequences}
                            onChange={(e) => setBulkMaxSequences(parseInt(e.target.value) || 50)}
                            min="1"
                            max="200"
                            placeholder="50"
                          />
                          <small className="text-muted">How many sequence numbers to try downloading per case</small>
                        </div>
                        <div className="col-md-6">
                          <div className="d-flex align-items-center gap-3">
                            <div className="form-check">
                              <input
                                className="form-check-input"
                                type="checkbox"
                                id="selectAll"
                                checked={selectedCases.size === filteredCases.length && filteredCases.length > 0}
                                onChange={(e) => handleSelectAll(e.target.checked)}
                              />
                              <label className="form-check-label" htmlFor="selectAll">
                                Select All ({selectedCases.size} selected)
                              </label>
                            </div>
                          </div>
                        </div>
                        <div className="col-md-3">
                          <button
                            className="btn btn-success w-100"
                            onClick={handleBulkProcessOrders}
                            disabled={bulkProcessing || selectedCases.size === 0}
                          >
                            {bulkProcessing ? '⏳ Processing...' : `🚀 Process ${selectedCases.size} Cases`}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bulk Results */}
              {bulkResults && (
                <div className="row mb-4">
                  <div className="col-12">
                    <div className="alert alert-info">
                      <h6>📊 Bulk Processing Results</h6>
                      <div className="row">
                        <div className="col-md-3">
                          <strong>Successful:</strong> {bulkResults.successful || 0}
                        </div>
                        <div className="col-md-3">
                          <strong>Failed:</strong> {bulkResults.failed || 0}
                        </div>
                        <div className="col-md-3">
                          <strong>Total Processed:</strong> {(bulkResults.successful || 0) + (bulkResults.failed || 0)}
                        </div>
                        <div className="col-md-3">
                          <strong>Max Sequences Used:</strong> {bulkMaxSequences}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

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
                  <p className="mt-2">Loading cases...</p>
                </div>
              )}

              {/* Cases Table */}
              <div className="row">
                <div className="col-md-8">
                  <h6>Cases Without Orders ({filteredCases.length} found)</h6>
                  <div className="table-responsive" style={{ maxHeight: '600px', overflowY: 'auto' }}>
                    <table className="table table-hover">
                      <thead className="table-light sticky-top">
                        <tr>
                          <th style={{width: '50px'}}>
                            <input
                              type="checkbox"
                              className="form-check-input"
                              checked={selectedCases.size === filteredCases.length && filteredCases.length > 0}
                              onChange={(e) => handleSelectAll(e.target.checked)}
                            />
                          </th>
                          <th>Case Reference</th>
                          <th>Board Date</th>
                          <th>AGP</th>
                          <th>Petitioner</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCases.map((caseItem, _index) => (
                          <tr
                            key={caseItem.id}
                            className={selectedCase?.id === caseItem.id ? 'table-active' : ''}
                          >
                            <td>
                              <input
                                type="checkbox"
                                className="form-check-input"
                                checked={selectedCases.has(caseItem.id)}
                                onChange={(e) => handleBulkCaseSelection(caseItem.id, e.target.checked)}
                              />
                            </td>
                            <td>
                              <strong>{caseItem.case_ref}</strong>
                              <br />
                              <small className="text-muted">{caseItem.file_name}</small>
                            </td>
                            <td>{caseItem.board_date}</td>
                            <td>{caseItem.respondent_lawyer}</td>
                            <td>{caseItem.petitioner_lawyer}</td>
                            <td>
                              <div className="btn-group-vertical btn-group-sm" role="group">
                                <button
                                  className="btn btn-outline-primary btn-sm"
                                  onClick={() => handleCaseSelection(caseItem)}
                                >
                                  📝 Select
                                </button>
                                <button
                                  className="btn btn-outline-info btn-sm"
                                  onClick={() => handleAutoFetchOrder(caseItem)}
                                  disabled={loading}
                                >
                                  🤖 Auto Fetch
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Load More Button */}
                  {pagination.hasMore && (
                    <div className="text-center mt-3">
                      <button
                        className="btn btn-outline-secondary"
                        onClick={loadMoreCases}
                        disabled={loading}
                      >
                        Load More Cases
                      </button>
                    </div>
                  )}
                </div>

                {/* Order Linking Panel */}
                <div className="col-md-4">
                  <div className="card">
                    <div className="card-header">
                      <h6>🔗 Link Order</h6>
                    </div>
                    <div className="card-body">
                      {selectedCase ? (
                        <>
                          <div className="mb-3">
                            <h6>Selected Case</h6>
                            <p><strong>{selectedCase.case_ref}</strong></p>
                            <p><small>Date: {selectedCase.board_date}</small></p>
                            <p><small>AGP: {selectedCase.respondent_lawyer}</small></p>
                          </div>

                          <div className="mb-3">
                            <label className="form-label">Order Status</label>
                            <select
                              className="form-select"
                              value={orderStatus}
                              onChange={(e) => setOrderStatus(e.target.value)}
                            >
                              <option value="linked">Linked</option>
                              <option value="failed">Failed to Fetch</option>
                              <option value="manually_uploaded">Manually Uploaded</option>
                              <option value="not_present">Not Present</option>
                            </select>
                          </div>

                          {(orderStatus === 'linked' || orderStatus === 'manually_uploaded') && (
                            <div className="mb-3">
                              <label className="form-label">Order Link/URL</label>
                              <input
                                type="url"
                                className="form-control"
                                value={orderLink}
                                onChange={(e) => setOrderLink(e.target.value)}
                                placeholder="https://..."
                              />
                            </div>
                          )}

                          <div className="mb-3">
                            <label className="form-label">Order Text/Summary</label>
                            <textarea
                              className="form-control"
                              rows="3"
                              value={orderText}
                              onChange={(e) => setOrderText(e.target.value)}
                              placeholder="Enter order details or summary..."
                            />
                          </div>

                          <div className="mb-3">
                            <label className="form-label">Notes</label>
                            <textarea
                              className="form-control"
                              rows="2"
                              value={notes}
                              onChange={(e) => setNotes(e.target.value)}
                              placeholder="Additional notes..."
                            />
                          </div>

                          <button
                            className="btn btn-primary w-100"
                            onClick={handleCreateOrderLink}
                            disabled={loading}
                          >
                            {loading ? '⏳ Saving...' : '💾 Save Order Link'}
                          </button>
                        </>
                      ) : (
                        <div className="text-center text-muted py-4">
                          <p>Select a case from the table to link its order</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OrderManagement;
