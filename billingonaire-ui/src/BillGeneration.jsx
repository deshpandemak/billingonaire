import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Form, Button, Table, Alert, Modal, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON, authenticatedFetch, getApiUrl } from './lib/api.js';
import { auth } from './lib/firebase.js';
import { onAuthStateChanged } from 'firebase/auth';
import {
    BILLING_OUTCOMES,
    DEFAULT_OUTCOME,
    UNVERIFIED_RESULT,
    feeForResult,
    isUnverifiedResult,
    labelForResult,
    formatFee,
} from './lib/billing.js';

const BillGeneration = () => {
    const [dateRange, setDateRange] = useState({
        startDate: '',
        endDate: ''
    });
    const [billData, setBillData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [editingRow, setEditingRow] = useState(null);
    const [tempEditData, setTempEditData] = useState({});
    const [showSaveModal, setShowSaveModal] = useState(false);
    const [saveBillLoading, setSaveBillLoading] = useState(false);
    const [bulkEditMode, setBulkEditMode] = useState(false);
    const [selectedRows, setSelectedRows] = useState(new Set());
    const [bulkFeeValue, setBulkFeeValue] = useState('');
    const [processingStatus, setProcessingStatus] = useState('');
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    const [isAdmin, setIsAdmin] = useState(false);
    const [userList, setUserList] = useState([]);
    const [selectedUser, setSelectedUser] = useState('');
    const [authReady, setAuthReady] = useState(false);
    const [exportMessage, setExportMessage] = useState(null);
    const [saveMessage, setSaveMessage] = useState(null);

    // Set default date range to current month
    useEffect(() => {
        const today = new Date();
        const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);

        setDateRange({
            startDate: formatDateSafe(startOfMonth),
            endDate: formatDateSafe(endOfMonth)
        });
    }, []);

    // Wait for Firebase authentication before fetching user list
    useEffect(() => {
        const unsubscribe = onAuthStateChanged(auth, async (user) => {
            if (user) {
                await checkAdminAndFetchUsers();
            } else {
                setIsAdmin(false);
                setUserList([]);
            }
            setAuthReady(true);
        });

        return () => unsubscribe();
    }, []);

    const checkAdminAndFetchUsers = async () => {
        try {
            const currentUser = auth.currentUser;
            if (!currentUser) {
                setIsAdmin(false);
                setUserList([]);
                return;
            }
            const response = await authenticatedFetchJSON('/admin/active-users');
            setIsAdmin(true);
            setUserList(response.user_names || []);
        } catch {
            setIsAdmin(false);
            setUserList([]);
        }
    };

    const handleDateChange = (field, value) => {
        setDateRange(prev => ({
            ...prev,
            [field]: value
        }));
    };

    const formatDateSafe = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    const getDatePresets = () => {
        const today = new Date();
        const presets = {};

        // This Week
        const startOfWeek = new Date(today);
        startOfWeek.setDate(today.getDate() - today.getDay());
        const endOfWeek = new Date(startOfWeek);
        endOfWeek.setDate(startOfWeek.getDate() + 6);
        presets.thisWeek = {
            startDate: formatDateSafe(startOfWeek),
            endDate: formatDateSafe(endOfWeek)
        };

        // Last Week
        const lastWeekStart = new Date(startOfWeek);
        lastWeekStart.setDate(startOfWeek.getDate() - 7);
        const lastWeekEnd = new Date(lastWeekStart);
        lastWeekEnd.setDate(lastWeekStart.getDate() + 6);
        presets.lastWeek = {
            startDate: formatDateSafe(lastWeekStart),
            endDate: formatDateSafe(lastWeekEnd)
        };

        // This Month
        const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        presets.thisMonth = {
            startDate: formatDateSafe(startOfMonth),
            endDate: formatDateSafe(endOfMonth)
        };

        // Last Month
        const lastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        const lastMonthEnd = new Date(today.getFullYear(), today.getMonth(), 0);
        presets.lastMonth = {
            startDate: formatDateSafe(lastMonth),
            endDate: formatDateSafe(lastMonthEnd)
        };

        // This Quarter
        const quarterStart = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3, 1);
        const quarterEnd = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3 + 3, 0);
        presets.thisQuarter = {
            startDate: formatDateSafe(quarterStart),
            endDate: formatDateSafe(quarterEnd)
        };

        return presets;
    };

    const applyDatePreset = (presetKey) => {
        const presets = getDatePresets();
        setDateRange(presets[presetKey]);
    };

    const generateBillData = async () => {
        if (!dateRange.startDate || !dateRange.endDate) {
            setError('Please select both start and end dates');
            return;
        }

        setLoading(true);
        setError('');
        setElapsedSeconds(0);
        setProcessingStatus('Generating bill data…');

        const startTs = Date.now();
        const timerRef = setInterval(() => {
            setElapsedSeconds(Math.floor((Date.now() - startTs) / 1000));
        }, 1000);

        try {
            let queryUrl = `/bills/generate?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`;
            if (isAdmin && selectedUser) {
                queryUrl += `&user_name=${encodeURIComponent(selectedUser)}`;
            }

            const response = await authenticatedFetchJSON(queryUrl, { timeoutMs: 120000 });
            setBillData(response);
            setProcessingStatus('');
        } catch (err) {
            // Gracefully handle "No matching AGP" errors by showing empty bill
            if (err.message && err.message.includes('400')) {
                setBillData({
                    bill_entries: [],
                    total_fees: 0,
                    user_name: selectedUser || 'Current User',
                    start_date: dateRange.startDate,
                    end_date: dateRange.endDate,
                    generated_at: new Date().toISOString()
                });
                setProcessingStatus('');
            } else {
                setError(err.message || 'Failed to generate bill data');
                setProcessingStatus('');
            }
        } finally {
            clearInterval(timerRef);
            setLoading(false);
        }
    };

    const startEditRow = (index) => {
        setEditingRow(index);
        setTempEditData({ ...billData.bill_entries[index] });
    };

    const cancelEdit = () => {
        setEditingRow(null);
        setTempEditData({});
    };

    const saveEdit = () => {
        const updatedEntries = [...billData.bill_entries];
        // The outcome is what the user chose; the fee follows from it.
        const resultText = tempEditData.results || DEFAULT_OUTCOME.result;
        const updatedEntry = {
            ...tempEditData,
            results: resultText,
            fees_rs: feeForResult(resultText)
        };
        updatedEntries[editingRow] = updatedEntry;

        setBillData(prev => ({
            ...prev,
            bill_entries: updatedEntries,
            total_fees: updatedEntries.reduce((sum, entry) => sum + Number(entry.fees_rs || 0), 0)
        }));

        setEditingRow(null);
        setTempEditData({});
    };

    const deleteRow = (index) => {
        const updatedEntries = billData.bill_entries.filter((_, i) => i !== index);

        // Clear selection for deleted row and adjust indices
        const newSelected = new Set();
        selectedRows.forEach(selectedIndex => {
            if (selectedIndex < index) {
                newSelected.add(selectedIndex);
            } else if (selectedIndex > index) {
                newSelected.add(selectedIndex - 1);
            }
        });
        setSelectedRows(newSelected);

        setBillData(prev => ({
            ...prev,
            bill_entries: updatedEntries,
            total_entries: updatedEntries.length,
            total_fees: updatedEntries.reduce((sum, entry) => sum + Number(entry.fees_rs || 0), 0)
        }));
    };

    const addNewRow = () => {
        const newEntry = {
            id: `new_${Date.now()}`,
            date: formatDateSafe(new Date()),
            case_detail: '',
            case_type: '',
            case_no: '',
            case_year: '',
            parties_name: '',
            results: DEFAULT_OUTCOME.result,
            fees_rs: DEFAULT_OUTCOME.fee,
            confidence_score: 1.0,
            match_source: 'manual',
            editable: true
        };

        setBillData(prev => ({
            ...prev,
            bill_entries: [...prev.bill_entries, newEntry],
            total_entries: prev.bill_entries.length + 1,
            total_fees: Number(prev.total_fees || 0) + Number(newEntry.fees_rs)
        }));
    };

    const toggleRowSelection = (index) => {
        const newSelected = new Set(selectedRows);
        if (newSelected.has(index)) {
            newSelected.delete(index);
        } else {
            newSelected.add(index);
        }
        setSelectedRows(newSelected);
    };

    const selectAllRows = () => {
        if (selectedRows.size === billData?.bill_entries?.length) {
            setSelectedRows(new Set());
        } else {
            setSelectedRows(new Set(billData?.bill_entries?.map((_, index) => index)));
        }
    };

    const applyBulkFeeUpdate = () => {
        if (!bulkFeeValue || selectedRows.size === 0) return;

        const updatedEntries = [...billData.bill_entries];
        // bulkFeeValue now holds an outcome, not a rupee amount.
        const resultText = bulkFeeValue;
        const feeAmount = feeForResult(resultText);

        selectedRows.forEach(index => {
            updatedEntries[index] = {
                ...updatedEntries[index],
                results: resultText,
                fees_rs: feeAmount
            };
        });

        setBillData(prev => ({
            ...prev,
            bill_entries: updatedEntries,
            total_fees: updatedEntries.reduce((sum, entry) => sum + Number(entry.fees_rs || 0), 0)
        }));

        setSelectedRows(new Set());
        setBulkFeeValue('');
        setBulkEditMode(false);
    };

    const exportMultipleFormats = async () => {
        if (!billData?.bill_entries?.length) return;

        // Trigger backend Excel export (proper AGP format)
        try {
            // Build URL with parameters
            let excelUrl = `/bills/export/excel?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`;

            // Add user_name parameter if admin selected a user
            if (selectedUser) {
                excelUrl += `&user_name=${encodeURIComponent(selectedUser)}`;
            }

            // Download Excel file using authenticatedFetch (respects VITE_API_URL)
            const response = await authenticatedFetch(excelUrl);

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `AGP_Bill_${dateRange.startDate}_to_${dateRange.endDate}.xlsx`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            setExportMessage({ type: 'success', text: 'Bill exported successfully as Excel file.' });
        } catch (err) {
            setExportMessage({ type: 'error', text: `Export failed: ${err.message}` });
        }
    };

    const saveBill = async () => {
        setSaveBillLoading(true);
        try {
            const payload = {
                bill_entries: billData.bill_entries,
                metadata: {
                    date_range: dateRange,
                    generated_at: new Date().toISOString(),
                    total_entries: billData.total_entries,
                    total_fees: billData.total_fees
                }
            };

            const response = await authenticatedFetchJSON('/bills/save', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            setSaveMessage({
                type: 'success',
                text: `Bill saved — #${response.bill_number} · ${response.month_description} · ₹${response.total_fees?.toLocaleString()} · ${response.total_entries} entries`
            });
            setShowSaveModal(false);
        } catch (err) {
            setSaveMessage({ type: 'error', text: `Failed to save bill: ${err.message}` });
        } finally {
            setSaveBillLoading(false);
        }
    };

    const escapeCSVField = (field) => {
        if (field == null) return '';
        const stringField = String(field);
        // If field contains comma, quote, or newline, wrap in quotes and escape internal quotes
        if (stringField.includes(',') || stringField.includes('"') || stringField.includes('\n')) {
            return `"${stringField.replace(/"/g, '""')}"`;
        }
        return stringField;
    };

    return (
        <Container fluid className="py-4">
            <Row>
                <Col>
                    <Card className="shadow-sm">
                        <Card.Header className="bg-primary text-white">
                            <h4 className="mb-0">📊 Bill Generation</h4>
                        </Card.Header>
                        <Card.Body>
                            {/* Date Range Selection */}
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
                                <Col md={6}>
                                    <Form.Label>Quick Date Presets</Form.Label>
                                    <div className="d-flex gap-2 flex-wrap">
                                        <Button size="sm" variant="outline-secondary" onClick={() => applyDatePreset('thisWeek')}>
                                            This Week
                                        </Button>
                                        <Button size="sm" variant="outline-secondary" onClick={() => applyDatePreset('lastWeek')}>
                                            Last Week
                                        </Button>
                                        <Button size="sm" variant="outline-secondary" onClick={() => applyDatePreset('thisMonth')}>
                                            This Month
                                        </Button>
                                        <Button size="sm" variant="outline-secondary" onClick={() => applyDatePreset('lastMonth')}>
                                            Last Month
                                        </Button>
                                        <Button size="sm" variant="outline-secondary" onClick={() => applyDatePreset('thisQuarter')}>
                                            This Quarter
                                        </Button>
                                    </div>
                                </Col>
                            </Row>

                            {/* Admin User Selector */}
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
                                            <Form.Text className="text-muted">
                                                As an admin, you can generate bills for any user
                                            </Form.Text>
                                        </Form.Group>
                                    </Col>
                                </Row>
                            )}

                            <Row className="mb-4">
                                <Col md={3} className="d-flex align-items-end">
                                    <Button
                                        variant="success"
                                        onClick={generateBillData}
                                        disabled={loading}
                                        className="w-100"
                                    >
                                        {loading ? (
                                            <>
                                                <Spinner size="sm" className="me-2" />
                                                Generating...
                                            </>
                                        ) : (
                                            'Generate Bill Data'
                                        )}
                                    </Button>
                                </Col>
                            </Row>

                            {error && (
                                <Alert variant="danger">
                                    {error}
                                </Alert>
                            )}

                            {saveMessage && (
                                <Alert
                                    variant={saveMessage.type === 'success' ? 'success' : 'danger'}
                                    dismissible
                                    onClose={() => setSaveMessage(null)}
                                >
                                    {saveMessage.text}
                                </Alert>
                            )}

                            {/* Progress Indicator */}
                            {loading && (
                                <Card className="mb-4">
                                    <Card.Body className="d-flex align-items-center gap-3 py-3">
                                        <Spinner animation="border" variant="primary" size="sm" />
                                        <span className="text-muted" style={{ fontSize: '0.9rem' }}>
                                            {processingStatus || 'Generating bill data…'}
                                            {elapsedSeconds > 0 && (
                                                <span className="ms-2 text-secondary">({elapsedSeconds}s)</span>
                                            )}
                                        </span>
                                    </Card.Body>
                                </Card>
                            )}

                            {/* Bill Data Table */}
                            {billData && (
                                <>
                                    <div className="d-flex justify-content-between align-items-center mb-3">
                                        <div>
                                            <h5>Bill Entries</h5>
                                            <p className="text-muted mb-0">
                                                Total Entries: {billData.total_entries} |
                                                Total Fees: ₹{billData.total_fees?.toLocaleString() || 0}
                                            </p>
                                            {(() => {
                                                const linked = (billData.bill_entries || []).filter(e => e.order_link).length;
                                                const total = (billData.bill_entries || []).length;
                                                if (!total) return null;
                                                return (
                                                    <p className="mb-0" style={{ fontSize: '0.85rem' }}>
                                                        <span style={{ color: linked === total ? '#198754' : '#dc3545', fontWeight: 500 }}>
                                                            🔗 {linked}/{total} orders linked
                                                        </span>
                                                        {linked < total && (
                                                            <span className="text-muted ms-2">
                                                                ({total - linked} not yet fetched)
                                                            </span>
                                                        )}
                                                    </p>
                                                );
                                            })()}
                                        </div>
                                        {(() => {
                                            // Three separate ways an entry can be a guess. All of
                                            // them change what you are claiming, so all of them are
                                            // stated before you submit.
                                            const entries = billData.bill_entries || [];
                                            const lowName = entries.filter(e => e.confidence_score != null && e.confidence_score < 0.7);
                                            const lowCat = entries.filter(e => e.order_category_confidence != null && e.order_category_confidence < 0.55);
                                            const assumed = entries.filter(e => isUnverifiedResult(e.results));
                                            if (!lowName.length && !lowCat.length && !assumed.length) return null;
                                            const plural = (n, s, p) => `${n} ${n === 1 ? s : p}`;
                                            return (
                                                <Alert variant="warning" className="mb-0 py-2" style={{ fontSize: '0.85rem' }}>
                                                    <strong>Check these before saving — highlighted below.</strong>
                                                    <ul className="mb-0 mt-1" style={{ paddingLeft: '1.1rem' }}>
                                                        {assumed.length > 0 && (
                                                            <li>{plural(assumed.length, 'entry has', 'entries have')} no order on file — adjournment assumed.</li>
                                                        )}
                                                        {lowCat.length > 0 && (
                                                            <li>{plural(lowCat.length, 'outcome was', 'outcomes were')} classified with low confidence — the outcome sets the fee.</li>
                                                        )}
                                                        {lowName.length > 0 && (
                                                            <li>{plural(lowName.length, 'entry was', 'entries were')} matched to your name with low confidence — they may not be yours.</li>
                                                        )}
                                                    </ul>
                                                </Alert>
                                            );
                                        })()}
                                        <div>
                                            <Button variant="outline-success" size="sm" onClick={addNewRow} className="me-2">
                                                + Add Row
                                            </Button>
                                            <Button variant="outline-warning" size="sm" onClick={() => setBulkEditMode(!bulkEditMode)} className="me-2">
                                                {bulkEditMode ? 'Cancel Bulk Edit' : '✏️ Bulk Edit'}
                                            </Button>
                                            {exportMessage && (
                                                <Alert
                                                    variant={exportMessage.type === 'success' ? 'success' : 'danger'}
                                                    dismissible
                                                    className="mb-0 py-1 px-2 me-2"
                                                    style={{ fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center' }}
                                                    onClose={() => setExportMessage(null)}
                                                >
                                                    {exportMessage.text}
                                                </Alert>
                                            )}
                                        <Button variant="success" size="sm" onClick={exportMultipleFormats} className="me-2">
                                                Export Excel (XLSX)
                                            </Button>
                                            <Button variant="primary" size="sm" onClick={() => setShowSaveModal(true)}>
                                                💾 Save Bill
                                            </Button>
                                        </div>
                                    </div>

                                    {/* Bulk Operations Panel */}
                                    {bulkEditMode && (
                                        <Card className="mb-3 border-warning">
                                            <Card.Body className="bg-light">
                                                <Row className="align-items-center">
                                                    <Col md={4}>
                                                        <div className="d-flex align-items-center">
                                                            <Form.Check
                                                                type="checkbox"
                                                                label="Select All"
                                                                checked={selectedRows.size === billData?.bill_entries?.length && billData?.bill_entries?.length > 0}
                                                                onChange={selectAllRows}
                                                                className="me-3"
                                                            />
                                                            <span className="text-muted">
                                                                {selectedRows.size} row(s) selected
                                                            </span>
                                                        </div>
                                                    </Col>
                                                    <Col md={4}>
                                                        <Form.Group>
                                                            <Form.Label className="small mb-1">Set outcome for selected rows</Form.Label>
                                                            <Form.Select
                                                                size="sm"
                                                                value={bulkFeeValue}
                                                                onChange={(e) => setBulkFeeValue(e.target.value)}
                                                                title="The fee is set automatically from the outcome."
                                                            >
                                                                <option value="">Select outcome…</option>
                                                                {BILLING_OUTCOMES.map(option => (
                                                                    <option key={option.result} value={option.result}>
                                                                        {option.label} — {formatFee(option.fee)}
                                                                    </option>
                                                                ))}
                                                            </Form.Select>
                                                        </Form.Group>
                                                    </Col>
                                                    <Col md={4}>
                                                        <Button
                                                            variant="warning"
                                                            size="sm"
                                                            onClick={applyBulkFeeUpdate}
                                                            disabled={!bulkFeeValue || selectedRows.size === 0}
                                                            className="w-100"
                                                        >
                                                            Apply to {selectedRows.size} rows
                                                        </Button>
                                                    </Col>
                                                </Row>
                                            </Card.Body>
                                        </Card>
                                    )}

                                    <div className="table-responsive">
                                        <Table striped bordered hover>
                                            <thead className="table-dark">
                                                <tr>
                                                    {bulkEditMode && <th width="50px">☑️</th>}
                                                    <th>Date</th>
                                                    <th>Case Type</th>
                                                    <th>Case No</th>
                                                    <th>Case Year</th>
                                                    <th>Parties Name</th>
                                                    <th>Results</th>
                                                    <th style={{ width: '70px', textAlign: 'center' }}>Order</th>
                                                    <th>Fees (₹)</th>
                                                    <th>Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {billData.bill_entries.length === 0 ? (
                                                    <tr>
                                                        <td colSpan={bulkEditMode ? "10" : "9"} className="text-center py-5">
                                                            <div className="text-muted">
                                                                <h5>📭 No cases found</h5>
                                                                <p className="mb-0">
                                                                    No matching cases were found for <strong>{billData.user_name}</strong> in the selected date range.
                                                                    <br />
                                                                    This could mean:
                                                                </p>
                                                                <ul className="list-unstyled mt-2">
                                                                    <li>• No cases assigned to this user in this period</li>
                                                                    <li>• User name doesn't match any AGP names in the system</li>
                                                                    <li>• Try adjusting the date range or selecting a different user</li>
                                                                </ul>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                ) : billData.bill_entries.map((entry, index) => {
                                                    // Flag any of the three kinds of guess, so the
                                                    // marker on the row matches the banner above.
                                                    const needsCheck = !selectedRows.has(index) && (
                                                        (entry.confidence_score != null && entry.confidence_score < 0.7)
                                                        || (entry.order_category_confidence != null && entry.order_category_confidence < 0.55)
                                                        || isUnverifiedResult(entry.results)
                                                    );
                                                    return (
                                                    <tr
                                                        key={index}
                                                        className={selectedRows.has(index) ? 'table-warning' : ''}
                                                        style={needsCheck ? { borderLeft: '3px solid #ffc107' } : undefined}
                                                    >
                                                        {bulkEditMode && (
                                                            <td>
                                                                <Form.Check
                                                                    type="checkbox"
                                                                    checked={selectedRows.has(index)}
                                                                    onChange={() => toggleRowSelection(index)}
                                                                />
                                                            </td>
                                                        )}
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Control
                                                                    type="date"
                                                                    value={tempEditData.date || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, date: e.target.value})}
                                                                />
                                                            ) : (
                                                                entry.date
                                                            )}
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Control
                                                                    type="text"
                                                                    value={tempEditData.case_type || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, case_type: e.target.value})}
                                                                    size="sm"
                                                                />
                                                            ) : (
                                                                entry.case_type
                                                            )}
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Control
                                                                    type="text"
                                                                    value={tempEditData.case_no || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, case_no: e.target.value})}
                                                                    size="sm"
                                                                />
                                                            ) : (
                                                                entry.case_no
                                                            )}
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Control
                                                                    type="text"
                                                                    value={tempEditData.case_year || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, case_year: e.target.value})}
                                                                    size="sm"
                                                                />
                                                            ) : (
                                                                entry.case_year
                                                            )}
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Control
                                                                    as="textarea"
                                                                    rows={2}
                                                                    value={tempEditData.parties_name || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, parties_name: e.target.value})}
                                                                />
                                                            ) : (
                                                                <div style={{maxWidth: '200px', fontSize: '0.9em'}}>
                                                                    {entry.parties_name}
                                                                </div>
                                                            )}
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <Form.Select
                                                                    value={tempEditData.results || DEFAULT_OUTCOME.result}
                                                                    onChange={(e) => {
                                                                        const result = e.target.value;
                                                                        setTempEditData({
                                                                            ...tempEditData,
                                                                            results: result,
                                                                            fees_rs: feeForResult(result)
                                                                        });
                                                                    }}
                                                                    title="What the court did. The fee follows from this."
                                                                >
                                                                    {/* An unverified entry keeps its marker as an option so
                                                                        editing another field cannot silently confirm it. */}
                                                                    {isUnverifiedResult(tempEditData.results) && (
                                                                        <option value={UNVERIFIED_RESULT}>
                                                                            {labelForResult(UNVERIFIED_RESULT)}
                                                                        </option>
                                                                    )}
                                                                    {BILLING_OUTCOMES.map(option => (
                                                                        <option key={option.result} value={option.result}>
                                                                            {option.label} — {formatFee(option.fee)}
                                                                        </option>
                                                                    ))}
                                                                </Form.Select>
                                                            ) : (
                                                                <span
                                                                    className={`badge ${
                                                                        isUnverifiedResult(entry.results) ? 'bg-secondary' :
                                                                        entry.results.includes('DISPOSED') ? 'bg-success' :
                                                                        entry.results.includes('ADJOURNED') ? 'bg-warning' : 'bg-info'
                                                                    }`}
                                                                    title={isUnverifiedResult(entry.results)
                                                                        ? 'No analysed order on file for this hearing — adjournment assumed. Check before billing.'
                                                                        : undefined}
                                                                >
                                                                    {labelForResult(entry.results)}
                                                                </span>
                                                            )}
                                                        </td>
                                                        <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>
                                                            {entry.order_link ? (
                                                                <a
                                                                    href={getApiUrl(`/orders/pdf/${entry.id}`)}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    title={`View order PDF (${entry.order_category || 'linked'})`}
                                                                    style={{ textDecoration: 'none', fontSize: '1.1rem' }}
                                                                >
                                                                    🔗
                                                                </a>
                                                            ) : (
                                                                <span
                                                                    title="No order linked yet"
                                                                    style={{ color: '#adb5bd', fontSize: '1rem' }}
                                                                >
                                                                    —
                                                                </span>
                                                            )}
                                                        </td>
                                                        <td>
                                                            <strong>₹{(editingRow === index ? tempEditData.fees_rs : entry.fees_rs)?.toLocaleString()}</strong>
                                                        </td>
                                                        <td>
                                                            {editingRow === index ? (
                                                                <div className="d-flex gap-1">
                                                                    <Button size="sm" variant="success" onClick={saveEdit}>
                                                                        ✓
                                                                    </Button>
                                                                    <Button size="sm" variant="secondary" onClick={cancelEdit}>
                                                                        ✗
                                                                    </Button>
                                                                </div>
                                                            ) : (
                                                                <div className="d-flex gap-1">
                                                                    <Button size="sm" variant="outline-primary" onClick={() => startEditRow(index)}>
                                                                        ✏️
                                                                    </Button>
                                                                    <Button size="sm" variant="outline-danger" onClick={() => deleteRow(index)}>
                                                                        🗑️
                                                                    </Button>
                                                                </div>
                                                            )}
                                                        </td>
                                                    </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </Table>
                                    </div>
                                </>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>

            {/* Save Bill Modal */}
            <Modal show={showSaveModal} onHide={() => setShowSaveModal(false)}>
                <Modal.Header closeButton>
                    <Modal.Title>Save Bill</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <table className="table table-sm table-borderless mb-0" style={{ fontSize: '0.9rem' }}>
                        <tbody>
                            <tr>
                                <td className="text-muted fw-semibold" style={{ width: '40%' }}>Entries</td>
                                <td>{billData?.total_entries ?? (billData?.bill_entries?.length ?? 0)}</td>
                            </tr>
                            <tr>
                                <td className="text-muted fw-semibold">Total Fees</td>
                                <td>₹{(billData?.total_fees ?? 0).toLocaleString('en-IN')}</td>
                            </tr>
                            <tr>
                                <td className="text-muted fw-semibold">Date Range</td>
                                <td>{dateRange.startDate} → {dateRange.endDate}</td>
                            </tr>
                            {isAdmin && selectedUser && (
                                <tr>
                                    <td className="text-muted fw-semibold">AGP</td>
                                    <td>{selectedUser}</td>
                                </tr>
                            )}
                            <tr>
                                <td className="text-muted fw-semibold">Bill Number</td>
                                <td className="text-muted">Assigned on save</td>
                            </tr>
                        </tbody>
                    </table>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowSaveModal(false)}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={saveBill} disabled={saveBillLoading}>
                        {saveBillLoading ? (
                            <>
                                <Spinner size="sm" className="me-2" />
                                Saving...
                            </>
                        ) : (
                            'Save Bill'
                        )}
                    </Button>
                </Modal.Footer>
            </Modal>
        </Container>
    );
};

export default BillGeneration;
