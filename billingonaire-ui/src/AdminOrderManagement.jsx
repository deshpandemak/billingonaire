import React, { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Card, Button, Form, Alert, Badge, ProgressBar, Table } from 'react-bootstrap';
import { auth } from './lib/firebase';

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
    const [loading, setLoading] = useState(false);
    const [processing, setProcessing] = useState(false);
    const [message, setMessage] = useState(null);
    const [selectedStatuses, setSelectedStatuses] = useState(['not_linked', 'order_failed']);
    const [limit, setLimit] = useState(100);
    const [daysBack, setDaysBack] = useState(30);

    const statusLabels = {
        'not_linked': 'Not Linked',
        'order_linked': 'Order Linked (Not Analysed)',
        'analysed': 'Linked & Analysed',
        'order_failed': 'Order Failed',
        'order_analysis_failed': 'Analysis Failed'
    };

    const statusVariants = {
        'not_linked': 'secondary',
        'order_linked': 'info',
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
        } catch (error) {
            console.error('Error loading overview:', error);
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
        } catch (error) {
            console.error('Error loading queue status:', error);
        }
    }, [currentUser]);

    useEffect(() => {
        if (!currentUser) return;
        
        loadOverview();
        loadQueueStatus();
        
        const interval = setInterval(() => {
            loadQueueStatus();
        }, 5000);
        
        return () => clearInterval(interval);
    }, [currentUser, loadOverview, loadQueueStatus]);

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
                    days_back: daysBack
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                setMessage({
                    type: 'success',
                    text: `${data.message}. Processing ${data.cases_queued} cases in background.`
                });
                
                // Update queue status immediately with response data
                if (data.queue_size !== undefined) {
                    setQueueStatus({
                        queue_size: data.queue_size,
                        processing_active: true,
                        status: 'active',
                        message: `Queue has ${data.queue_size} pending cases`
                    });
                }
                
                // Reload data after 2 seconds
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
            <Row className="mb-4">
                <Col>
                    <h2 className="mb-0">Admin Order Management</h2>
                    <p className="text-muted">Manage automatic order processing for all cases</p>
                </Col>
            </Row>

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
                                    <div className="mb-3">
                                        <h4 className="mb-0">{queueStatus.queue_size}</h4>
                                        <small className="text-muted">Cases in Queue</small>
                                    </div>
                                    <div className="mb-2">
                                        <Badge bg={queueStatus.processing_active ? 'success' : 'danger'}>
                                            {queueStatus.processing_active ? 'Active' : 'Inactive'}
                                        </Badge>
                                    </div>
                                    <p className="text-muted small mb-0">
                                        {queueStatus.message}
                                    </p>
                                </>
                            ) : (
                                <p className="text-muted mb-0">Loading...</p>
                            )}
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
                                            Cases will be processed automatically in the background. The queue status updates every 5 seconds. 
                                            Refresh the overview to see updated statistics after processing completes.
                                        </Alert>
                                    </Col>
                                </Row>
                            </Form>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
        </Container>
    );
};

export default AdminOrderManagement;
