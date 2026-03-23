import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Container,
  Form,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap';
import { onAuthStateChanged } from 'firebase/auth';
import { authenticatedFetchJSON } from './lib/api';
import { auth } from './lib/firebase';
import './styles/professional.css';

const DEFAULT_SCRAPER_FORM = {
  provider: 'ollama_first',
  allow_firecrawl_fallback: true,
  ollama_base_url: 'http://localhost:11434',
  ollama_model: 'llama3.2',
  ollama_timeout_seconds: 20,
};

const DEFAULT_PROBE_FORM = {
  case_ref: 'WP/3373/2025',
  date: '',
  bench: 'mumbai',
};

const DEFAULT_ORDER_LINKS_FORM = {
  case_ref: 'WP/3373/2025',
  date: '',
  bench: 'mumbai',
};

const AdminOllamaManagement = () => {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [health, setHealth] = useState(null);
  const [models, setModels] = useState(null);
  const [scraperStatus, setScraperStatus] = useState(null);
  const [scraperForm, setScraperForm] = useState(DEFAULT_SCRAPER_FORM);
  const [probeForm, setProbeForm] = useState(DEFAULT_PROBE_FORM);
  const [probeResult, setProbeResult] = useState(null);
  const [orderLinksForm, setOrderLinksForm] = useState(DEFAULT_ORDER_LINKS_FORM);
  const [orderLinksResult, setOrderLinksResult] = useState(null);
  const [orderLinksLoading, setOrderLinksLoading] = useState(false);
  const [orderAnalysisUrl, setOrderAnalysisUrl] = useState('');
  const [orderAnalysisPersist, setOrderAnalysisPersist] = useState(false);
  const [orderAnalysisResult, setOrderAnalysisResult] = useState(null);

  const [healthLoading, setHealthLoading] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [scraperLoading, setScraperLoading] = useState(false);
  const [scraperSaving, setScraperSaving] = useState(false);
  const [pullLoading, setPullLoading] = useState(false);
  const [probeLoading, setProbeLoading] = useState(false);
  const [orderAnalysisLoading, setOrderAnalysisLoading] = useState(false);

  const [modelNameInput, setModelNameInput] = useState('llama3.1:8b');

  const loadUserProfile = useCallback(async () => {
    try {
      const profileData = await authenticatedFetchJSON('/user/profile');
      setProfile(profileData);
      if (profileData.role !== 'admin') {
        setError('Access denied. Administrator privileges required.');
      }
    } catch (loadError) {
      console.error('Error loading profile:', loadError);
      setError('Failed to load user profile');
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = await authenticatedFetchJSON('/admin/ollama/health');
      setHealth(data);
    } catch (requestError) {
      console.error('Error fetching health:', requestError);
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
    } catch (requestError) {
      console.error('Error fetching models:', requestError);
      setError('Failed to fetch models');
    } finally {
      setModelsLoading(false);
    }
  }, []);

  const refreshScraperStatus = useCallback(async () => {
    setScraperLoading(true);
    try {
      const data = await authenticatedFetchJSON('/scraper/status');
      setScraperStatus(data);
      setScraperForm({
        provider: data.provider || DEFAULT_SCRAPER_FORM.provider,
        allow_firecrawl_fallback:
          data.allow_firecrawl_fallback ?? DEFAULT_SCRAPER_FORM.allow_firecrawl_fallback,
        ollama_base_url:
          data.ollama?.base_url || DEFAULT_SCRAPER_FORM.ollama_base_url,
        ollama_model: data.ollama?.model || DEFAULT_SCRAPER_FORM.ollama_model,
        ollama_timeout_seconds:
          data.ollama?.timeout_seconds || DEFAULT_SCRAPER_FORM.ollama_timeout_seconds,
      });
    } catch (requestError) {
      console.error('Error fetching scraper status:', requestError);
      setError('Failed to fetch scraper configuration');
    } finally {
      setScraperLoading(false);
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
      setSuccessMessage(result.message || 'Model pull initiated');
      window.setTimeout(() => {
        refreshModels();
      }, 2000);
    } catch (requestError) {
      console.error('Error pulling model:', requestError);
      setError(`Failed to pull model: ${requestError.message}`);
    } finally {
      setPullLoading(false);
    }
  };

  const handleScraperFormChange = (field, value) => {
    setScraperForm((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleSaveScraperConfig = async () => {
    setScraperSaving(true);
    setError('');
    setSuccessMessage('');

    try {
      const params = new URLSearchParams();
      params.set('provider', scraperForm.provider);
      params.set(
        'allow_firecrawl_fallback',
        String(scraperForm.allow_firecrawl_fallback)
      );
      params.set('ollama_base_url', scraperForm.ollama_base_url.trim());
      params.set('ollama_model', scraperForm.ollama_model.trim());
      params.set(
        'ollama_timeout_seconds',
        String(Number(scraperForm.ollama_timeout_seconds) || 20)
      );

      const result = await authenticatedFetchJSON(`/scraper/configure?${params.toString()}`, {
        method: 'POST',
      });
      setScraperStatus(result);
      setSuccessMessage('Scraper configuration updated');
      await refreshHealth();
      await refreshModels();
    } catch (requestError) {
      console.error('Error updating scraper config:', requestError);
      setError(`Failed to update scraper config: ${requestError.message}`);
    } finally {
      setScraperSaving(false);
    }
  };

  const handleProbeCase = async () => {
    if (!probeForm.case_ref.trim()) {
      setError('Please enter a case reference to test');
      return;
    }

    setProbeLoading(true);
    setError('');
    setSuccessMessage('');
    setProbeResult(null);

    try {
      const result = await authenticatedFetchJSON('/admin/ollama/test-case', {
        method: 'POST',
        body: JSON.stringify({
          case_ref: probeForm.case_ref.trim(),
          date: probeForm.date.trim() || null,
          bench: probeForm.bench,
        }),
      });
      setProbeResult(result);
      if (result && result.ok === false) {
        setError(`Probe returned an error: ${result.error || 'Unknown error'}`);
      } else {
        setSuccessMessage('Case probe completed');
      }
    } catch (requestError) {
      console.error('Error probing case:', requestError);
      setError(`Failed to probe case: ${requestError.message}`);
    } finally {
      setProbeLoading(false);
    }
  };

  const handleFetchOrderLinks = async () => {
    if (!orderLinksForm.case_ref.trim()) {
      setError('Please enter a case reference');
      return;
    }

    setOrderLinksLoading(true);
    setError('');
    setSuccessMessage('');
    setOrderLinksResult(null);

    try {
      const params = new URLSearchParams({ case_ref: orderLinksForm.case_ref.trim() });
      if (orderLinksForm.date) params.set('date', orderLinksForm.date);
      params.set('bench', orderLinksForm.bench);
      const data = await authenticatedFetchJSON(`/court/case-orders?${params.toString()}`);
      setOrderLinksResult(data);
      const count = (data.court_orders || data.orders || []).length;
      setSuccessMessage(`Found ${count} order link(s) for ${orderLinksForm.case_ref}`);
    } catch (requestError) {
      console.error('Error fetching order links:', requestError);
      setError(`Failed to fetch order links: ${requestError.message}`);
    } finally {
      setOrderLinksLoading(false);
    }
  };

  const handleAnalyzeOrderLink = async () => {
    if (!orderAnalysisUrl.trim()) {
      setError('Please enter an order PDF link');
      return;
    }

    setOrderAnalysisLoading(true);
    setError('');
    setSuccessMessage('');
    setOrderAnalysisResult(null);

    try {
      const result = await authenticatedFetchJSON('/admin/order-analysis/from-link', {
        method: 'POST',
        body: JSON.stringify({
          url: orderAnalysisUrl.trim(),
          persist_result: orderAnalysisPersist,
        }),
      });
      setOrderAnalysisResult(result);
      setSuccessMessage('Order analysis completed');
    } catch (requestError) {
      console.error('Error analyzing order link:', requestError);
      setError(`Failed to analyze order link: ${requestError.message}`);
    } finally {
      setOrderAnalysisLoading(false);
    }
  };

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (authUser) => {
      setUser(authUser);
      if (authUser) {
        await loadUserProfile();
        await Promise.all([
          refreshHealth(),
          refreshModels(),
          refreshScraperStatus(),
        ]);
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, [loadUserProfile, refreshHealth, refreshModels, refreshScraperStatus]);

  useEffect(() => {
    if (!user) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      refreshHealth();
    }, 10000);

    return () => window.clearInterval(interval);
  }, [refreshHealth, user]);

  const renderJsonBlock = (title, value) => (
    <Card className="card-professional mt-3">
      <Card.Header className="card-header-professional">
        <h6 className="mb-0">{title}</h6>
      </Card.Header>
      <Card.Body>
        <pre
          className="bg-light border rounded p-3 small mb-0"
          style={{ maxHeight: '320px', overflow: 'auto' }}
        >
          {JSON.stringify(value, null, 2)}
        </pre>
      </Card.Body>
    </Card>
  );

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
      <p className="text-muted mb-4">
        Monitor Ollama, tweak the court scraper at runtime, test a case lookup,
        and analyze an order PDF directly from a link.
      </p>

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

      <Row className="mb-4">
        <Col lg={6}>
          <Card className="card-professional h-100">
            <Card.Header className="card-header-professional d-flex justify-content-between align-items-center">
              <h5 className="mb-0">🏥 Ollama Service Health</h5>
              <Button
                size="sm"
                variant="outline-primary"
                onClick={refreshHealth}
                disabled={healthLoading}
              >
                {healthLoading ? 'Checking...' : 'Refresh'}
              </Button>
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
                    <div className="form-label">Status</div>
                    {health.healthy ? (
                      <Badge bg="success" className="fs-6 py-2 px-3">Healthy</Badge>
                    ) : (
                      <Badge bg="danger" className="fs-6 py-2 px-3">Unhealthy</Badge>
                    )}
                  </div>
                  <div className="mb-3">
                    <div className="form-label">Base URL</div>
                    <code className="d-block bg-light p-2 rounded">
                      {health.base_url || 'Not configured'}
                    </code>
                  </div>
                  <div>
                    <div className="form-label">Response Time</div>
                    <strong>{health.response_time_ms}ms</strong>
                  </div>
                  {health.status && health.status !== 'ok' && (
                    <Alert variant="warning" className="mt-3 mb-0">
                      <strong>Details:</strong> {health.status}
                    </Alert>
                  )}
                </>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="card-professional h-100">
            <Card.Header className="card-header-professional">
              <h5 className="mb-0">📥 Pull New Model</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted small">
                Pull a new model into Ollama without leaving the admin panel.
              </p>
              <Form.Group className="mb-3">
                <Form.Label>Model Name</Form.Label>
                <Form.Control
                  type="text"
                  placeholder="e.g., llama3.1:8b"
                  value={modelNameInput}
                  onChange={(event) => setModelNameInput(event.target.value)}
                  disabled={pullLoading || !health?.healthy}
                />
                <Form.Text className="text-muted">
                  Popular models: llama3.1:8b, llama3.2, mistral, gemma2.
                </Form.Text>
              </Form.Group>
              <Button
                variant="primary"
                className="w-100"
                onClick={handlePullModel}
                disabled={pullLoading || !health?.healthy}
              >
                {pullLoading ? 'Initiating Pull...' : 'Pull Model'}
              </Button>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="mb-4">
        <Col xl={6}>
          <Card className="card-professional h-100">
            <Card.Header className="card-header-professional d-flex justify-content-between align-items-center">
              <h5 className="mb-0">⚙️ Scraper Runtime Config</h5>
              <Button
                size="sm"
                variant="outline-primary"
                onClick={refreshScraperStatus}
                disabled={scraperLoading}
              >
                {scraperLoading ? 'Refreshing...' : 'Reload'}
              </Button>
            </Card.Header>
            <Card.Body>
              <Row>
                <Col md={6} className="mb-3">
                  <Form.Label>Provider</Form.Label>
                  <Form.Select
                    value={scraperForm.provider}
                    onChange={(event) => handleScraperFormChange('provider', event.target.value)}
                  >
                    {(scraperStatus?.supported_providers || [
                      'firecrawl_first',
                      'firecrawl_only',
                      'ollama_first',
                      'ollama_only',
                    ]).map((provider) => (
                      <option key={provider} value={provider}>{provider}</option>
                    ))}
                  </Form.Select>
                </Col>
                <Col md={6} className="mb-3">
                  <Form.Label>Ollama Timeout (seconds)</Form.Label>
                  <Form.Control
                    type="number"
                    min="1"
                    value={scraperForm.ollama_timeout_seconds}
                    onChange={(event) =>
                      handleScraperFormChange('ollama_timeout_seconds', event.target.value)
                    }
                  />
                </Col>
              </Row>

              <Form.Group className="mb-3">
                <Form.Label>Ollama Base URL</Form.Label>
                <Form.Control
                  type="text"
                  value={scraperForm.ollama_base_url}
                  onChange={(event) =>
                    handleScraperFormChange('ollama_base_url', event.target.value)
                  }
                />
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Ollama Model</Form.Label>
                <Form.Control
                  type="text"
                  value={scraperForm.ollama_model}
                  onChange={(event) =>
                    handleScraperFormChange('ollama_model', event.target.value)
                  }
                />
              </Form.Group>

              <Form.Check
                className="mb-3"
                type="switch"
                id="allow-firecrawl-fallback"
                label="Allow Firecrawl fallback when Ollama scraping fails"
                checked={scraperForm.allow_firecrawl_fallback}
                onChange={(event) =>
                  handleScraperFormChange(
                    'allow_firecrawl_fallback',
                    event.target.checked
                  )
                }
              />

              <Button
                variant="primary"
                onClick={handleSaveScraperConfig}
                disabled={scraperSaving}
              >
                {scraperSaving ? 'Saving...' : 'Save Scraper Config'}
              </Button>
            </Card.Body>
          </Card>
        </Col>

        <Col xl={6}>
          <Card className="card-professional h-100">
            <Card.Header className="card-header-professional">
              <h5 className="mb-0">🧪 Probe Case Lookup</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted small">
                Run the court scraper for one case and inspect the court requests,
                HTML previews, Ollama prompt, raw response, and final normalized result.
              </p>
              <Row>
                <Col md={7} className="mb-3">
                  <Form.Label>Case Reference</Form.Label>
                  <Form.Control
                    type="text"
                    value={probeForm.case_ref}
                    placeholder="WP/3373/2025"
                    onChange={(event) =>
                      setProbeForm((current) => ({
                        ...current,
                        case_ref: event.target.value,
                      }))
                    }
                  />
                </Col>
                <Col md={5} className="mb-3">
                  <Form.Label>Bench</Form.Label>
                  <Form.Select
                    value={probeForm.bench}
                    onChange={(event) =>
                      setProbeForm((current) => ({
                        ...current,
                        bench: event.target.value,
                      }))
                    }
                  >
                    <option value="mumbai">Mumbai</option>
                    <option value="mumbai_appellate">Mumbai Appellate</option>
                    <option value="aurangabad">Aurangabad</option>
                    <option value="nagpur">Nagpur</option>
                    <option value="goa">Goa</option>
                  </Form.Select>
                </Col>
              </Row>

              <Form.Group className="mb-3">
                <Form.Label>Board Date (optional)</Form.Label>
                <Form.Control
                  type="date"
                  value={probeForm.date}
                  onChange={(event) =>
                    setProbeForm((current) => ({
                      ...current,
                      date: event.target.value,
                    }))
                  }
                />
              </Form.Group>

              <Button
                variant="primary"
                className="w-100"
                onClick={handleProbeCase}
                disabled={probeLoading}
              >
                {probeLoading ? 'Running Case Probe...' : 'Run Case Probe'}
              </Button>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {probeResult && (
        <Row className="mb-4">
          <Col>
            <Card className="card-professional">
              <Card.Header className="card-header-professional">
                <h5 className="mb-0">🔎 Probe Result</h5>
              </Card.Header>
              <Card.Body>
                <Row>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Provider</div>
                    <Badge bg="info">{probeResult.scraper_config?.provider || 'unknown'}</Badge>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Final Status</div>
                    <strong>{probeResult.final_result?.status || 'unknown'}</strong>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Result Source</div>
                    <strong>{probeResult.final_result?.source || 'unknown'}</strong>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Orders Found</div>
                    <strong>{probeResult.final_result?.court_orders?.length || 0}</strong>
                  </Col>
                </Row>

                <div className="table-responsive mt-3">
                  <Table striped hover size="sm">
                    <thead>
                      <tr>
                        <th>URL</th>
                        <th>Status</th>
                        <th>Bytes</th>
                        <th>Orders</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(probeResult.http_trace || []).map((trace, index) => (
                        <tr key={`${trace.url}-${index}`}>
                          <td className="small"><code>{trace.url}</code></td>
                          <td>{trace.status_code || trace.error || 'n/a'}</td>
                          <td>{trace.content_length || 0}</td>
                          <td>{trace.extracted_order_count || 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              </Card.Body>
            </Card>

            {renderJsonBlock('Probe Request', probeResult.request)}
            {renderJsonBlock('HTTP Trace', probeResult.http_trace)}
            {renderJsonBlock('Ollama Request', probeResult.ollama_request)}
            {renderJsonBlock('Ollama Response', probeResult.ollama_response)}
            {renderJsonBlock('Final Scraper Result', probeResult.final_result)}
          </Col>
        </Row>
      )}

      {/* ── Ad-hoc: Fetch Order Links via Web Scraping + Ollama ─────────────── */}
      <Row className="mb-4">
        <Col>
          <Card className="card-professional">
            <Card.Header className="card-header-professional">
              <h5 className="mb-0">🔗 Ad-hoc Fetch Order Links</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted small">
                Enter a case number to fetch all available order PDF links from the
                Bombay High Court website using the configured scraper (Ollama or
                Firecrawl). The currently active model is{' '}
                <strong>{scraperForm.ollama_model || 'not configured'}</strong>.
              </p>
              <Row>
                <Col md={7} className="mb-3">
                  <Form.Label>Case Reference</Form.Label>
                  <Form.Control
                    type="text"
                    placeholder="e.g. WP/3373/2025"
                    value={orderLinksForm.case_ref}
                    onChange={(event) =>
                      setOrderLinksForm((prev) => ({
                        ...prev,
                        case_ref: event.target.value,
                      }))
                    }
                  />
                </Col>
                <Col md={5} className="mb-3">
                  <Form.Label>Bench</Form.Label>
                  <Form.Select
                    value={orderLinksForm.bench}
                    onChange={(event) =>
                      setOrderLinksForm((prev) => ({
                        ...prev,
                        bench: event.target.value,
                      }))
                    }
                  >
                    <option value="mumbai">Mumbai</option>
                    <option value="mumbai_appellate">Mumbai Appellate</option>
                    <option value="aurangabad">Aurangabad</option>
                    <option value="nagpur">Nagpur</option>
                    <option value="goa">Goa</option>
                  </Form.Select>
                </Col>
              </Row>
              <Form.Group className="mb-3">
                <Form.Label>Date (optional – leave blank for all orders)</Form.Label>
                <Form.Control
                  type="date"
                  value={orderLinksForm.date}
                  onChange={(event) =>
                    setOrderLinksForm((prev) => ({
                      ...prev,
                      date: event.target.value,
                    }))
                  }
                />
              </Form.Group>
              <Button
                variant="primary"
                className="w-100"
                onClick={handleFetchOrderLinks}
                disabled={orderLinksLoading}
              >
                {orderLinksLoading ? (
                  <>
                    <Spinner animation="border" size="sm" className="me-2" />
                    Fetching Order Links…
                  </>
                ) : (
                  'Fetch Order Links'
                )}
              </Button>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {orderLinksResult && (
        <Row className="mb-4">
          <Col>
            <Card className="card-professional">
              <Card.Header className="card-header-professional">
                <h5 className="mb-0">🗂️ Order Links Result</h5>
              </Card.Header>
              <Card.Body>
                <Row className="mb-3">
                  <Col md={4}>
                    <div className="small text-muted">Case Reference</div>
                    <strong>{orderLinksResult.case_ref}</strong>
                  </Col>
                  <Col md={4}>
                    <div className="small text-muted">Order Links Found</div>
                    <Badge bg={(orderLinksResult.court_orders || orderLinksResult.orders || []).length > 0 ? 'success' : 'secondary'}>
                      {(orderLinksResult.court_orders || orderLinksResult.orders || []).length}
                    </Badge>
                  </Col>
                  <Col md={4}>
                    <div className="small text-muted">Ollama Model Used</div>
                    <code>{scraperForm.ollama_model || '—'}</code>
                  </Col>
                </Row>

                {(orderLinksResult.court_orders || orderLinksResult.orders || []).length > 0 ? (
                  <div className="table-responsive">
                    <Table striped hover size="sm" className="mb-0">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Order Link</th>
                          <th>Date</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(orderLinksResult.court_orders || orderLinksResult.orders || []).map(
                          (order, index) => {
                            const url =
                              typeof order === 'string'
                                ? order
                                : order.url || order.order_url || order.link || '';
                            const orderDate =
                              typeof order === 'object'
                                ? order.date || order.order_date || '—'
                                : '—';
                            return (
                              <tr key={`${url}-${index}`}>
                                <td>{index + 1}</td>
                                <td className="small">
                                  <code
                                    style={{
                                      wordBreak: 'break-all',
                                      whiteSpace: 'pre-wrap',
                                    }}
                                  >
                                    {url || '(no URL)'}
                                  </code>
                                </td>
                                <td>{orderDate}</td>
                                <td>
                                  {url && (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="outline-primary"
                                        className="me-1"
                                        onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}
                                      >
                                        Open
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline-secondary"
                                        onClick={() => {
                                          setOrderAnalysisUrl(url);
                                          window.scrollTo({
                                            top: document.body.scrollHeight,
                                            behavior: 'smooth',
                                          });
                                        }}
                                      >
                                        Analyze ↓
                                      </Button>
                                    </>
                                  )}
                                </td>
                              </tr>
                            );
                          }
                        )}
                      </tbody>
                    </Table>
                  </div>
                ) : (
                  <Alert variant="warning" className="mb-0">
                    No order links found for this case. Check the case reference and bench, or
                    verify Ollama is healthy.
                  </Alert>
                )}

                {orderLinksResult.status && (
                  <div className="mt-3 small text-muted">
                    Scraper status: <strong>{orderLinksResult.status}</strong>
                  </div>
                )}
              </Card.Body>
            </Card>

            {renderJsonBlock('Order Links Raw Response', orderLinksResult)}
          </Col>
        </Row>
      )}

      <Row className="mb-4">
        <Col>
          <Card className="card-professional">
            <Card.Header className="card-header-professional">
              <h5 className="mb-0">📄 Analyze Order From Link</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted small">
                Paste a PDF link and run the existing order analyzer directly. This is useful for
                validating a scraped order link without uploading a file manually.
              </p>
              <Form.Group className="mb-3">
                <Form.Label>Order PDF URL</Form.Label>
                <Form.Control
                  type="url"
                  placeholder="https://.../order.pdf"
                  value={orderAnalysisUrl}
                  onChange={(event) => setOrderAnalysisUrl(event.target.value)}
                />
              </Form.Group>
              <Form.Check
                className="mb-3"
                type="switch"
                id="persist-order-analysis"
                label="Persist analysis result to database"
                checked={orderAnalysisPersist}
                onChange={(event) => setOrderAnalysisPersist(event.target.checked)}
              />
              <Button
                variant="primary"
                onClick={handleAnalyzeOrderLink}
                disabled={orderAnalysisLoading}
              >
                {orderAnalysisLoading ? 'Analyzing Order Link...' : 'Analyze Link'}
              </Button>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {orderAnalysisResult && (
        <Row className="mb-4">
          <Col>
            <Card className="card-professional">
              <Card.Header className="card-header-professional">
                <h5 className="mb-0">🧾 Order Analysis Result</h5>
              </Card.Header>
              <Card.Body>
                <Row>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Category</div>
                    <Badge
                      bg={
                        orderAnalysisResult.order_category === 'DISPOSED_OFF'
                          ? 'danger'
                          : orderAnalysisResult.order_category === 'HEARD_AND_ADJOURNED'
                          ? 'warning'
                          : 'primary'
                      }
                    >
                      {orderAnalysisResult.order_category || 'Unknown'}
                    </Badge>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Confidence</div>
                    <Badge
                      bg={
                        orderAnalysisResult.category_confidence >= 0.7
                          ? 'success'
                          : 'warning'
                      }
                    >
                      {(orderAnalysisResult.category_confidence * 100).toFixed(1)}%
                    </Badge>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Order Date</div>
                    <strong>{orderAnalysisResult.order_date || 'Unknown'}</strong>
                  </Col>
                  <Col md={3} className="mb-3">
                    <div className="small text-muted">Cases Extracted</div>
                    <strong>{orderAnalysisResult.summary?.total_cases || 0}</strong>
                  </Col>
                </Row>

                {orderAnalysisResult.persisted !== undefined && (
                  <div className="mb-3">
                    <div className="small text-muted">Persisted to DB</div>
                    <Badge bg={orderAnalysisResult.persisted ? 'success' : 'secondary'}>
                      {orderAnalysisResult.persisted ? 'Yes' : 'No'}
                    </Badge>
                  </div>
                )}

                {(orderAnalysisResult.cases || []).length > 0 && (
                  <div className="table-responsive mt-2">
                    <Table striped hover size="sm" className="mb-0">
                      <thead>
                        <tr>
                          <th>Case</th>
                          <th>Petitioner</th>
                          <th>Respondent</th>
                          <th>AGP</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orderAnalysisResult.cases.map((c, i) => (
                          <tr key={i}>
                            <td>
                              <code>
                                {c.case_type}/{c.case_number}/{c.case_year}
                              </code>
                            </td>
                            <td className="small">{c.petitioner || '—'}</td>
                            <td className="small">{c.respondent || '—'}</td>
                            <td className="small">{c.government_pleader || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>
                )}
              </Card.Body>
            </Card>

            {renderJsonBlock('Download Metadata', orderAnalysisResult.download_metadata)}
            {renderJsonBlock('Full Analysis Response', orderAnalysisResult)}
          </Col>
        </Row>
      )}

      <Row>
        <Col>
          <Card className="card-professional">
            <Card.Header className="card-header-professional d-flex justify-content-between align-items-center">
              <h5 className="mb-0">
                📚 Available Models
                {models?.models && (
                  <Badge bg="info" className="ms-2">{models.models.length}</Badge>
                )}
              </h5>
              <Button
                size="sm"
                variant="outline-primary"
                onClick={refreshModels}
                disabled={modelsLoading}
              >
                {modelsLoading ? 'Loading...' : 'Refresh'}
              </Button>
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
                    <div className="form-label">Configured Model</div>
                    <Badge bg="info" className="fs-6 py-2 px-3">
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
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {models.models.map((model) => {
                          const isConfigured = model.name === models.configured_model;
                          const sizeMB = (model.size / (1024 * 1024)).toFixed(0);
                          return (
                            <tr
                              key={model.name}
                              className={isConfigured ? 'table-info' : ''}
                            >
                              <td><code>{model.name}</code></td>
                              <td>{sizeMB} MB</td>
                              <td className="text-muted small">{model.format || 'unknown'}</td>
                              <td>
                                {isConfigured ? (
                                  <Badge bg="success">Configured</Badge>
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
                  No models loaded. Pull a model or verify the Ollama endpoint.
                </Alert>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
};

export default AdminOllamaManagement;
