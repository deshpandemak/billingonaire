import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Form, Button, Table as BTable, Alert, Spinner, Badge } from 'react-bootstrap';
import { authenticatedFetchJSON, getApiUrl } from './lib/api.js';
import { auth } from './lib/firebase.js';
import { onAuthStateChanged } from 'firebase/auth';
import { getOrderCategoryLabel, GOVERNMENT_ROLES_NOTE } from './lib/lifecycleUtils';

// Fixed taxonomy mirrors compliance_extractor.py's DIRECTIVE_TYPES -- keep
// these two lists in sync if a new directive type is ever added there.
const DIRECTIVE_LABELS = {
    FILE_REPLY_AFFIDAVIT: 'File reply affidavit',
    FILE_REJOINDER: 'File rejoinder',
    FURNISH_COMPLIANCE_REPORT: 'Furnish compliance report',
    PRODUCE_DOCUMENTS: 'Produce documents',
    APPEAR_IN_PERSON: 'Appear in person',
    PAY_COSTS_OR_COMPENSATION: 'Pay costs / compensation',
    OTHER: 'Other directive',
};

const formatDateSafe = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

// Whole-day difference between an ISO date and today, ignoring time of day
// so "today" always reads as 0 rather than a fraction.
const daysUntil = (isoDate) => {
    if (!isoDate) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(`${isoDate}T00:00:00`);
    if (isNaN(target.getTime())) return null;
    return Math.round((target - today) / 86400000);
};

const DeadlineBadge = ({ isoDate }) => {
    const days = daysUntil(isoDate);
    if (days === null) return <span className="text-muted">No deadline stated</span>;
    if (days < 0) return <Badge bg="danger">Overdue by {Math.abs(days)}d ({isoDate})</Badge>;
    if (days <= 3) return <Badge bg="danger">{days}d left ({isoDate})</Badge>;
    if (days <= 7) return <Badge bg="warning" text="dark">{days}d left ({isoDate})</Badge>;
    return <Badge bg="success">{days}d left ({isoDate})</Badge>;
};

