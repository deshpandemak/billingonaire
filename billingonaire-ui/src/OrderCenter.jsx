import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Nav, Tab, Badge, Alert, Spinner, Button, Table, Form, Modal } from 'react-bootstrap';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const OrderCenter = () => {
    const [activeTab, setActiveTab] = useState('overview');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    
    // Overview Data
    const [overviewStats, setOverviewStats] = useState(null);
    const [queueStatus, setQueueStatus] = useState(null);
    const [recentActivity, setRecentActivity] = useState([]);
    
    // Manual Management Data
    const [casesWithoutOrders, setCasesWithoutOrders] = useState([]);
    const [selectedCase, setSelectedCase] = useState(null);
    const [orderStatus, setOrderStatus] = useState('not_present');
    const [orderLink, setOrderLink] = useState('');
    const [orderText, setOrderText] = useState('');
    
    // Auto Processing Data
    const [autoProcessing, setAutoProcessing] = useState(false);
    const [processResults, setProcessResults] = useState(null);
    const [searchResults, setSearchResults] = useState([]);
    const [searchIndexStats, setSearchIndexStats] = useState(null);
    
    // Analysis Data
    const [analysisHistory, setAnalysisHistory] = useState([]);
    const [analysisStats, setAnalysisStats] = useState(null);
    const [selectedFile, setSelectedFile] = useState(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analysisResult, setAnalysisResult] = useState(null);

    useEffect(() => {
        loadOverviewData();
        const interval = setInterval(loadOverviewData, 30000); // Refresh every 30 seconds
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        switch (activeTab) {
            case 'manual':
                loadCasesWithoutOrders();
                break;
            case 'auto':
                loadAutoProcessingData();
                break;
            case 'analysis':
                loadAnalysisData();
                break;
        }
    }, [activeTab]);

    const loadOverviewData = async () => {
        try {
            // Load comprehensive overview statistics
            const [stats, queue, activity] = await Promise.all([
                authenticatedFetchJSON('/orders/overview-stats'),
                authenticatedFetchJSON('/orders/queue-status').catch(() => ({ active: false, pending: 0 })),
                authenticatedFetchJSON('/orders/recent-activity?limit=10').catch(() => [])
            ]);
            
            setOverviewStats(stats);
            setQueueStatus(queue);
            setRecentActivity(activity);
        } catch (e) {
            console.error('Failed to load overview data:', e);
        }
    };

    const loadCasesWithoutOrders = async () => {
        setLoading(true);
        try {
            const result = await authenticatedFetchJSON('/orders/cases-without-orders?limit=100&offset=0');
            setCasesWithoutOrders(result.cases || []);
        } catch (e) {
            setError(`Failed to load cases: ${e.message}`);
        } finally {
            setLoading(false);
        }
    };

    const loadAutoProcessingData = async () => {
        try {
            const stats = await authenticatedFetchJSON('/auto-orders/search-index-stats');
            setSearchIndexStats(stats);
        } catch (e) {
            console.error('Failed to load auto processing data:', e);
        }
    };

    const loadAnalysisData = async () => {
        try {
            const [history, stats] = await Promise.all([
                authenticatedFetchJSON('/analysis-history?limit=20'),
                authenticatedFetchJSON('/analysis-stats')
            ]);
            setAnalysisHistory(history.analyses || []);
            setAnalysisStats(stats);
        } catch (e) {
            console.error('Failed to load analysis data:', e);
        }
    };

    const handleAutoProcess = async () => {
        setAutoProcessing(true);
        setError('');
        setSuccess('');

        try {
            const result = await authenticatedFetchJSON('/auto-orders/process-cases', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filters: {},
                    limit: 50
                })
            });

            if (result.success) {
                setProcessResults(result.results);
                setSuccess(`Processing completed! ${result.results.successful_downloads} downloads, ${result.results.successful_analyses} analyses successful.`);
                loadOverviewData(); // Refresh overview
                loadAutoProcessingData(); // Refresh auto processing stats
            } else {
                setError(result.error || 'Processing failed');
            }
        } catch (e) {
            setError(`Processing failed: ${e.message}`);
        } finally {
            setAutoProcessing(false);
        }
    };

    const OverviewTab = () => (
        <div>
            <Row className="mb-4">
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-primary">{overviewStats?.total_cases || 0}</h3>
                            <p className="text-muted mb-0">Total Cases</p>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-success">{overviewStats?.cases_with_orders || 0}</h3>
                            <p className="text-muted mb-0">With Orders</p>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-warning">{overviewStats?.cases_without_orders || 0}</h3>
                            <p className="text-muted mb-0">Pending Orders</p>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-info">{overviewStats?.analysis_completion_rate || 0}%</h3>
                            <p className="text-muted mb-0">Analysis Rate</p>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            <Row className="mb-4">
                <Col md={8}>
                    <Card>
                        <Card.Header className="d-flex justify-content-between align-items-center">
                            <h5 className="mb-0">Processing Queue Status</h5>
                            <Badge bg={queueStatus?.active ? 'success' : 'secondary'}>
                                {queueStatus?.active ? 'Active' : 'Idle'}
                            </Badge>
                        </Card.Header>
                        <Card.Body>
                            <div className="d-flex justify-content-between align-items-center mb-3">
                                <span>Pending Items: <strong>{queueStatus?.pending || 0}</strong></span>
                                <Button 
                                    variant="primary" 
                                    size="sm"
                                    onClick={handleAutoProcess}
                                    disabled={autoProcessing}
                                >
                                    {autoProcessing ? (
                                        <>
                                            <Spinner size="sm" className="me-2" />
                                            Processing...
                                        </>
                                    ) : (
                                        'Start Auto Processing'
                                    )}
                                </Button>
                            </div>
                            
                            {processResults && (
                                <Alert variant="info" className="mb-0">
                                    <strong>Last Processing Result:</strong>
                                    <br />✅ Downloads: {processResults.successful_downloads}
                                    <br />🔍 Analyses: {processResults.successful_analyses}
                                    <br />❌ Failed: {processResults.failed_downloads + processResults.failed_analyses}
                                </Alert>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={4}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Search Index Stats</h5>
                        </Card.Header>
                        <Card.Body>
                            <p className="mb-1">
                                <strong>Indexed Orders:</strong> {searchIndexStats?.total_indexed || 0}
                            </p>
                            <p className="mb-1">
                                <strong>Last Updated:</strong> {searchIndexStats?.last_updated || 'Never'}
                            </p>
                            <p className="mb-0">
                                <strong>Index Size:</strong> {searchIndexStats?.index_size || '0 KB'}
                            </p>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            <Card>
                <Card.Header>
                    <h5 className="mb-0">Recent Activity</h5>
                </Card.Header>
                <Card.Body>
                    {recentActivity.length > 0 ? (
                        <Table responsive size="sm">
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Action</th>
                                    <th>Case</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {recentActivity.map((activity, index) => (
                                    <tr key={index}>
                                        <td>{new Date(activity.timestamp).toLocaleString()}</td>
                                        <td>{activity.action}</td>
                                        <td>{activity.case_ref}</td>
                                        <td>
                                            <Badge bg={activity.status === 'success' ? 'success' : 'danger'}>
                                                {activity.status}
                                            </Badge>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    ) : (
                        <p className="text-muted text-center">No recent activity</p>
                    )}
                </Card.Body>
            </Card>
        </div>
    );

    const ManualManagementTab = () => (
        <div>
            <Card>
                <Card.Header className="d-flex justify-content-between align-items-center">
                    <h5 className="mb-0">Cases Without Orders ({casesWithoutOrders.length})</h5>
                    <Button variant="outline-primary" size="sm" onClick={loadCasesWithoutOrders}>
                        🔄 Refresh
                    </Button>
                </Card.Header>
                <Card.Body>
                    {loading ? (
                        <div className="text-center">
                            <Spinner />
                            <p className="mt-2">Loading cases...</p>
                        </div>
                    ) : casesWithoutOrders.length > 0 ? (
                        <Table responsive striped hover>
                            <thead>
                                <tr>
                                    <th>Case Ref</th>
                                    <th>Date</th>
                                    <th>Petitioner</th>
                                    <th>Respondent</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {casesWithoutOrders.slice(0, 20).map((caseItem, index) => (
                                    <tr key={index}>
                                        <td>{caseItem.case_ref}</td>
                                        <td>{caseItem.board_date}</td>
                                        <td>{caseItem.petitioner_lawyer}</td>
                                        <td>{caseItem.respondent_lawyer}</td>
                                        <td>
                                            <Button 
                                                variant="outline-primary" 
                                                size="sm"
                                                onClick={() => setSelectedCase(caseItem)}
                                            >
                                                Link Order
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    ) : (
                        <Alert variant="success" className="text-center">
                            🎉 All cases have orders linked!
                        </Alert>
                    )}
                </Card.Body>
            </Card>
        </div>
    );

    return (
        <Container fluid className="py-4">
            <Row>
                <Col>
                    <Card className="shadow-sm">
                        <Card.Header className="bg-primary text-white">
                            <h4 className="mb-0">⚖️ Order Management Center</h4>
                            <p className="mb-0">Unified order processing, analysis, and management</p>
                        </Card.Header>
                        <Card.Body className="p-0">
                            <Tab.Container activeKey={activeTab} onSelect={setActiveTab}>
                                <Nav variant="tabs" className="px-3 pt-3">
                                    <Nav.Item>
                                        <Nav.Link eventKey="overview">
                                            📊 Overview
                                            {queueStatus?.pending > 0 && (
                                                <Badge bg="warning" className="ms-2">{queueStatus.pending}</Badge>
                                            )}
                                        </Nav.Link>
                                    </Nav.Item>
                                    <Nav.Item>
                                        <Nav.Link eventKey="manual">
                                            🔗 Manual Linking
                                            {overviewStats?.cases_without_orders > 0 && (
                                                <Badge bg="warning" className="ms-2">{overviewStats.cases_without_orders}</Badge>
                                            )}
                                        </Nav.Link>
                                    </Nav.Item>
                                    <Nav.Item>
                                        <Nav.Link eventKey="auto">
                                            🤖 Auto Processing
                                            <Badge bg={autoProcessing ? 'success' : 'secondary'} className="ms-2">
                                                {autoProcessing ? 'Running' : 'Ready'}
                                            </Badge>
                                        </Nav.Link>
                                    </Nav.Item>
                                    <Nav.Item>
                                        <Nav.Link eventKey="analysis">
                                            🧠 AI Analysis
                                        </Nav.Link>
                                    </Nav.Item>
                                    <Nav.Item>
                                        <Nav.Link eventKey="analytics">
                                            📈 Analytics
                                        </Nav.Link>
                                    </Nav.Item>
                                </Nav>
                                
                                <div className="p-4">
                                    {error && (
                                        <Alert variant="danger" dismissible onClose={() => setError('')}>
                                            {error}
                                        </Alert>
                                    )}
                                    
                                    {success && (
                                        <Alert variant="success" dismissible onClose={() => setSuccess('')}>
                                            {success}
                                        </Alert>
                                    )}

                                    <Tab.Content>
                                        <Tab.Pane eventKey="overview">
                                            <OverviewTab />
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="manual">
                                            <ManualManagementTab />
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="auto">
                                            <div className="text-center">
                                                <h5>Auto Processing Features</h5>
                                                <p className="text-muted">Comprehensive auto processing interface coming soon...</p>
                                                <Button variant="primary" onClick={handleAutoProcess} disabled={autoProcessing}>
                                                    {autoProcessing ? 'Processing...' : 'Start Auto Processing'}
                                                </Button>
                                            </div>
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="analysis">
                                            <div className="text-center">
                                                <h5>AI Analysis Tools</h5>
                                                <p className="text-muted">AI-powered order analysis interface coming soon...</p>
                                            </div>
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="analytics">
                                            <div className="text-center">
                                                <h5>Order Analytics</h5>
                                                <p className="text-muted">Comprehensive analytics dashboard coming soon...</p>
                                            </div>
                                        </Tab.Pane>
                                    </Tab.Content>
                                </div>
                            </Tab.Container>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
        </Container>
    );
};

export default OrderCenter;