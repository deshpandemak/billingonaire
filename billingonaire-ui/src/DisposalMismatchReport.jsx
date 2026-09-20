import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Form, Button, Table as BTable, Alert, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON, getApiUrl } from './lib/api.js';
import { auth } from './lib/firebase.js';
import { onAuthStateChanged } from 'firebase/auth';
import { getOrderCategoryLabel, GOVERNMENT_ROLES_NOTE } from './lib/lifecycleUtils';

const formatDateSafe = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

const DisposalMismatchReport = () => {
    const [dateRange, setDateRange] = useState({ startDate: '', endDate: '' });
    const [isAdmin, setIsAdmin] = useState(false);
    const [userList, setUserList] = useState([]);
    const [selectedUser, setSelectedUser] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [report, setReport] = useState(null);

    useEffect(() => {
        const today = new Date();
        const startOfYear = new Date(today.getFullYear(), 0, 1);
        setDateRange({ startDate: formatDateSafe(startOfYear), endDate: formatDateSafe(today) });
    }, []);

    useEffect(() => {
        const unsubscribe = onAuthStateChanged(auth, async (user) => {
            if (!user) {
                setIsAdmin(false);
                setUserList([]);
                return;
            }
            try {
                const response = await authenticatedFetchJSON('/admin/active-users');
                setIsAdmin(true);
                setUserList(response.user_names || []);
            } catch {
                setIsAdmin(false);
                setUserList([]);
            }
        });
        return () => unsubscribe();
    }, []);

    const handleDateChange = (field, value) => {
        setDateRange((prev) => ({ ...prev, [field]: value }));
    };

    const runReport = async () => {
        if (!dateRange.startDate || !dateRange.endDate) {
            setError('Please select both start and end dates');
            return;
        }
        setLoading(true);
        setError('');
        try {
            let url = `/reports/cross-agp-disposals?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`;
            if (isAdmin && selectedUser) {
                url += `&user_name=${encodeURIComponent(selectedUser)}`;
            }
            // Walks every matched case's full order history -- can take a
            // moment for an AGP with a large docket, same reasoning as the
            // Compliance Tracker's own generous timeout.
            const response = await authenticatedFetchJSON(url, { method: 'POST', timeoutMs: 120000 });
            setReport(response);
        } catch (err) {
            setError(err.message || 'Failed to run report');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Container fluid className="py-4">
            <Row>
                <Col>
                    <Card className="shadow-sm">
                        <Card.Header className="bg-primary text-white">
                            <h4 className="mb-0">🔀 Disposal Mismatch Report</h4>
                        </Card.Header>
                        <Card.Body>
                            <p className="text-muted mb-4">
                                Finds matters where the selected AGP appeared on one or more hearing
                                dates but the case was eventually disposed under a <strong>different</strong>{' '}
                                AGP's name — e.g. you appeared and the matter was heard &amp; adjourned,
                                but someone else's name is on the disposal order. Both your appearance
                                and the disposal must fall within the selected date range — a case you
                                handled in an earlier period, disposed under someone else's name outside
                                this window, won't surface; pick a wider range to include it. A disposal
                                order that names no one is left out rather than guessed at.
                                {' '}{GOVERNMENT_ROLES_NOTE}
                            </p>

                            <Row className="mb-4">
                                <Col md={3}>
                                    <Form.Group>
                                        <Form.Label>Start Date</Form.Label>
                                        <Form.Control
                                            type="date"
                                            value={dateRange.startDate}
                                            onChange={(e) => handleDateChange('startDate', e.target.value)}
                                        />
                                    </Form.Group>
                                </Col>
                                <Col md={3}>
                                    <Form.Group>
                                        <Form.Label>End Date</Form.Label>
                                        <Form.Control
                                            type="date"
                                            value={dateRange.endDate}
                                            onChange={(e) => handleDateChange('endDate', e.target.value)}
                                        />
                                    </Form.Group>
                                </Col>
                            </Row>

                            {isAdmin && userList.length > 0 && (
                                <Row className="mb-4">
                                    <Col md={6}>
                                        <Form.Group>
                                            <Form.Label>
                                                <span className="badge bg-success me-2">Admin</span>
                                                Select AGP (optional — leave empty for your own cases)
                                            </Form.Label>
                                            <Form.Select
                                                value={selectedUser}
                                                onChange={(e) => setSelectedUser(e.target.value)}
                                            >
                                                <option value="">My Cases Only</option>
                                                {userList.map((userName, index) => (
                                                    <option key={index} value={userName}>{userName}</option>
                                                ))}
                                            </Form.Select>
                                        </Form.Group>
                                    </Col>
                                </Row>
                            )}

                            <Row className="mb-4">
                                <Col md={3}>
                                    <Button variant="success" onClick={runReport} disabled={loading} className="w-100">
                                        {loading ? (
                                            <>
                                                <Spinner size="sm" className="me-2" />
                                                Scanning...
                                            </>
                                        ) : (
                                            'Run Report'
                                        )}
                                    </Button>
                                </Col>
                            </Row>

                            {error && <Alert variant="danger">{error}</Alert>}

                            {report && (
                                <>
                                    <Row className="mb-3">
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Cases checked</div>
                                                <div className="h4 mb-0">{report.cases_checked}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center border-warning">
                                                <div className="text-muted small">Flagged</div>
                                                <div className="h4 mb-0 text-warning">{report.flagged_count}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center" title="Disposed under the same AGP's name -- nothing to flag.">
                                                <div className="text-muted small">Same AGP disposed</div>
                                                <div className="h4 mb-0">{report.already_disposed_by_same_agp}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Not disposed yet</div>
                                                <div className="h4 mb-0">{report.no_disposal_yet}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center" title="Disposal order names no government pleader (even after checking the board assignment for that date) -- can't confirm a mismatch, so excluded from the flagged list.">
                                                <div className="text-muted small">Disposal AGP unnamed</div>
                                                <div className="h4 mb-0">{report.disposal_agp_unnamed}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center" title="Disposed under a different AGP, but before the selected start date -- outside what you asked to see. Widen the date range to include it.">
                                                <div className="text-muted small">Outside date range</div>
                                                <div className="h4 mb-0">{report.disposed_outside_range}</div>
                                            </Card>
                                        </Col>
                                    </Row>

                                    {report.results.length === 0 ? (
                                        <Alert variant="light" className="border">
                                            No mismatches found in this date range.
                                        </Alert>
                                    ) : (
                                        <div style={{ overflowX: 'auto' }}>
                                            <BTable striped bordered hover size="sm">
                                                <thead>
                                                    <tr>
                                                        <th>Case</th>
                                                        <th>Selected AGP's appearances</th>
                                                        <th>Disposal Date</th>
                                                        <th>Disposed under</th>
                                                        <th>Order</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {report.results.map((row) => (
                                                        <tr key={row.case_ref}>
                                                            <td>{row.case_ref}</td>
                                                            <td style={{ fontSize: '0.85em' }}>
                                                                <div className="fw-bold">{row.appearances_count}</div>
                                                                {row.appearances.map((a, i) => (
                                                                    <div key={i} className="text-muted">
                                                                        {a.date} — {getOrderCategoryLabel(a.category)}
                                                                    </div>
                                                                ))}
                                                            </td>
                                                            <td>{row.disposal_date || '-'}</td>
                                                            <td className="text-danger fw-bold">
                                                                {row.disposal_agp_names.join(', ')}
                                                            </td>
                                                            <td>
                                                                {row.order_link ? (
                                                                    <a
                                                                        href={getApiUrl(`/orders/pdf/${row.disposal_board_date}-${row.case_ref.replace(/\//g, '-')}`)}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                    >
                                                                        View
                                                                    </a>
                                                                ) : '-'}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </BTable>
                                        </div>
                                    )}
                                </>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
        </Container>
    );
};

export default DisposalMismatchReport;
