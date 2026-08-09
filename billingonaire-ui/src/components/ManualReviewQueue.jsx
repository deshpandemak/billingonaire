import React, { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Card, Button, Alert, Badge, Spinner, Table } from 'react-bootstrap';
import { authenticatedFetchJSON } from '../lib/api';

const ORDER_CATEGORIES = [
  { value: 'ADJOURNED',           label: 'Adjourned',    variant: 'warning' },
  { value: 'HEARD_AND_ADJOURNED', label: 'Heard & Adj.', variant: 'info'    },
  { value: 'DISPOSED_OFF',        label: 'Disposed',     variant: 'success' },
];

const ManualReviewQueue = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [overriding, setOverriding] = useState(null);
  const [message, setMessage] = useState(null);
  // Per-row AI suggestion state, keyed by doc_id/case_ref: undefined (not
  // fetched), 'loading', { category, confidence, rationale }, or { error }.
  const [aiSuggestions, setAiSuggestions] = useState({});

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await authenticatedFetchJSON('/admin/review-queue');
      setItems(Array.isArray(data) ? data : (data.items || []));
    } catch (e) {
      setError(`Failed to load review queue: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  const handleGetAiRead = async (item) => {
    const key = item.doc_id || item.case_ref;
    setAiSuggestions(prev => ({ ...prev, [key]: 'loading' }));
    try {
      const data = await authenticatedFetchJSON(`/admin/orders/${encodeURIComponent(key)}/ai-suggestion`, {
        method: 'POST',
      });
      setAiSuggestions(prev => ({ ...prev, [key]: data }));
    } catch (e) {
      setAiSuggestions(prev => ({ ...prev, [key]: { error: e.message || 'AI read failed.' } }));
    }
  };

  const handleOverride = async (item, category) => {
    const key = item.doc_id || item.case_ref;
    setOverriding(key);
    try {
      await authenticatedFetchJSON(`/admin/orders/${encodeURIComponent(key)}/override`, {
        method: 'POST',
        body: JSON.stringify({ order_category: category }),
      });
      const catLabel = ORDER_CATEGORIES.find(c => c.value === category)?.label ?? category;
      setMessage({ type: 'success', text: `${item.case_ref || key} — set to ${catLabel}` });
      setItems(prev => prev.filter(i => (i.doc_id || i.case_ref) !== key));
    } catch (e) {
      setMessage({ type: 'danger', text: `Override failed for ${item.case_ref || key}: ${e.message}` });
    } finally {
      setOverriding(null);
    }
  };

  return (
    <Container fluid className="py-4">
      <Row className="mb-3 align-items-center">
        <Col>
          <h2 className="mb-1">Needs Review</h2>
          <p className="text-muted mb-0">
            Orders the system could not classify confidently. Confirm the outcome
            here and it will be used for billing — these cases are held back until
            you do.
          </p>
        </Col>
        <Col xs="auto">
          <Button variant="outline-secondary" size="sm" onClick={fetchQueue} disabled={loading}>
            Refresh
          </Button>
        </Col>
      </Row>

      {message && (
        <Alert
          variant={message.type}
          dismissible
          onClose={() => setMessage(null)}
          className="mb-3"
        >
          {message.text}
        </Alert>
      )}

      <Card className="shadow-sm">
        <Card.Header>
          <div className="d-flex justify-content-between align-items-center">
            <h5 className="mb-0">Pending Review</h5>
            {!loading && (
              <Badge bg={items.length > 0 ? 'warning' : 'success'} text={items.length > 0 ? 'dark' : undefined}>
                {items.length} {items.length === 1 ? 'item' : 'items'}
              </Badge>
            )}
          </div>
        </Card.Header>

        <Card.Body className="p-0">
          {loading ? (
            <div className="text-center py-5">
              <Spinner animation="border" variant="primary" />
              <p className="mt-3 text-muted">Loading review queue…</p>
            </div>
          ) : error ? (
            <div className="text-center py-5 px-4">
              <Alert variant="danger">{error}</Alert>
              <Button variant="outline-primary" onClick={fetchQueue}>Retry</Button>
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-5">
              <p className="mb-1" style={{ fontSize: '1.5rem' }}>✓</p>
              <p className="text-muted mb-0">No cases awaiting manual review.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <Table hover className="mb-0" style={{ fontSize: '0.875rem' }}>
                <thead className="table-light">
                  <tr>
                    <th>Case Ref</th>
                    <th>Board Date</th>
                    <th>Petitioner</th>
                    <th>Respondent</th>
                    <th>ML Result</th>
                    <th>Confidence</th>
                    <th style={{ minWidth: 300 }}>Set Category</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => {
                    const key = item.doc_id || item.case_ref;
                    const isProcessing = overriding === key;
                    const conf = item.confidence_score != null
                      ? Math.round(item.confidence_score * 100)
                      : null;

                    return (
                      <React.Fragment key={key}>
                      <tr>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <strong>{item.case_ref || item.case_no || '—'}</strong>
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {item.board_date || item.order_date || '—'}
                        </td>
                        <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                            title={item.petitioner}>
                          {item.petitioner || '—'}
                        </td>
                        <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                            title={item.respondent}>
                          {item.respondent || '—'}
                        </td>
                        <td>
                          {item.order_category ? (
                            <Badge bg="secondary">{item.order_category}</Badge>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td>
                          {conf != null ? (
                            <Badge
                              bg={conf < 50 ? 'danger' : conf < 70 ? 'warning' : 'secondary'}
                              text={conf < 70 ? 'dark' : undefined}
                            >
                              {conf}%
                            </Badge>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td>
                          {isProcessing ? (
                            <Spinner animation="border" size="sm" />
                          ) : (
                            <div className="d-flex gap-1 flex-wrap">
                              {ORDER_CATEGORIES.map(cat => {
                                const aiAgrees = aiSuggestions[key]
                                  && aiSuggestions[key] !== 'loading'
                                  && !aiSuggestions[key].error
                                  && aiSuggestions[key].category === cat.value;
                                return (
                                  <Button
                                    key={cat.value}
                                    size="sm"
                                    variant={aiAgrees ? cat.variant : `outline-${cat.variant}`}
                                    onClick={() => handleOverride(item, cat.value)}
                                    title={aiAgrees ? 'The AI read agrees with this category' : undefined}
                                  >
                                    {cat.label}{aiAgrees ? ' ✓' : ''}
                                  </Button>
                                );
                              })}
                              {item.order_link && (
                                <Button
                                  size="sm"
                                  variant="outline-secondary"
                                  as="a"
                                  href={item.order_link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  View PDF
                                </Button>
                              )}
                              {!aiSuggestions[key] && (
                                <Button
                                  size="sm"
                                  variant="outline-dark"
                                  onClick={() => handleGetAiRead(item)}
                                >
                                  Get AI read
                                </Button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                      {aiSuggestions[key] && (
                        <tr key={`${key}-ai`}>
                          <td colSpan={7} className="py-2" style={{ background: 'var(--bs-light, #f8f9fa)' }}>
                            {aiSuggestions[key] === 'loading' ? (
                              <span className="text-muted small">
                                <Spinner animation="border" size="sm" className="me-2" />
                                Reading the order…
                              </span>
                            ) : aiSuggestions[key].error ? (
                              <span className="text-danger small">
                                AI read unavailable: {aiSuggestions[key].error}
                              </span>
                            ) : (
                              <span className="small">
                                <strong>AI read:</strong>{' '}
                                <Badge bg={ORDER_CATEGORIES.find(c => c.value === aiSuggestions[key].category)?.variant ?? 'secondary'}>
                                  {ORDER_CATEGORIES.find(c => c.value === aiSuggestions[key].category)?.label ?? aiSuggestions[key].category}
                                </Badge>
                                {aiSuggestions[key].confidence != null && (
                                  <span className="text-muted"> ({Math.round(aiSuggestions[key].confidence * 100)}%)</span>
                                )}
                                {' — '}
                                {aiSuggestions[key].rationale}
                              </span>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                    );
                  })}
                </tbody>
              </Table>
            </div>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
};

export default ManualReviewQueue;
