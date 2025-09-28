import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Form, Button, Table, Alert, Modal, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON } from './lib/api.js';

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

    // Set default date range to current month
    useEffect(() => {
        const today = new Date();
        const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        
        setDateRange({
            startDate: startOfMonth.toISOString().split('T')[0],
            endDate: endOfMonth.toISOString().split('T')[0]
        });
    }, []);

    const handleDateChange = (field, value) => {
        setDateRange(prev => ({
            ...prev,
            [field]: value
        }));
    };

    const generateBillData = async () => {
        if (!dateRange.startDate || !dateRange.endDate) {
            setError('Please select both start and end dates');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const response = await authenticatedFetchJSON(`/bills/generate?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`);
            setBillData(response);
        } catch (err) {
            setError(err.message || 'Failed to generate bill data');
        } finally {
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
        updatedEntries[editingRow] = { ...tempEditData };
        
        setBillData(prev => ({
            ...prev,
            bill_entries: updatedEntries,
            total_fees: updatedEntries.reduce((sum, entry) => sum + (entry.fees_rs || 0), 0)
        }));
        
        setEditingRow(null);
        setTempEditData({});
    };

    const deleteRow = (index) => {
        const updatedEntries = billData.bill_entries.filter((_, i) => i !== index);
        setBillData(prev => ({
            ...prev,
            bill_entries: updatedEntries,
            total_entries: updatedEntries.length,
            total_fees: updatedEntries.reduce((sum, entry) => sum + (entry.fees_rs || 0), 0)
        }));
    };

    const addNewRow = () => {
        const newEntry = {
            id: `new_${Date.now()}`,
            date: new Date().toISOString().split('T')[0],
            case_detail: '',
            parties_name: '',
            results: 'HEARD & ADJN.',
            fees_rs: 1875,
            confidence_score: 1.0,
            match_source: 'manual',
            editable: true
        };

        setBillData(prev => ({
            ...prev,
            bill_entries: [...prev.bill_entries, newEntry],
            total_entries: prev.bill_entries.length + 1,
            total_fees: prev.total_fees + newEntry.fees_rs
        }));
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

            alert(`Bill saved successfully! Bill ID: ${response.bill_id}`);
            setShowSaveModal(false);
        } catch (err) {
            alert('Failed to save bill: ' + err.message);
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

        // Create CSV content with proper escaping
        const headers = ['DATE', 'CASE DETAIL', 'PARTIES NAME', 'RESULTS', 'FEES (RS.)'];
        const totalFees = billData.bill_entries.reduce((sum, entry) => sum + (entry.fees_rs || 0), 0);
        
        const csvContent = [
            headers.map(escapeCSVField).join(','),
            ...billData.bill_entries.map(entry => [
                escapeCSVField(entry.date),
                escapeCSVField(entry.case_detail),
                escapeCSVField(entry.parties_name),
                escapeCSVField(entry.results),
                escapeCSVField(entry.fees_rs)
            ].join(',')),
            '', // Empty line before total
            [
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
                                        <div>
                                            <Button variant="outline-success" size="sm" onClick={addNewRow} className="me-2">
                                                + Add Row
                                            </Button>
                                            <Button variant="info" size="sm" onClick={exportToExcel} className="me-2">
                                                📊 Export Excel
                                            </Button>
                                            <Button variant="primary" size="sm" onClick={() => setShowSaveModal(true)}>
                                                💾 Save Bill
                                            </Button>
                                        </div>
                                    </div>

                                    <div className="table-responsive">
                                        <Table striped bordered hover>
                                            <thead className="table-dark">
                                                <tr>
                                                    <th>Date</th>
                                                    <th>Case Detail</th>
                                                    <th>Parties Name</th>
                                                    <th>Results</th>
                                                    <th>Fees (₹)</th>
                                                    <th>Confidence</th>
                                                    <th>Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {billData.bill_entries.map((entry, index) => (
                                                    <tr key={index}>
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
                                                                    value={tempEditData.case_detail || ''}
                                                                    onChange={(e) => setTempEditData({...tempEditData, case_detail: e.target.value})}
                                                                />
                                                            ) : (
                                                                entry.case_detail
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
                                                            <span className={`badge ${
                                                                entry.confidence_score >= 0.9 ? 'bg-success' :
                                                                entry.confidence_score >= 0.75 ? 'bg-warning' : 'bg-secondary'
                                                            }`}>
                                                                {(entry.confidence_score * 100).toFixed(0)}%
                                                            </span>
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
                                                ))}
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