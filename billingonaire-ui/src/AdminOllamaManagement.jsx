import React, { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Card, Button, Alert, Badge, Spinner, Table, Form } from 'react-bootstrap';
import { authenticatedFetchJSON } from './lib/api';
import { auth } from './lib/firebase';
import { onAuthStateChanged } from 'firebase/auth';
import './styles/professional.css';

const AdminOllamaManagement = () => {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  // Ollama Status
  const [health, setHealth] = useState(null);
  const [models, setModels] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Pull Model Form
  const [modelNameInput, setModelNameInput] = useState('llama3.1:8b');
  const [pullLoading, setPullLoading] = useState(false);

  const loadUserProfile = async () => {
    try {
      const profileData = await authenticatedFetchJSON('/user/profile');
      setProfile(profileData);

      if (profileData.role !== 'admin') {
        setError('Access denied. Administrator privileges required.');
        return;
      }
    } catch (error) {
      console.error('Error loading profile:', error);
      setError('Failed to load user profile');
    }
  };

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = await authenticatedFetchJSON('/admin/ollama/health');
      setHealth(data);
    } catch (error) {
      console.error('Error fetching health:', error);
      setError('Failed to fetch health status');
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const refreshModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      const data = await authenticatedFetchJSON('/admin/ollama/models');
      setModels(data);
    } catch (error) {
      console.error('Error fetching models:', error);
      setError('Failed to fetch models');
    } finally {
      setModelsLoading(false);
    }
  }, []);

  const handlePullModel = async () => {
    if (!modelNameInput.trim()) {
      setError('Please enter a model name');
      return;
    }

    setPullLoading(true);
    setError('');
    setSuccessMessage('');

    try {
      const url = `/admin/ollama-pull-model?model_name=${encodeURIComponent(modelNameInput.trim())}`;
      const result = await authenticatedFetchJSON(url, {
        method: 'POST',
      });

      setSuccessMessage(`✅ ${result.message}`);
      // Refresh models after pulling
      setTimeout(() => {
        refreshModels();
      }, 2000);
    } catch (error) {
      console.error('Error pulling model:', error);
      setError(`Failed to pull model: ${error.message}`);
    } finally {
      setPullLoading(false);
    }
  };

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setUser(user);
      if (user) {
        await loadUserProfile();
        // Initial load
        setTimeout(() => {
          refreshHealth();
          refreshModels();
        }, 500);
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, [refreshHealth, refreshModels]);

  // Auto-refresh health every 10 seconds
  useEffect(() => {
    if (!user) return;
    
    const interval = setInterval(() => {
      refreshHealth();
    }, 10000);

    return () => clearInterval(interval);
  }, [user, refreshHealth]);

  if (loading) {
    return (
      <Container className="container-professional py-5">
        <div className="text-center">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading...</span>
          </Spinner>
        </div>
      </Container>
    );
  }

  if (!user) {
    return (
      <Container className="container-professional py-5">
        <Alert variant="warning">Please log in to access Ollama management.</Alert>
      </Container>
    );
  }

  if (profile && profile.role !== 'admin') {
    return (
      <Container className="container-professional py-5">
        <Alert variant="danger">
          <h5>Access Denied</h5>
          <p>Administrator privileges are required to access Ollama management.</p>
        </Alert>
      </Container>
    );
  }

  if (!profile) {
    return (
      <Container className="container-professional py-5">
        <div className="text-center">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading...</span>
          </Spinner>
          <p className="mt-2">Loading admin profile...</p>
        </div>
      </Container>
    );
  }

  return (
    <Container className="container-professional py-5">
      <h1 className="mb-4">🦙 Ollama Model Management</h1>

      {error && (
        <Alert variant="danger" onClose={() => setError('')} dismissible>
          {error}
        </Alert>
      )}

      {successMessage && (
        <Alert variant="success" onClose={() => setSuccessMessage('')} dismissible>
          {successMessage}
        </Alert>
      )}

      {/* Health Status Card */}
      <Row className="mb-4">
        <Col lg={6}>
          <Card className="card-professional">
            <Card.Header className="card-header-professional">
              <div className="d-flex justify-content-between align-items-center">
                <h5 className="mb-0">🏥 Ollama Service Health</h5>
                <Button
                  size="sm"
                  variant="outline-primary"
                  onClick={refreshHealth}
                  disabled={healthLoading}
                >
                  {healthLoading ? (
                    <>
                      <Spinner animation="border" size="sm" className="me-2" />
                      Checking...
                    </>
                  ) : (
                    '🔄 Refresh'
                  )}
                </Button>
              </div>
            </Card.Header>
            <Card.Body>
              {health === null ? (
                <div className="text-center">
                  <Spinner animation="border" size="sm" />
                  <p className="mt-2">Loading health status...</p>
                </div>
              ) : (
                <>
                  <div className="mb-3">
                    <label className="form-label">Status</label>
                    <div>
                      {health.healthy ? (
                        <Badge bg="success" className="fs-6 py-2 px-3">
                          ✅ Healthy
                        </Badge>
                      ) : (
                        <Badge bg="danger" className="fs-6 py-2 px-3">
                          ❌ Unhealthy
                        </Badge>
                      )}
                    </div>
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Base URL</label>
                    <code className="d-block bg-light p-2 rounded">
                      {health.base_url || 'Not configured'}
                    </code>
                  </div>

                  <div className="mb-0">
                    <label className="form-label">Response Time</label>
                    <div>
                      <strong>{health.response_time_ms}ms</strong>
                    </div>
                  </div>

                  {health.status !== 'ok' && health.status !== '' && (
                    <Alert variant="warning" className="mt-3 mb-0">
                      <strong>Details:</strong> {health.status}
                    </Alert>
                  )}
                </>
              )}
            </Card.Body>
          </Card>
        </Col>

        {/* Pull Model Card */}
        <Col lg={6}>
          <Card className="card-professional">
            <Card.Header className="card-header-professional">
              <h5 className="mb-0">📥 Pull New Model</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted small">
                Enter a model name from Ollama library (e.g., llama3.1:8b, mistral, neural-chat)
              </p>

              <Form.Group className="mb-3">
                <Form.Label>Model Name</Form.Label>
                <Form.Control
                  type="text"
                  placeholder="e.g., llama3.1:8b"
                  value={modelNameInput}
                  onChange={(e) => setModelNameInput(e.target.value)}
                  disabled={pullLoading || !health?.healthy}
                />
                <Form.Text className="d-block mt-2 text-muted">
                  Popular models: llama3.1:8b, llama3.2, mistral, neural-chat, zephyr
                </Form.Text>
              </Form.Group>

              <Button
                variant="primary"
                className="w-100"
                onClick={handlePullModel}
                disabled={pullLoading || !health?.healthy}
              >
                {pullLoading ? (
                  <>
                    <Spinner animation="border" size="sm" className="me-2" />
                    Initiating Pull...
                  </>
                ) : (
                  '📥 Pull Model'
                )}
              </Button>

              {!health?.healthy && (
                <Alert variant="warning" className="mt-3 mb-0">
                  ⚠️ Ollama service is not healthy. Cannot pull models.
                </Alert>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {/* Models Table */}
      <Row>
        <Col>
          <Card className="card-professional">
            <Card.Header className="card-header-professional">
              <div className="d-flex justify-content-between align-items-center">
                <h5 className="mb-0">
                  📚 Available Models
                  {models?.models && (
                    <Badge bg="info" className="ms-2">
                      {models.models.length}
                    </Badge>
                  )}
                </h5>
                <Button
                  size="sm"
                  variant="outline-primary"
                  onClick={refreshModels}
                  disabled={modelsLoading}
                >
                  {modelsLoading ? (
                    <>
                      <Spinner animation="border" size="sm" className="me-2" />
                      Loading...
                    </>
                  ) : (
                    '🔄 Refresh'
                  )}
                </Button>
              </div>
            </Card.Header>
            <Card.Body>
              {models === null ? (
                <div className="text-center">
                  <Spinner animation="border" size="sm" />
                  <p className="mt-2">Loading models...</p>
                </div>
              ) : models.models && models.models.length > 0 ? (
                <>
                  <div className="mb-3">
                    <label className="form-label">
                      Configured Model for Billingonaire
                    </label>
                    <Badge bg="info" className="d-block fs-6 py-2 px-3">
                      {models.configured_model}
                    </Badge>
                  </div>

                  <div className="table-responsive">
                    <Table striped hover size="sm" className="mb-0">
                      <thead>
                        <tr>
                          <th>Model Name</th>
                          <th>Size</th>
                          <th>Format</th>
                          <th style={{ width: '150px' }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {models.models.map((model) => {
                          const isConfigured =
                            model.name === models.configured_model;
                          const sizeMB = (model.size / (1024 * 1024)).toFixed(0);
                          return (
                            <tr key={model.name} className={isConfigured ? 'table-info' : ''}>
                              <td>
                                <code>{model.name}</code>
                              </td>
                              <td>{sizeMB} MB</td>
                              <td className="text-muted small">{model.format || 'unknown'}</td>
                              <td>
                                {isConfigured ? (
                                  <Badge bg="success">✅ Configured</Badge>
                                ) : (
                                  <Badge bg="secondary">Available</Badge>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </Table>
                  </div>
                </>
              ) : (
                <Alert variant="warning" className="mb-0">
                  <strong>No models loaded</strong>
                  <p className="mb-0 mt-2">
                    Use the "Pull New Model" form above or check your Ollama configuration.
                  </p>
                </Alert>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {/* Configuration Info */}
      <Row className="mt-4">
        <Col>
          <Card className="card-professional bg-light">
            <Card.Header className="card-header-professional">
              <h6 className="mb-0">ℹ️ Configuration Info</h6>
            </Card.Header>
            <Card.Body>
              <dl className="row small mb-0">
                <dt className="col-sm-4">Ollama Endpoint:</dt>
                <dd className="col-sm-8">
                  <code>{health?.base_url || 'Not configured'}</code>
                </dd>

                <dt className="col-sm-4">Configured Model:</dt>
                <dd className="col-sm-8">
                  <code>{models?.configured_model || 'llama3.2'}</code>
                </dd>

                <dt className="col-sm-4">Service Status:</dt>
                <dd className="col-sm-8">
                  {health?.healthy ? (
                    <span>
                      <Badge bg="success" className="me-2">Online</Badge>
                      Response: {health?.response_time_ms}ms
                    </span>
                  ) : (
                    <span>
                      <Badge bg="danger">Offline</Badge>
                    </span>
                  )}
                </dd>

                <dt className="col-sm-4">Models Loaded:</dt>
                <dd className="col-sm-8">
                  {models ? `${models.models?.length || 0} model(s)` : 'Unknown'}
                </dd>
              </dl>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
};

export default AdminOllamaManagement;
