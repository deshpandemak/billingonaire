import React, { useState, useEffect } from 'react';
import { Container, Card, Button, Form, Alert, Table, Badge, Spinner, Row, Col } from 'react-bootstrap';
import { authenticatedFetchJSON, authenticatedFetch } from './lib/api';
import './styles/professional.css';

const OrderAnalysis = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [analysisStats, setAnalysisStats] = useState(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [activeTab, setActiveTab] = useState('upload');

  useEffect(() => {
    loadAnalysisHistory();
    loadAnalysisStats();
  }, []);

  const loadAnalysisHistory = async () => {
    try {
      const result = await authenticatedFetchJSON('/analysis-history?limit=20');
      setAnalysisHistory(result.analyses || []);
    } catch (e) {
      console.error('Failed to load analysis history:', e);
    }
  };

  const loadAnalysisStats = async () => {
    try {
      const result = await authenticatedFetchJSON('/analysis-stats');
      setAnalysisStats(result);
    } catch (e) {
      console.error('Failed to load analysis stats:', e);
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

      const response = await authenticatedFetch('/analyze-order', {
        method: 'POST',
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
      loadAnalysisHistory();
      loadAnalysisStats();
      
      // Switch to results tab
      setActiveTab('results');
      
    } catch (e) {
      setError(`Analysis failed: ${e.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getCategoryBadgeVariant = (category) => {
    switch (category) {
      case 'DISPOSED_OFF': return 'success';
      case 'ADJOURNED': return 'warning';
      case 'HEARD_AND_ADJOURNED': return 'info';
      default: return 'secondary';
    }
  };

  const getCategoryDisplayName = (category) => {
    switch (category) {
      case 'DISPOSED_OFF': return 'Disposed Off';
      case 'ADJOURNED': return 'Adjourned';
      case 'HEARD_AND_ADJOURNED': return 'Heard & Adjourned';
      default: return category;
    }
  };

  const formatConfidence = (confidence) => {
    return `${Math.round(confidence * 100)}%`;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    try {
      return new Date(dateStr).toLocaleDateString();
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">⚖️ AI-Powered Order Document Analysis</h1>
        <p className="dashboard-subtitle">
          Automatically categorize court orders and extract key information using advanced machine learning
        </p>
      </div>

      {/* Navigation Tabs */}
      <div className="card-professional" style={{ marginBottom: 'var(--spacing-lg)' }}>
        <div className="card-body" style={{ padding: 'var(--spacing-md)' }}>
          <div style={{ display: 'flex', gap: 'var(--spacing-md)', borderBottom: '1px solid var(--gray-200)', paddingBottom: 'var(--spacing-md)' }}>
            <button 
              className={`btn-professional ${activeTab === 'upload' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('upload')}
              style={{ fontSize: '0.875rem' }}
            >
              📄 Upload & Analyze
            </button>
            <button 
              className={`btn-professional ${activeTab === 'results' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('results')}
              style={{ fontSize: '0.875rem' }}
            >
              📊 Results
            </button>
            <button 
              className={`btn-professional ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('history')}
              style={{ fontSize: '0.875rem' }}
            >
              📚 History
            </button>
            <button 
              className={`btn-professional ${activeTab === 'stats' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('stats')}
              style={{ fontSize: '0.875rem' }}
            >
              📈 Statistics
            </button>
          </div>
        </div>
      </div>

      {/* Upload Tab */}
      {activeTab === 'upload' && (
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📤 Upload Order Document</h2>
          </div>
          <div className="card-body">
            <Form>
              <Form.Group className="form-group">
                <Form.Label className="form-label">Select Court Order PDF</Form.Label>
                <Form.Control
                  type="file"
                  accept=".pdf"
                  onChange={handleFileSelect}
                  className="form-control"
                />
                <Form.Text className="text-muted">
                  Upload a PDF file containing a court order for AI-powered analysis
                </Form.Text>
              </Form.Group>

              {selectedFile && (
                <Alert variant="info" className="mt-3">
                  <strong>Selected File:</strong> {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
                </Alert>
              )}

              <div style={{ marginTop: 'var(--spacing-lg)' }}>
                <Button
                  className="btn-professional btn-primary"
                  onClick={handleAnalyzeOrder}
                  disabled={!selectedFile || isAnalyzing}
                  style={{ minWidth: '200px' }}
                >
                  {isAnalyzing ? (
                    <>
                      <Spinner size="sm" className="me-2" />
                      Analyzing Document...
                    </>
                  ) : (
                    '🧠 Analyze Order Document'
                  )}
                </Button>
              </div>
            </Form>

            {error && (
              <Alert variant="danger" className="mt-3">
                {error}
              </Alert>
            )}

            {success && (
              <Alert variant="success" className="mt-3">
                {success}
              </Alert>
            )}
          </div>
        </div>
      )}

      {/* Results Tab */}
      {activeTab === 'results' && analysisResult && (
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📋 Analysis Results</h2>
            <Badge bg={getCategoryBadgeVariant(analysisResult.order_category)} style={{ fontSize: '1rem' }}>
              {getCategoryDisplayName(analysisResult.order_category)}
            </Badge>
          </div>
          <div className="card-body">
            <Row>
              <Col md={6}>
                <div className="mb-4">
                  <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                    📊 Classification
                  </h4>
                  <Table striped bordered hover className="professional-table">
                    <tbody>
                      <tr>
                        <td><strong>Order Category</strong></td>
                        <td>
                          <Badge bg={getCategoryBadgeVariant(analysisResult.order_category)}>
                            {getCategoryDisplayName(analysisResult.order_category)}
                          </Badge>
                        </td>
                      </tr>
                      <tr>
                        <td><strong>Confidence</strong></td>
                        <td>{formatConfidence(analysisResult.category_confidence)}</td>
                      </tr>
                      {analysisResult.order_date && (
                        <tr>
                          <td><strong>Order Date</strong></td>
                          <td>{analysisResult.order_date}</td>
                        </tr>
                      )}
                      <tr>
                        <td><strong>Next Hearing Date</strong></td>
                        <td>{analysisResult.next_hearing_date || 'Not specified'}</td>
                      </tr>
                      {analysisResult.disposal_reason && (
                        <tr>
                          <td><strong>Disposal Reason</strong></td>
                          <td>{analysisResult.disposal_reason}</td>
                        </tr>
                      )}
                    </tbody>
                  </Table>
                </div>
              </Col>
              <Col md={6}>
                <div className="mb-4">
                  <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                    📈 Document Structure
                  </h4>
                  <Table striped bordered hover className="professional-table">
                    <tbody>
                      <tr>
                        <td><strong>Document Type</strong></td>
                        <td>
                          <Badge bg={analysisResult.document_structure?.type === 'COMPLETE_ORDER' ? 'success' : 
                                     analysisResult.document_structure?.type === 'ADJOURNMENT_ONLY' ? 'warning' : 'secondary'}>
                            {analysisResult.document_structure?.type || 'UNKNOWN'}
                          </Badge>
                        </td>
                      </tr>
                      <tr>
                        <td><strong>Total Cases</strong></td>
                        <td>{analysisResult.summary?.total_cases || 0}</td>
                      </tr>
                      <tr>
                        <td><strong>Has Case Numbers</strong></td>
                        <td>{analysisResult.document_structure?.has_case_numbers ? '✅' : '❌'}</td>
                      </tr>
                      <tr>
                        <td><strong>Has Parties</strong></td>
                        <td>{analysisResult.document_structure?.has_parties ? '✅' : '❌'}</td>
                      </tr>
                      <tr>
                        <td><strong>Has Advocates</strong></td>
                        <td>{analysisResult.document_structure?.has_advocates ? '✅' : '❌'}</td>
                      </tr>
                    </tbody>
                  </Table>
                </div>
              </Col>
            </Row>

            {/* Tabular Format Data - Primary Display */}
            {analysisResult.tabular_data && analysisResult.tabular_data.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  📊 Case Analysis - Tabular Format
                </h4>
                <Table striped bordered hover className="professional-table" responsive>
                  <thead>
                    <tr>
                      <th>Case Type</th>
                      <th>Case Number</th>
                      <th>Year</th>
                      <th>Date</th>
                      <th>Petitioner</th>
                      <th>Respondent</th>
                      <th>AGP/GP/Addl GP/B'Pnl</th>
                      <th>Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisResult.tabular_data.map((row, index) => (
                      <tr key={index}>
                        <td>{row.case_type}</td>
                        <td><strong>{row.case_number}</strong></td>
                        <td>{row.year}</td>
                        <td>{row.date}</td>
                        <td>{row.petitioner}</td>
                        <td>{row.respondent}</td>
                        <td>
                          <Badge bg="info" style={{ fontSize: '0.75rem' }}>
                            {row.agp_gp_addl_gp_bpnl || 'None'}
                          </Badge>
                        </td>
                        <td>
                          <Badge bg={getCategoryBadgeVariant(row.category)}>
                            {getCategoryDisplayName(row.category)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}

            {/* Enhanced Case-by-Case Information (Fallback) */}
            {(!analysisResult.tabular_data || analysisResult.tabular_data.length === 0) && analysisResult.cases && analysisResult.cases.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  ⚖️ Case-by-Case Analysis
                </h4>
                {analysisResult.cases.map((caseInfo, index) => (
                  <div key={index} className="mb-3" style={{ border: '1px solid var(--gray-200)', borderRadius: '8px', padding: 'var(--spacing-md)' }}>
                    <h5 style={{ color: 'var(--secondary-color)', marginBottom: 'var(--spacing-sm)' }}>
                      📋 {caseInfo.case_number || `Case ${index + 1}`}
                    </h5>
                    <Row>
                      <Col md={3}>
                        <div>
                          <strong>Petitioners:</strong>
                          <ul style={{ marginTop: '0.5rem', marginBottom: '0' }}>
                            {caseInfo.petitioners && caseInfo.petitioners.length > 0 ? 
                              caseInfo.petitioners.map((petitioner, i) => (
                                <li key={i} style={{ fontSize: '0.875rem' }}>{petitioner}</li>
                              )) :
                              <li style={{ fontSize: '0.875rem', color: 'var(--gray-500)' }}>None found</li>
                            }
                          </ul>
                        </div>
                      </Col>
                      <Col md={3}>
                        <div>
                          <strong>Respondents:</strong>
                          <ul style={{ marginTop: '0.5rem', marginBottom: '0' }}>
                            {caseInfo.respondents && caseInfo.respondents.length > 0 ? 
                              caseInfo.respondents.map((respondent, i) => (
                                <li key={i} style={{ fontSize: '0.875rem' }}>{respondent}</li>
                              )) :
                              <li style={{ fontSize: '0.875rem', color: 'var(--gray-500)' }}>None found</li>
                            }
                          </ul>
                        </div>
                      </Col>
                      <Col md={3}>
                        <div>
                          <strong>AGP Names:</strong>
                          <ul style={{ marginTop: '0.5rem', marginBottom: '0' }}>
                            {caseInfo.agp_names && caseInfo.agp_names.length > 0 ? 
                              caseInfo.agp_names.map((agp, i) => (
                                <li key={i} style={{ fontSize: '0.875rem' }}>
                                  <Badge bg="info" style={{ fontSize: '0.75rem' }}>{agp}</Badge>
                                </li>
                              )) :
                              <li style={{ fontSize: '0.875rem', color: 'var(--gray-500)' }}>None found</li>
                            }
                          </ul>
                        </div>
                      </Col>
                      <Col md={3}>
                        <div>
                          <strong>Other Advocates:</strong>
                          <ul style={{ marginTop: '0.5rem', marginBottom: '0' }}>
                            {caseInfo.advocates && caseInfo.advocates.length > 0 ? 
                              caseInfo.advocates.map((advocate, i) => (
                                <li key={i} style={{ fontSize: '0.875rem' }}>{advocate}</li>
                              )) :
                              <li style={{ fontSize: '0.875rem', color: 'var(--gray-500)' }}>None found</li>
                            }
                          </ul>
                        </div>
                      </Col>
                    </Row>
                  </div>
                ))}
              </div>
            )}

            {/* Petitioners */}
            {analysisResult.petitioners && analysisResult.petitioners.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  👥 Petitioners
                </h4>
                <Table striped bordered hover className="professional-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisResult.petitioners.map((petitioner, index) => (
                      <tr key={index}>
                        <td>{petitioner.name}</td>
                        <td>{formatConfidence(petitioner.confidence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}

            {/* Respondents */}
            {analysisResult.respondents && analysisResult.respondents.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  🏛️ Respondents
                </h4>
                <Table striped bordered hover className="professional-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisResult.respondents.map((respondent, index) => (
                      <tr key={index}>
                        <td>{respondent.name}</td>
                        <td>{formatConfidence(respondent.confidence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}

            {/* AGP Names */}
            {analysisResult.agp_names && analysisResult.agp_names.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  ⚖️ AGP Names
                </h4>
                <Table striped bordered hover className="professional-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisResult.agp_names.map((agp, index) => (
                      <tr key={index}>
                        <td>{agp.name}</td>
                        <td><Badge variant="secondary">{agp.type}</Badge></td>
                        <td>{formatConfidence(agp.confidence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}

            {/* Key Phrases */}
            {analysisResult.key_phrases && analysisResult.key_phrases.length > 0 && (
              <div className="mb-4">
                <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                  🔑 Key Phrases
                </h4>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-sm)' }}>
                  {analysisResult.key_phrases.map((phrase, index) => (
                    <Badge key={index} bg="info" style={{ fontSize: '0.875rem' }}>
                      {phrase}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📚 Analysis History</h2>
          </div>
          <div className="card-body">
            {analysisHistory.length === 0 ? (
              <Alert variant="info">
                No analysis history found. Upload and analyze your first order document to get started.
              </Alert>
            ) : (
              <Table striped bordered hover className="professional-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Category</th>
                    <th>Confidence</th>
                    <th>Analyzed On</th>
                    <th>Entities</th>
                  </tr>
                </thead>
                <tbody>
                  {analysisHistory.map((analysis, index) => (
                    <tr key={index}>
                      <td>{analysis.filename}</td>
                      <td>
                        <Badge bg={getCategoryBadgeVariant(analysis.order_category)}>
                          {getCategoryDisplayName(analysis.order_category)}
                        </Badge>
                      </td>
                      <td>{formatConfidence(analysis.category_confidence)}</td>
                      <td>{formatDate(analysis.analysis_timestamp)}</td>
                      <td>
                        <small>
                          P: {analysis.petitioners?.length || 0} | 
                          R: {analysis.respondents?.length || 0} | 
                          AGP: {analysis.agp_names?.length || 0}
                        </small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </div>
        </div>
      )}

      {/* Statistics Tab */}
      {activeTab === 'stats' && (
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📈 Analysis Statistics</h2>
          </div>
          <div className="card-body">
            {analysisStats ? (
              <Row>
                <Col md={6}>
                  <div className="mb-4">
                    <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                      📊 Overall Statistics
                    </h4>
                    <Table striped bordered hover className="professional-table">
                      <tbody>
                        <tr>
                          <td><strong>Total Analyses</strong></td>
                          <td>{analysisStats.total_analyses}</td>
                        </tr>
                        <tr>
                          <td><strong>Average Confidence</strong></td>
                          <td>{formatConfidence(analysisStats.avg_confidence)}</td>
                        </tr>
                        <tr>
                          <td><strong>Recent Analyses (30 days)</strong></td>
                          <td>{analysisStats.recent_analyses}</td>
                        </tr>
                      </tbody>
                    </Table>
                  </div>
                </Col>
                <Col md={6}>
                  <div className="mb-4">
                    <h4 style={{ color: 'var(--primary-color)', marginBottom: 'var(--spacing-md)' }}>
                      📋 Category Distribution
                    </h4>
                    <Table striped bordered hover className="professional-table">
                      <tbody>
                        <tr>
                          <td><strong>Disposed Off</strong></td>
                          <td>{analysisStats.category_distribution.DISPOSED_OFF}</td>
                        </tr>
                        <tr>
                          <td><strong>Adjourned</strong></td>
                          <td>{analysisStats.category_distribution.ADJOURNED}</td>
                        </tr>
                        <tr>
                          <td><strong>Heard & Adjourned</strong></td>
                          <td>{analysisStats.category_distribution.HEARD_AND_ADJOURNED}</td>
                        </tr>
                      </tbody>
                    </Table>
                  </div>
                </Col>
              </Row>
            ) : (
              <Alert variant="info">
                Loading statistics...
              </Alert>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default OrderAnalysis;