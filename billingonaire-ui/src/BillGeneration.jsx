import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Form, Button, Table, Alert, Modal, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON, authenticatedFetch } from './lib/api.js';
import { auth } from './lib/firebase.js';
import { onAuthStateChanged } from 'firebase/auth';

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
    const [processingProgress, setProcessingProgress] = useState(0);
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

            const response = await authenticatedFetchJSON(queryUrl);
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
        const feeAmount = Number(tempEditData.fees_rs) || 0;
        const updatedEntry = {
            ...tempEditData,
            fees_rs: feeAmount,
            results: getResultFromFee(feeAmount)
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
        const feeAmount = 1875;
        const newEntry = {
            id: `new_${Date.now()}`,
            date: formatDateSafe(new Date()),
            case_detail: '',
            case_type: '',
            case_no: '',
            case_year: '',
            parties_name: '',
            results: getResultFromFee(feeAmount),
            fees_rs: feeAmount,
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
        const feeAmount = Number(bulkFeeValue) || 0;
        const resultText = getResultFromFee(feeAmount);

        selectedRows.forEach(index => {
            updatedEntries[index] = {
                ...updatedEntries[index],
                fees_rs: feeAmount,
                results: resultText
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

    const exportToExcel = () => {
        if (!billData?.bill_entries?.length) return;

        // Create CSV content with proper escaping (matching Excel format)
        const headers = ['SR. NO.', 'DATE', 'CASE TYPE', 'CASE NO', 'CASE YEAR', 'RESULTS', 'PARTIES NAME', 'FEES (RS.)'];
        const totalFees = billData.bill_entries.reduce((sum, entry) => sum + Number(entry.fees_rs || 0), 0);

        const csvContent = [
            headers.map(escapeCSVField).join(','),
            ...billData.bill_entries.map((entry, index) => [
                escapeCSVField(index + 1),
                escapeCSVField(entry.date),
                escapeCSVField(entry.case_type || ''),
                escapeCSVField(entry.case_no || ''),
                escapeCSVField(entry.case_year || ''),
                escapeCSVField(entry.results),
                escapeCSVField(entry.parties_name),
                escapeCSVField(entry.fees_rs)
            ].join(',')),
            '', // Empty line before total
            [
                escapeCSVField(''),
                escapeCSVField(''),
                escapeCSVField(''),
                escapeCSVField(''),
                escapeCSVField(''),
                escapeCSVField(''),
                escapeCSVField('TOTAL:'),
                escapeCSVField(totalFees)
            ].join(',')
        ].join('\n');

        // Download file
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bill_${dateRange.startDate}_to_${dateRange.endDate}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    };

    const getFeeOptions = () => [
        { value: 1250, label: 'ADJOURNED (₹1,250)' },
        { value: 1875, label: 'HEARD & ADJN. (₹1,875)' },
        { value: 2500, label: 'WP DISPOSED OF (₹2,500)' }
    ];

    const getResultFromFee = (fee) => {
        switch (fee) {
            case 1250: return 'ADJOURNED';
            case 1875: return 'HEARD & ADJN.';
            case 2500: return 'WP DISPOSED OF';
            default: return 'HEARD & ADJN.';
        }
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
                                                Select User (Optional - leave empty for your own cases)
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
                                <Col md={3} className="d-flex align-items-end">
                                    <div className="d-grid gap-2 w-100">
                                        <Button variant="outline-primary" size="sm" href="/user-matters/role-config">
                                            Configure Role
                                        </Button>
                                    </div>
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
                                        </div>
                                        {(() => {
                                            const lowConf = (billData.bill_entries || []).filter(e => e.confidence_score != null && e.confidence_score < 0.7);
                                            if (!lowConf.length) return null;
                                            return (
                                                <Alert variant="warning" className="mb-0 py-2" style={{ fontSize: '0.85rem' }}>
                                                    <strong>{lowConf.length} {lowConf.length === 1 ? 'entry has' : 'entries have'} a low confidence score</strong> — highlighted below. Review before saving.
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
                                                            <Form.Label className="small mb-1">Update Fee for Selected Rows</Form.Label>
                                                            <Form.Select
                                                                size="sm"
                                                                value={bulkFeeValue}
                                                                onChange={(e) => setBulkFeeValue(e.target.value)}
                                                            >
                                                                <option value="">Select Fee Amount</option>
                                                                <option value="1250">ADJOURNED (₹1,250)</option>
                                                                <option value="1875">HEARD & ADJN. (₹1,875)</option>
                                                                <option value="2500">WP DISPOSED OF (₹2,500)</option>
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
                                                    <th>Fees (₹)</th>
                                                    <th>Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {billData.bill_entries.length === 0 ? (
                                                    <tr>
                                                        <td colSpan={bulkEditMode ? "9" : "8"} className="text-center py-5">
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
                                                    const isLowConf = !selectedRows.has(index)
                                                        && entry.confidence_score != null
                                                        && entry.confidence_score < 0.7;
                                                    return (
                                                    <tr
                                                        key={index}
                                                        className={selectedRows.has(index) ? 'table-warning' : ''}
                                                        style={isLowConf ? { borderLeft: '3px solid #ffc107' } : undefined}
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
                                                                    value={tempEditData.fees_rs || 1875}
                                                                    onChange={(e) => {
                                                                        const fee = parseInt(e.target.value);
                                                                        setTempEditData({
                                                                            ...tempEditData,
                                                                            fees_rs: fee,
                                                                            results: getResultFromFee(fee)
                                                                        });
                                                                    }}
                                                                >
                                                                    {getFeeOptions().map(option => (
                                                                        <option key={option.value} value={option.value}>
                                                                            {option.label}
                                                                        </option>
                                                                    ))}
                                                                </Form.Select>
                                                            ) : (
                                                                <span className={`badge ${
                                                                    entry.results.includes('DISPOSED') ? 'bg-success' :
                                                                    entry.results.includes('ADJOURNED') ? 'bg-warning' : 'bg-info'
                                                                }`}>
                                                                    {entry.results}
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
                    <p>Are you sure you want to save this bill with {billData?.total_entries} entries totaling ₹{billData?.total_fees?.toLocaleString()}?</p>
                    <p className="text-muted">
                        Date Range: {dateRange.startDate} to {dateRange.endDate}
                    </p>
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
