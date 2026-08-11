import React, { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Card, Button, Form, Alert, Badge, ProgressBar, Table, Modal, Nav } from 'react-bootstrap';
import { auth } from './lib/firebase';
import ManualReviewQueue from './components/ManualReviewQueue';

const API_URL = import.meta.env.VITE_API_URL || '/api';

const AdminOrderManagement = () => {
    const [currentUser, setCurrentUser] = useState(null);

    useEffect(() => {
        const unsubscribe = auth.onAuthStateChanged(user => {
            setCurrentUser(user);
        });
        return () => unsubscribe();
    }, []);
    const [overview, setOverview] = useState(null);
    const [queueStatus, setQueueStatus] = useState(null);
    const [queueDetail, setQueueDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [processing, setProcessing] = useState(false);
    const [message, setMessage] = useState(null);
    const [selectedStatuses, setSelectedStatuses] = useState(['not_linked', 'order_failed']);
    const [limit, setLimit] = useState(100);
    const [daysBack, setDaysBack] = useState(30);
    const [confirmState, setConfirmState] = useState({ show: false, title: '', body: '', onConfirm: null });
    // /admin/review now redirects here with ?tab=review.
    const [activeTab, setActiveTab] = useState(
        () => (new URLSearchParams(window.location.search).get('tab') === 'review' ? 'review' : 'pipeline')
    );
    const reviewCount = queueStatus?.review_queue_count
        ?? queueStatus?.status_counts?.manual_review_required
        ?? 0;

    const requireConfirm = (title, body, onConfirm) => {
        setConfirmState({ show: true, title, body, onConfirm });
    };

    const handleConfirm = () => {
        const fn = confirmState.onConfirm;
        setConfirmState(s => ({ ...s, show: false }));
        fn?.();
    };

    const statusLabels = {
        'not_linked': 'Not Linked',
        'linked': 'Order Linked (Not Analysed)',
        'analysed': 'Linked & Analysed',
        'order_failed': 'Order Failed',
        'order_analysis_failed': 'Analysis Failed'
    };

    const statusVariants = {
        'not_linked': 'secondary',
        'linked': 'info',
        'analysed': 'success',
        'order_failed': 'danger',
        'order_analysis_failed': 'warning'
    };

    const loadOverview = useCallback(async () => {
        if (!currentUser) return;
        try {
            setLoading(true);
            const idToken = await currentUser.getIdToken();

            const response = await fetch(`${API_URL}/admin/order-status-overview`, {
                headers: {
                    'Authorization': `Bearer ${idToken}`
                }
            });

            const data = await response.json();
            if (data.success) {
                setOverview(data);
            }
        } catch {
            setMessage({ type: 'danger', text: 'Failed to load overview' });
        } finally {
            setLoading(false);
        }
    }, [currentUser]);

    const loadQueueStatus = useCallback(async () => {
        if (!currentUser) return;
        try {
            const idToken = await currentUser.getIdToken();

            const response = await fetch(`${API_URL}/queue/status`, {
                headers: {
                    'Authorization': `Bearer ${idToken}`
                }
            });

            const data = await response.json();
            setQueueStatus(data);
        } catch {
            // non-critical — queue status will retry on next interval
        }
    }, [currentUser]);

    const loadQueueDetail = useCallback(async () => {
        if (!currentUser) return;
        try {
            const idToken = await currentUser.getIdToken();

            const response = await fetch(`${API_URL}/queue/detail?limit=10`, {
                headers: {
                    'Authorization': `Bearer ${idToken}`
                }
            });

            const data = await response.json();
            setQueueDetail(data);
        } catch {
            // non-critical — queue detail will retry on next interval
        }
    }, [currentUser]);

    const formatAge = (ageSeconds) => {
        if (ageSeconds === null || ageSeconds === undefined) return '—';
        const minutes = Math.round(ageSeconds / 60);
        if (minutes < 1) return '<1m';
        if (minutes < 60) return `${minutes}m`;
        return `${Math.round(minutes / 60)}h`;
    };

    useEffect(() => {
        if (!currentUser) return;

        loadOverview();
        loadQueueStatus();
        loadQueueDetail();

        const interval = setInterval(() => {
            loadQueueStatus();
            loadQueueDetail();
        }, 5000);

        return () => clearInterval(interval);
    }, [currentUser, loadOverview, loadQueueStatus, loadQueueDetail]);

    const startBulkProcessing = async () => {
        try {
            setProcessing(true);
            setMessage(null);

            const idToken = await currentUser.getIdToken();

            const response = await fetch(`${API_URL}/admin/bulk-order-processing`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${idToken}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    order_statuses: selectedStatuses,
                    limit: limit,
                    days_back: daysBack,
                })
            });

            const data = await response.json();

            if (data.success) {
                setMessage({
                    type: 'success',
                    text: `${data.message}. Processing ${data.cases_queued} cases in background.`
                });

                // Reload data after 2 seconds -- long enough for the fetch
                // poll loop to have picked up at least the first case.
                setTimeout(() => {
                    loadOverview();
                    loadQueueStatus();
                }, 2000);
            } else {
                setMessage({
                    type: 'danger',
                    text: data.error || 'Failed to start bulk processing'
                });
            }
        } catch (error) {
            console.error('Error starting bulk processing:', error);
            setMessage({
                type: 'danger',
                text: 'Failed to start bulk processing: ' + error.message
            });
        } finally {
            setProcessing(false);
        }
    };

    const retryFailedCases = async () => {
        try {
            setProcessing(true);
            setMessage(null);
            const idToken = await currentUser.getIdToken();
            const response = await fetch(`${API_URL}/jobs/retry-failed`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${idToken}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ limit: 500 })
            });
            const data = await response.json();
            if (data.success) {
                setMessage({
                    type: 'success',
                    text: `✅ Retrying failed cases — fetch queue: ${data.fetch_queued}, analysis queue: ${data.analysis_queued}`
                });
                setTimeout(() => { loadOverview(); loadQueueStatus(); }, 2000);
            } else {
                setMessage({ type: 'danger', text: data.error || 'Retry failed' });
            }
        } catch (error) {
            setMessage({ type: 'danger', text: 'Failed to retry cases: ' + error.message });
        } finally {
            setProcessing(false);
        }
    };

    const queueLinkedForAnalysis = async () => {
        try {
            setProcessing(true);
            setMessage(null);
            const idToken = await currentUser.getIdToken();
            const response = await fetch(`${API_URL}/jobs/analyze-orders`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${idToken}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ limit: 500 })
            });
            const data = await response.json();
            if (data.success) {
                setMessage({
                    type: 'success',
                    text: `✅ Queued ${data.queued} linked cases for analysis (skipped ${data.skipped} without order links)`
                });
                setTimeout(() => { loadOverview(); loadQueueStatus(); }, 2000);
            } else {
                setMessage({ type: 'danger', text: data.error || 'Failed to queue analysis jobs' });
            }
        } catch (error) {
            setMessage({ type: 'danger', text: 'Failed to queue analysis: ' + error.message });
        } finally {
            setProcessing(false);
        }
    };

    const handleStatusToggle = (status) => {
        if (selectedStatuses.includes(status)) {
            setSelectedStatuses(selectedStatuses.filter(s => s !== status));
        } else {
            setSelectedStatuses([...selectedStatuses, status]);
        }
    };

    const getStatusPercentage = (status) => {
        if (!overview || !overview.total_cases) return 0;
        return ((overview.status_counts[status] / overview.total_cases) * 100).toFixed(1);
    };

    if (!currentUser) {
        return (
            <Container fluid className="py-4">
                <Row className="mb-4">
                    <Col className="text-center">
                        <div className="spinner-border" role="status">
                            <span className="visually-hidden">Loading...</span>
                        </div>
                        <p className="text-muted mt-2">Loading...</p>
                    </Col>
                </Row>
            </Container>
        );
    }

    return (
        <Container fluid className="py-4">
            <Row className="mb-3">
                <Col>
                    <h2 className="mb-0">Pipeline &amp; Review</h2>
                    <p className="text-muted">Order processing across all cases, and cases the system could not decide on its own.</p>
                </Col>
            </Row>

            {/* Review Queue used to be a separate nav destination. It is one
                tab here so all operator work lives behind a single entry. */}
            <Nav variant="tabs" className="mb-4" activeKey={activeTab} onSelect={(k) => setActiveTab(k || 'pipeline')}>
                <Nav.Item>
                    <Nav.Link eventKey="pipeline">Pipeline</Nav.Link>
                </Nav.Item>
                <Nav.Item>
                    <Nav.Link eventKey="review">
                        Needs Review
                        {reviewCount > 0 && <Badge bg="danger" className="ms-2">{reviewCount}</Badge>}
                    </Nav.Link>
                </Nav.Item>
            </Nav>

            {activeTab === 'review' && <ManualReviewQueue />}

            {activeTab === 'pipeline' && (
            <>
            {message && (
                <Row className="mb-3">
                    <Col>
                        <Alert variant={message.type} dismissible onClose={() => setMessage(null)}>
                            {message.text}
                        </Alert>
                    </Col>
                </Row>
            )}

            <Row className="mb-4">
                <Col lg={8}>
                    <Card className="shadow-sm mb-3">
                        <Card.Header className="bg-primary text-white">
                            <h5 className="mb-0">Order Status Overview</h5>
                        </Card.Header>
                        <Card.Body>
                            {loading ? (
                                <div className="text-center py-4">
                                    <div className="spinner-border" role="status">
                                        <span className="visually-hidden">Loading...</span>
                                    </div>
                                </div>
                            ) : overview ? (
                                <>
                                    <Row className="mb-3">
                                        <Col md={6}>
                                            <h3 className="mb-0">{overview.total_cases.toLocaleString()}</h3>
                                            <small className="text-muted">Total Cases</small>
                                        </Col>
                                        <Col md={6}>
                                            <h3 className="mb-0">{overview.pending_processing.toLocaleString()}</h3>
                                            <small className="text-muted">Pending Processing</small>
                                        </Col>
                                    </Row>

                                    <Table striped bordered hover className="mb-0">
                                        <thead>
                                            <tr>
                                                <th>Status</th>
                                                <th>Count</th>
                                                <th>Percentage</th>
                                                <th>Progress</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {Object.entries(overview.status_counts)
                                                .filter(([status, _count]) => status && status.trim() !== '' && statusLabels[status])
                                                .map(([status, count]) => (
                                                <tr key={status}>
                                                    <td>
                                                        <Badge bg={statusVariants[status]}>
                                                            {statusLabels[status]}
                                                        </Badge>
                                                    </td>
                                                    <td>{count.toLocaleString()}</td>
                                                    <td>{getStatusPercentage(status)}%</td>
                                                    <td>
                                                        <ProgressBar
                                                            now={getStatusPercentage(status)}
                                                            variant={statusVariants[status]}
                                                            style={{height: '20px'}}
                                                        />
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </Table>
                                </>
                            ) : (
                                <p className="text-muted mb-0">No data available</p>
                            )}
                        </Card.Body>
                    </Card>
                </Col>

                <Col lg={4}>
                    <Card className="shadow-sm mb-3">
                        <Card.Header className="bg-info text-white">
                            <h5 className="mb-0">Processing Queue</h5>
                        </Card.Header>
                        <Card.Body>
                            {queueStatus ? (
                                <>
                                    {/* Fetch and analysis shown as one pipeline, not two
                                        separate queues -- they're almost always one
                                        worker turn per case (analysis runs inline right
                                        after a successful fetch); tracked as two phases
                                        internally only because they have different
                                        retry/timeout behaviour. */}
                                    <Row className="mb-2">
                                        <Col xs={6} className="text-center">
                                            <h4 className="mb-0">{(queueStatus.total_queued ?? ((queueStatus.fetch_queue_size ?? queueStatus.queue_size ?? 0) + (queueStatus.analysis_queue_size ?? 0)))}</h4>
                                            <small className="text-muted">Queued</small>
                                        </Col>
                                        <Col xs={6} className="text-center">
                                            <h4 className="mb-0">{(queueStatus.total_in_progress ?? ((queueStatus.fetch_in_progress_count ?? 0) + (queueStatus.analysis_in_progress_count ?? 0)))}</h4>
                                            <small className="text-muted">In Progress</small>
                                        </Col>
                                    </Row>
                                    <div className="mb-2 d-flex gap-2 flex-wrap">
                                        <Badge bg={queueStatus.pipeline_active ? 'success' : 'secondary'}>
                                            Pipeline: {queueStatus.pipeline_active ? 'Active' : 'Idle'}
                                        </Badge>
                                    </div>
                                    {(queueStatus.fetch_pending_cases > 0 || queueStatus.analysis_pending_cases > 0) && (
                                        <p className="text-muted small mb-2">
                                            Persisted: {queueStatus.fetch_pending_cases ?? 0} fetch pending, {queueStatus.analysis_pending_cases ?? 0} analysis pending
                                        </p>
                                    )}
                                    {queueDetail?.cases?.length > 0 ? (
                                        <div className="table-responsive">
                                            <Table size="sm" className="mb-0">
                                                <thead>
                                                    <tr>
                                                        <th>Case</th>
                                                        <th>Status</th>
                                                        <th>Age</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {queueDetail.cases.map(c => (
                                                        <tr key={c.doc_id} className={c.stale ? 'table-warning' : undefined}>
                                                            <td className="text-truncate" style={{ maxWidth: '110px' }} title={c.case_ref}>{c.case_ref}</td>
                                                            <td>
                                                                <small>{c.status.replace(/_/g, ' ')}</small>
                                                                {c.stale && <Badge bg="warning" text="dark" className="ms-1">stale</Badge>}
                                                            </td>
                                                            <td>{formatAge(c.age_seconds)}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </Table>
                                        </div>
                                    ) : (
                                        ((queueStatus.total_queued ?? 0) > 0 || (queueStatus.total_in_progress ?? 0) > 0) && (
                                            <p className="text-muted small mb-0">Loading case list...</p>
                                        )
                                    )}
                                </>
                            ) : (
                                <p className="text-muted mb-0">Loading...</p>
                            )}
                        </Card.Body>
                    </Card>

                    <Card className="shadow-sm mb-3">
                        <Card.Header className="bg-warning">
                            <h5 className="mb-0">Quick Actions</h5>
                        </Card.Header>
                        <Card.Body className="d-grid gap-2">
                            <Button
                                variant="outline-warning"
                                onClick={() => requireConfirm(
                                    'Retry All Failed Cases',
                                    'Re-queue all order_failed and order_analysis_failed cases for retry?',
                                    retryFailedCases
                                )}
                                disabled={processing}
                            >
                                Retry All Failed Cases
                            </Button>
                            <Button
                                variant="outline-info"
                                onClick={() => requireConfirm(
                                    'Queue Linked for Analysis',
                                    'Queue all "linked" (downloaded but not yet analysed) cases for analysis? This will not re-download any orders.',
                                    queueLinkedForAnalysis
                                )}
                                disabled={processing}
                            >
                                Queue Linked for Analysis
                            </Button>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            <Row>
                <Col lg={12}>
                    <Card className="shadow-sm">
                        <Card.Header className="bg-success text-white">
                            <h5 className="mb-0">Bulk Order Processing</h5>
                        </Card.Header>
                        <Card.Body>
                            <Form>
                                <Row className="mb-3">
                                    <Col md={6}>
                                        <Form.Group>
                                            <Form.Label><strong>Select Statuses to Process</strong></Form.Label>
                                            <div>
                                                {['not_linked', 'order_failed', 'order_analysis_failed'].map(status => (
                                                    <Form.Check
                                                        key={status}
                                                        type="checkbox"
                                                        id={`status-${status}`}
                                                        label={statusLabels[status]}
                                                        checked={selectedStatuses.includes(status)}
                                                        onChange={() => handleStatusToggle(status)}
                                                        className="mb-2"
                                                    />
                                                ))}
                                            </div>
                                        </Form.Group>
                                    </Col>
                                    <Col md={3}>
                                        <Form.Group>
                                            <Form.Label><strong>Maximum Cases</strong></Form.Label>
                                            <Form.Control
                                                type="number"
                                                value={limit}
                                                onChange={(e) => setLimit(parseInt(e.target.value))}
                                                min="1"
                                                max="1000"
                                            />
                                            <Form.Text className="text-muted">
                                                Max: 1000
                                            </Form.Text>
                                        </Form.Group>
                                    </Col>
                                    <Col md={3}>
                                        <Form.Group>
                                            <Form.Label><strong>Days Back</strong></Form.Label>
                                            <Form.Control
                                                type="number"
                                                value={daysBack}
                                                onChange={(e) => setDaysBack(parseInt(e.target.value))}
                                                min="1"
                                                max="365"
                                            />
                                            <Form.Text className="text-muted">
                                                From last N days
                                            </Form.Text>
                                        </Form.Group>
                                    </Col>
                                </Row>

                                <Row>
                                    <Col>
                                        <Button
                                            variant="success"
                                            size="lg"
                                            onClick={startBulkProcessing}
                                            disabled={processing || selectedStatuses.length === 0}
                                            className="me-2"
                                        >
                                            {processing ? (
                                                <>
                                                    <span className="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                                                    Starting Processing...
                                                </>
                                            ) : (
                                                'Start Bulk Processing'
                                            )}
                                        </Button>
                                        <Button
                                            variant="outline-primary"
                                            onClick={() => { loadOverview(); loadQueueStatus(); }}
                                        >
                                            Refresh Status
                                        </Button>
                                    </Col>
                                </Row>

                                <Row className="mt-3">
                                    <Col>
                                        <Alert variant="info" className="mb-0">
                                            <strong>How it works:</strong> Bulk processing adds cases to an asynchronous background queue.
                                            Cases will be processed automatically in the background with {' '}
                                            <strong>5 parallel workers</strong>. The queue status updates every 5 seconds.
                                            After a successful fetch, cases are <strong>automatically
                                            queued for analysis</strong>; use <em>Queue Linked for Analysis</em> to manually
                                            unblock any that were stuck.
                                        </Alert>
                                    </Col>
                                </Row>
                            </Form>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
            </>
            )}
            {/* Confirmation Modal */}
            <Modal
                show={confirmState.show}
                onHide={() => setConfirmState(s => ({ ...s, show: false }))}
                centered
            >
                <Modal.Header closeButton>
                    <Modal.Title>{confirmState.title}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>{confirmState.body}</p>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setConfirmState(s => ({ ...s, show: false }))}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={handleConfirm}>
                        Confirm
                    </Button>
                </Modal.Footer>
            </Modal>
        </Container>
    );
};

export default AdminOrderManagement;