const ComplianceTracker = () => {
    const [dateRange, setDateRange] = useState({ startDate: '', endDate: '' });
    const [isAdmin, setIsAdmin] = useState(false);
    const [userList, setUserList] = useState([]);
    const [selectedUser, setSelectedUser] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [report, setReport] = useState(null);
    const [directiveFilter, setDirectiveFilter] = useState('ALL');

    useEffect(() => {
        const today = new Date();
        const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        setDateRange({ startDate: formatDateSafe(startOfMonth), endDate: formatDateSafe(today) });
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

    const runScan = async () => {
        if (!dateRange.startDate || !dateRange.endDate) {
            setError('Please select both start and end dates');
            return;
        }
        setLoading(true);
        setError('');
        try {
            let url = `/compliance/scan?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`;
            if (isAdmin && selectedUser) {
                url += `&user_name=${encodeURIComponent(selectedUser)}`;
            }
            const response = await authenticatedFetchJSON(url, { method: 'POST', timeoutMs: 120000 });
            setReport(response);
            setDirectiveFilter('ALL');
        } catch (err) {
            setError(err.message || 'Failed to run compliance scan');
        } finally {
            setLoading(false);
        }
    };

    // One row per directive; a disposed/no-directive case still gets a
    // single row so it's visible in the report, just with directive: null.
    const directiveRows = (report?.results || []).flatMap((row) =>
        row.directives && row.directives.length > 0
            ? row.directives.map((directive, i) => ({ ...row, directive, key: `${row.case_ref}-${row.order_date}-${i}` }))
            : [{ ...row, directive: null, key: `${row.case_ref}-${row.order_date}` }]
    );

    const filteredRows =
        directiveFilter === 'ALL'
            ? directiveRows
            : directiveFilter === 'DISPOSED'
                ? directiveRows.filter((r) => r.order_category === 'DISPOSED_OFF')
                : directiveRows.filter((r) => r.directive && r.directive.directive_type === directiveFilter);

    const directiveTypesPresent = [
        ...new Set(directiveRows.filter((r) => r.directive).map((r) => r.directive.directive_type)),
    ];

    return (
        <Container fluid className="py-4">
            <Row>
                <Col>
                    <Card className="shadow-sm">
                        <Card.Header className="bg-primary text-white">
                            <h4 className="mb-0">📋 Compliance Tracker</h4>
                        </Card.Header>
                        <Card.Body>
                            <p className="text-muted mb-4">
                                Scans already-analysed orders for directives requiring government-side
                                action — file a reply affidavit, furnish a compliance report, and
                                similar — plus which cases were disposed. Adjourned-only hearings are
                                skipped: the matter was never reached, so there is nothing to act on.
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
                                    <Button variant="success" onClick={runScan} disabled={loading} className="w-100">
                                        {loading ? (
                                            <>
                                                <Spinner size="sm" className="me-2" />
                                                Scanning...
                                            </>
                                        ) : (
                                            'Run Compliance Scan'
                                        )}
                                    </Button>
                                </Col>
                            </Row>

                            {error && <Alert variant="danger">{error}</Alert>}

                            {report && !report.ai_available && (
                                <Alert variant="warning">
                                    AI directive extraction is not configured for this deployment — disposed
                                    cases are still shown below, but affidavit/compliance directives could
                                    not be extracted from order text.
                                </Alert>
                            )}

                            {report && (
                                <>
                                    <Row className="mb-3">
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Matters in range</div>
                                                <div className="h4 mb-0">{report.total_matters}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center" title="HEARD_AND_ADJOURNED and DISPOSED_OFF orders examined -- adjourned-only hearings are skipped by design.">
                                                <div className="text-muted small">Orders scanned</div>
                                                <div className="h4 mb-0">{report.orders_scanned}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Adjourned (skipped)</div>
                                                <div className="h4 mb-0">{report.adjourned_skipped}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Disposed cases</div>
                                                <div className="h4 mb-0">{report.disposed_count}</div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Rows with a directive</div>
                                                <div className="h4 mb-0">
                                                    {directiveRows.filter((r) => r.directive).length}
                                                </div>
                                            </Card>
                                        </Col>
                                        <Col md={2}>
                                            <Card body className="text-center">
                                                <div className="text-muted small">Newly scanned</div>
                                                <div className="h4 mb-0">{report.newly_scanned}</div>
                                            </Card>
                                        </Col>
                                        {report.llm_errors > 0 && (
                                            <Col md={2}>
                                                <Card body className="text-center border-warning">
                                                    <div className="text-muted small">Scan errors</div>
                                                    <div className="h4 mb-0 text-warning">{report.llm_errors}</div>
                                                </Card>
                                            </Col>
                                        )}
                                    </Row>

                                    <div className="d-flex gap-2 flex-wrap mb-3">
                                        <Button
                                            size="sm"
                                            variant={directiveFilter === 'ALL' ? 'primary' : 'outline-primary'}
                                            onClick={() => setDirectiveFilter('ALL')}
                                        >
                                            All ({directiveRows.length})
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant={directiveFilter === 'DISPOSED' ? 'primary' : 'outline-primary'}
                                            onClick={() => setDirectiveFilter('DISPOSED')}
                                        >
                                            Disposed ({report.disposed_count})
                                        </Button>
                                        {directiveTypesPresent.map((type) => (
                                            <Button
                                                key={type}
                                                size="sm"
                                                variant={directiveFilter === type ? 'primary' : 'outline-primary'}
                                                onClick={() => setDirectiveFilter(type)}
                                            >
                                                {DIRECTIVE_LABELS[type] || type}
                                            </Button>
                                        ))}
                                    </div>

                                    {filteredRows.length === 0 ? (
                                        <Alert variant="light" className="border">
                                            No matching cases in this date range.
                                        </Alert>
                                    ) : (
                                        <div style={{ overflowX: 'auto' }}>
                                            <BTable striped bordered hover size="sm">
                                                <thead>
                                                    <tr>
                                                        <th>Case</th>
                                                        <th>Order Date</th>
                                                        <th>Outcome</th>
                                                        <th>Directive</th>
                                                        <th>Deadline</th>
                                                        <th>Order</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {filteredRows.map((row) => (
                                                        <tr key={row.key}>
                                                            <td>{row.case_ref}</td>
                                                            <td>{row.order_date || '-'}</td>
                                                            <td>{getOrderCategoryLabel(row.order_category)}</td>
                                                            <td>
                                                                {row.directive
                                                                    ? (DIRECTIVE_LABELS[row.directive.directive_type] || row.directive.directive_type)
                                                                    : <span className="text-muted">—</span>}
                                                                {row.directive?.description && (
                                                                    <div className="text-muted small">{row.directive.description}</div>
                                                                )}
                                                            </td>
                                                            <td>
                                                                {row.directive
                                                                    ? <DeadlineBadge isoDate={row.directive.deadline_date} />
                                                                    : <span className="text-muted">—</span>}
                                                            </td>
                                                            <td>
                                                                {row.order_link ? (
                                                                    <a href={getApiUrl(`/orders/pdf/${row.board_date}-${row.case_ref.replace(/\//g, '-')}`)} target="_blank" rel="noopener noreferrer">
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

export default ComplianceTracker;
