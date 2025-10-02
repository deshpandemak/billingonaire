import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Nav, Tab, Badge, Alert, Spinner, Button, Table, Form, Modal } from 'react-bootstrap';
import { authenticatedFetchJSON } from './lib/api';
import { auth } from './lib/firebase';
import './styles/professional.css';
import { getApiUrl } from './lib/api';

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
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchIndexStats, setSearchIndexStats] = useState(null);
    const [processFilters, setProcessFilters] = useState({
        case_type: '',
        case_year: '',
        date_from: '',
        date_to: '',
        limit: 50
    });
    const [searchFilters, setSearchFilters] = useState({
        petitioner_search: '',
        respondent_search: '',
        case_type: '',
        case_year: '',
        order_category: '',
        limit: 100
    });
    
    // Analysis Data
    const [analysisHistory, setAnalysisHistory] = useState([]);
    const [analysisStats, setAnalysisStats] = useState(null);
    const [selectedFile, setSelectedFile] = useState(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analysisResult, setAnalysisResult] = useState(null);
    const [analysisTab, setAnalysisTab] = useState('upload');

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

    const handleSearchOrders = async () => {
        setSearchLoading(true);
        setError('');

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
                setSuccess(`Found ${result.results.length} matching orders`);
            } else {
                setError(result.error || 'Search failed');
            }
        } catch (e) {
            setError(`Search failed: ${e.message}`);
        } finally {
            setSearchLoading(false);
        }
    };

    const handleFileSelect = (event) => {
        const file = event.target.files[0];
        if (file) {
            if (file.type !== 'application/pdf') {
                setError('Please select a PDF file');
                setSelectedFile(null);
                return;
            }
            setSelectedFile(file);
            setError('');
        }
    };

    const handleAnalyzeOrder = async () => {
        if (!selectedFile) {
            setError('Please select a PDF file to analyze');
            return;
        }

        setIsAnalyzing(true);
        setError('');
        setSuccess('');
        setAnalysisResult(null);

        try {
            const formData = new FormData();
            formData.append('file', selectedFile);

            const response = await fetch(getApiUrl('/analyze-order'), {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${await auth.currentUser.getIdToken()}`
                },
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Analysis failed');
            }

            const result = await response.json();
            setAnalysisResult(result);
            setSuccess(`Successfully analyzed ${result.filename}`);
            
            // Refresh history and stats
            loadAnalysisData();
            
            // Switch to results tab
            setAnalysisTab('results');
            
        } catch (e) {
            setError(`Analysis failed: ${e.message}`);
        } finally {
            setIsAnalyzing(false);
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

    const AutoProcessingTab = () => (
        <div>
            <Row className="mb-4">
                <Col md={8}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">🤖 Auto Processing Controls</h5>
                        </Card.Header>
                        <Card.Body>
                            <Row className="mb-3">
                                <Col md={6}>
                                    <Form.Group>
                                        <Form.Label>Case Type</Form.Label>
                                        <Form.Select 
                                            value={processFilters.case_type} 
                                            onChange={(e) => setProcessFilters({...processFilters, case_type: e.target.value})}
                                        >
                                            <option value="">All Types</option>
                                            <option value="WP">WP</option>
                                            <option value="CP">CP</option>
                                            <option value="IA">IA</option>
                                        </Form.Select>
                                    </Form.Group>
                                </Col>
                                <Col md={6}>
                                    <Form.Group>
                                        <Form.Label>Case Year</Form.Label>
                                        <Form.Select 
                                            value={processFilters.case_year} 
                                            onChange={(e) => setProcessFilters({...processFilters, case_year: e.target.value})}
                                        >
                                            <option value="">All Years</option>
                                            <option value="2025">2025</option>
                                            <option value="2024">2024</option>
                                            <option value="2023">2023</option>
                                        </Form.Select>
                                    </Form.Group>
                                </Col>
                            </Row>
                            <Row className="mb-3">
                                <Col md={6}>
                                    <Form.Group>
                                        <Form.Label>Date From</Form.Label>
                                        <Form.Control 
                                            type="date" 
                                            value={processFilters.date_from}
                                            onChange={(e) => setProcessFilters({...processFilters, date_from: e.target.value})}
                                        />
                                    </Form.Group>
                                </Col>
                                <Col md={6}>
                                    <Form.Group>
                                        <Form.Label>Date To</Form.Label>
                                        <Form.Control 
                                            type="date" 
                                            value={processFilters.date_to}
                                            onChange={(e) => setProcessFilters({...processFilters, date_to: e.target.value})}
                                        />
                                    </Form.Group>
                                </Col>
                            </Row>
                            <div className="d-flex gap-2">
                                <Button 
                                    variant="primary" 
                                    onClick={handleAutoProcess} 
                                    disabled={autoProcessing}
                                >
                                    {autoProcessing ? (
                                        <>
                                            <Spinner size="sm" className="me-2" />
                                            Processing...
                                        </>
                                    ) : (
                                        '🚀 Start Auto Processing'
                                    )}
                                </Button>
                                <Button variant="outline-secondary" onClick={loadAutoProcessingData}>
                                    🔄 Refresh Stats
                                </Button>
                            </div>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={4}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">📊 Processing Stats</h5>
                        </Card.Header>
                        <Card.Body>
                            {searchIndexStats ? (
                                <div>
                                    <p className="mb-2">
                                        <strong>Indexed Orders:</strong><br />
                                        {searchIndexStats.total_indexed_orders || 0}
                                    </p>
                                    <p className="mb-2">
                                        <strong>Categories:</strong>
                                    </p>
                                    {searchIndexStats.category_distribution && Object.entries(searchIndexStats.category_distribution).map(([category, count]) => (
                                        <Badge key={category} bg="info" className="me-1 mb-1">
                                            {category}: {count}
                                        </Badge>
                                    ))}
                                    <p className="mt-3 mb-0">
                                        <small className="text-muted">
                                            Last updated: {searchIndexStats.last_updated || 'Never'}
                                        </small>
                                    </p>
                                </div>
                            ) : (
                                <div className="text-center">
                                    <Spinner size="sm" />
                                    <p className="mt-2 mb-0">Loading stats...</p>
                                </div>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            <Card>
                <Card.Header>
                    <h5 className="mb-0">🔍 Order Search</h5>
                </Card.Header>
                <Card.Body>
                    <Row className="mb-3">
                        <Col md={4}>
                            <Form.Group>
                                <Form.Label>Petitioner Search</Form.Label>
                                <Form.Control 
                                    type="text" 
                                    value={searchFilters.petitioner_search}
                                    onChange={(e) => setSearchFilters({...searchFilters, petitioner_search: e.target.value})}
                                    placeholder="Search petitioner name..."
                                />
                            </Form.Group>
                        </Col>
                        <Col md={4}>
                            <Form.Group>
                                <Form.Label>Respondent Search</Form.Label>
                                <Form.Control 
                                    type="text" 
                                    value={searchFilters.respondent_search}
                                    onChange={(e) => setSearchFilters({...searchFilters, respondent_search: e.target.value})}
                                    placeholder="Search respondent name..."
                                />
                            </Form.Group>
                        </Col>
                        <Col md={4}>
                            <Form.Group>
                                <Form.Label>Order Category</Form.Label>
                                <Form.Select 
                                    value={searchFilters.order_category}
                                    onChange={(e) => setSearchFilters({...searchFilters, order_category: e.target.value})}
                                >
                                    <option value="">All Categories</option>
                                    <option value="DISPOSED_OFF">Disposed Off</option>
                                    <option value="ADJOURNED">Adjourned</option>
                                    <option value="HEARD_AND_ADJOURNED">Heard & Adjourned</option>
                                </Form.Select>
                            </Form.Group>
                        </Col>
                    </Row>
                    <Button 
                        variant="outline-primary" 
                        onClick={handleSearchOrders} 
                        disabled={searchLoading}
                    >
                        {searchLoading ? (
                            <>
                                <Spinner size="sm" className="me-2" />
                                Searching...
                            </>
                        ) : (
                            '🔍 Search Orders'
                        )}
                    </Button>

                    {searchResults.length > 0 && (
                        <div className="mt-4">
                            <h6>Search Results ({searchResults.length})</h6>
                            <Table responsive striped size="sm">
                                <thead>
                                    <tr>
                                        <th>Case Ref</th>
                                        <th>Date</th>
                                        <th>Category</th>
                                        <th>Petitioner</th>
                                        <th>Respondent</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {searchResults.slice(0, 10).map((result, index) => (
                                        <tr key={index}>
                                            <td>{result.case_ref}</td>
                                            <td>{result.order_date}</td>
                                            <td>
                                                <Badge bg={result.category === 'DISPOSED_OFF' ? 'success' : result.category === 'ADJOURNED' ? 'warning' : 'info'}>
                                                    {result.category}
                                                </Badge>
                                            </td>
                                            <td>{result.petitioner}</td>
                                            <td>{result.respondent}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </Table>
                        </div>
                    )}
                </Card.Body>
            </Card>
        </div>
    );

    const AnalysisTab = () => (
        <div>
            <Row className="mb-4">
                <Col>
                    <Nav variant="pills" className="mb-3">
                        <Nav.Item>
                            <Nav.Link 
                                active={analysisTab === 'upload'} 
                                onClick={() => setAnalysisTab('upload')}
                            >
                                📄 Upload & Analyze
                            </Nav.Link>
                        </Nav.Item>
                        <Nav.Item>
                            <Nav.Link 
                                active={analysisTab === 'results'} 
                                onClick={() => setAnalysisTab('results')}
                            >
                                📊 Results
                            </Nav.Link>
                        </Nav.Item>
                        <Nav.Item>
                            <Nav.Link 
                                active={analysisTab === 'history'} 
                                onClick={() => setAnalysisTab('history')}
                            >
                                📚 History
                            </Nav.Link>
                        </Nav.Item>
                    </Nav>
                </Col>
            </Row>

            {analysisTab === 'upload' && (
                <Card>
                    <Card.Header>
                        <h5 className="mb-0">🧠 AI Order Analysis</h5>
                    </Card.Header>
                    <Card.Body>
                        <Row>
                            <Col md={8}>
                                <Form.Group className="mb-3">
                                    <Form.Label>Select PDF Order Document</Form.Label>
                                    <Form.Control 
                                        type="file" 
                                        accept=".pdf"
                                        onChange={handleFileSelect}
                                    />
                                    <Form.Text className="text-muted">
                                        Upload a court order PDF for AI-powered analysis and categorization
                                    </Form.Text>
                                </Form.Group>
                                
                                {selectedFile && (
                                    <Alert variant="info">
                                        <strong>Selected file:</strong> {selectedFile.name}
                                        <br />
                                        <strong>Size:</strong> {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                                    </Alert>
                                )}

                                <Button 
                                    variant="primary" 
                                    onClick={handleAnalyzeOrder}
                                    disabled={!selectedFile || isAnalyzing}
                                >
                                    {isAnalyzing ? (
                                        <>
                                            <Spinner size="sm" className="me-2" />
                                            Analyzing...
                                        </>
                                    ) : (
                                        '🔍 Analyze Order'
                                    )}
                                </Button>
                            </Col>
                            <Col md={4}>
                                {analysisStats && (
                                    <Card>
                                        <Card.Header>
                                            <h6 className="mb-0">Analysis Statistics</h6>
                                        </Card.Header>
                                        <Card.Body>
                                            <p className="mb-1">
                                                <strong>Total Analyzed:</strong> {analysisStats.total_analyses || 0}
                                            </p>
                                            <p className="mb-1">
                                                <strong>Success Rate:</strong> {analysisStats.success_rate || 0}%
                                            </p>
                                            <p className="mb-0">
                                                <strong>Categories:</strong>
                                            </p>
                                            {analysisStats.category_distribution && Object.entries(analysisStats.category_distribution).map(([category, count]) => (
                                                <Badge key={category} bg="secondary" className="me-1 mb-1">
                                                    {category}: {count}
                                                </Badge>
                                            ))}
                                        </Card.Body>
                                    </Card>
                                )}
                            </Col>
                        </Row>
                    </Card.Body>
                </Card>
            )}

            {analysisTab === 'results' && analysisResult && (
                <Card>
                    <Card.Header>
                        <h5 className="mb-0">📊 Analysis Results</h5>
                    </Card.Header>
                    <Card.Body>
                        <Row>
                            <Col md={6}>
                                <h6>Document Information</h6>
                                <p><strong>Filename:</strong> {analysisResult.filename}</p>
                                <p><strong>Analysis Date:</strong> {new Date(analysisResult.analysis_date).toLocaleString()}</p>
                                <p><strong>Processing Time:</strong> {analysisResult.processing_time}s</p>
                            </Col>
                            <Col md={6}>
                                <h6>Classification Results</h6>
                                <p>
                                    <strong>Category:</strong> 
                                    <Badge 
                                        bg={analysisResult.category === 'DISPOSED_OFF' ? 'success' : analysisResult.category === 'ADJOURNED' ? 'warning' : 'info'}
                                        className="ms-2"
                                    >
                                        {analysisResult.category}
                                    </Badge>
                                </p>
                                <p><strong>Confidence:</strong> {Math.round(analysisResult.confidence * 100)}%</p>
                            </Col>
                        </Row>
                        {analysisResult.extracted_info && (
                            <div className="mt-3">
                                <h6>Extracted Information</h6>
                                <pre className="bg-light p-3 rounded">
                                    {JSON.stringify(analysisResult.extracted_info, null, 2)}
                                </pre>
                            </div>
                        )}
                    </Card.Body>
                </Card>
            )}

            {analysisTab === 'history' && (
                <Card>
                    <Card.Header>
                        <h5 className="mb-0">📚 Analysis History</h5>
                    </Card.Header>
                    <Card.Body>
                        {analysisHistory.length > 0 ? (
                            <Table responsive striped>
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Filename</th>
                                        <th>Category</th>
                                        <th>Confidence</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {analysisHistory.map((analysis, index) => (
                                        <tr key={index}>
                                            <td>{new Date(analysis.analysis_date).toLocaleDateString()}</td>
                                            <td>{analysis.filename}</td>
                                            <td>
                                                <Badge bg={analysis.category === 'DISPOSED_OFF' ? 'success' : analysis.category === 'ADJOURNED' ? 'warning' : 'info'}>
                                                    {analysis.category}
                                                </Badge>
                                            </td>
                                            <td>{Math.round(analysis.confidence * 100)}%</td>
                                            <td>
                                                <Badge bg={analysis.status === 'completed' ? 'success' : 'warning'}>
                                                    {analysis.status}
                                                </Badge>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </Table>
                        ) : (
                            <Alert variant="info" className="text-center">
                                No analysis history available. Upload and analyze order documents to see history here.
                            </Alert>
                        )}
                    </Card.Body>
                </Card>
            )}
        </div>
    );

    const AnalyticsTab = () => (
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
                            <p className="text-muted mb-0">Orders Processed</p>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-info">{searchIndexStats?.total_indexed_orders || 0}</h3>
                            <p className="text-muted mb-0">Indexed Orders</p>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={3}>
                    <Card className="text-center">
                        <Card.Body>
                            <h3 className="text-warning">{analysisStats?.total_analyses || 0}</h3>
                            <p className="text-muted mb-0">AI Analyses</p>
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            <Row>
                <Col md={6}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Processing Efficiency</h5>
                        </Card.Header>
                        <Card.Body>
                            <div className="mb-3">
                                <div className="d-flex justify-content-between">
                                    <span>Order Processing Rate</span>
                                    <span>{overviewStats?.analysis_completion_rate || 0}%</span>
                                </div>
                                <div className="progress">
                                    <div 
                                        className="progress-bar bg-success" 
                                        style={{width: `${overviewStats?.analysis_completion_rate || 0}%`}}
                                    ></div>
                                </div>
                            </div>
                            <div className="mb-3">
                                <div className="d-flex justify-content-between">
                                    <span>AI Analysis Success Rate</span>
                                    <span>{analysisStats?.success_rate || 0}%</span>
                                </div>
                                <div className="progress">
                                    <div 
                                        className="progress-bar bg-info" 
                                        style={{width: `${analysisStats?.success_rate || 0}%`}}
                                    ></div>
                                </div>
                            </div>
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={6}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Order Categories Distribution</h5>
                        </Card.Header>
                        <Card.Body>
                            {searchIndexStats?.category_distribution ? (
                                Object.entries(searchIndexStats.category_distribution).map(([category, count]) => (
                                    <div key={category} className="mb-2">
                                        <div className="d-flex justify-content-between">
                                            <span>{category.replace(/_/g, ' ')}</span>
                                            <span>{count}</span>
                                        </div>
                                        <div className="progress" style={{height: '8px'}}>
                                            <div 
                                                className="progress-bar" 
                                                style={{
                                                    width: `${(count / Object.values(searchIndexStats.category_distribution).reduce((a, b) => a + b, 0)) * 100}%`,
                                                    backgroundColor: category === 'DISPOSED_OFF' ? '#28a745' : category === 'ADJOURNED' ? '#ffc107' : '#17a2b8'
                                                }}
                                            ></div>
                                        </div>
                                    </div>
                                ))
                            ) : (
                                <p className="text-muted">No category data available</p>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
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
                                            <AutoProcessingTab />
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="analysis">
                                            <AnalysisTab />
                                        </Tab.Pane>
                                        <Tab.Pane eventKey="analytics">
                                            <AnalyticsTab />
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