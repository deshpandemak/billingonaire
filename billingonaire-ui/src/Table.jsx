import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from './config';
import { Container, Row, Col, Table as RBTable, Button, Form, Collapse, Card } from 'react-bootstrap';

const Table = () => {
  const [data, setData] = useState([]);
  const [editedData, setEditedData] = useState([]);
  const [searchCriteria, setSearchCriteria] = useState({
    startDate: '',
    endDate: '',
    advocateName: '',
    caseNumber: '',
    caseType: '',
    caseYear: '',
    caseStage: ''
  });
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    // By default, show today's data
    const today = new Date().toISOString().split('T')[0];
    setSearchCriteria((prev) => ({ ...prev, startDate: today, endDate: today }));
    fetchData({ ...searchCriteria, startDate: today, endDate: today });
    // eslint-disable-next-line
  }, []);

  const fetchData = async (criteria = searchCriteria) => {
    if (!criteria.startDate && !criteria.endDate && !criteria.advocateName && !criteria.caseNumber && !criteria.caseType && !criteria.caseYear && !criteria.caseStage) {
      alert('Please fill at least one search criteria');
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/get-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(criteria)
      });
      if (!response.ok) throw new Error('Failed to fetch data');
      const result = await response.json();
      setData(result);
      setEditedData(JSON.parse(JSON.stringify(result)));
    } catch (e) {
      console.error(e);
    }
  };

  const saveData = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/save-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editedData),
        credentials: 'include'
      });
      if (!response.ok) throw new Error('Failed to save data');
      await response.json();
      // Optionally show a message
    } catch (e) {
      console.error('Failed to save data:', e.message);
    }
  };

  const cancelEdit = () => {
    setEditedData(JSON.parse(JSON.stringify(data)));
  };

  const addRow = () => {
    setEditedData((prev) => [...prev, {}]);
  };

  const deleteRow = (index) => {
    setEditedData((prev) => prev.filter((_, i) => i !== index));
  };

  const columns = [
    { key: 'Date', label: 'Date', editable: true },
    { key: 'Case Type', label: 'Case Type', editable: true },
    { key: 'Case Number', label: 'Case Number', editable: true },
    { key: 'Case Year', label: 'Case Year', editable: true },
    { key: 'Case Stage', label: 'Case Stage', editable: true },
    { key: 'Advocate Name', label: 'Advocate Name', editable: true },
    { key: 'Actions', label: 'Actions', editable: false }
  ];

  return (
    <Container fluid className="py-4">
      <Row>
        {/* Collapsible Search Criteria Pane */}
        <Col xs="auto" className="pe-0">
          <Button
            variant="primary"
            onClick={() => setSearchOpen(open => !open)}
            aria-controls="search-collapse"
            aria-expanded={searchOpen}
            style={{ minHeight: 40, marginBottom: 10 }}
          >
            {searchOpen ? '<' : '>'}
          </Button>
          <Collapse in={searchOpen}>
            <div id="search-collapse">
              <Card style={{ width: 300, minHeight: 400 }}>
                <Card.Body>
                  <Card.Title>Search Criteria</Card.Title>
                  <Form>
                    <Form.Group className="mb-2">
                      <Form.Label>Start Date</Form.Label>
                      <Form.Control
                        type="date"
                        value={searchCriteria.startDate}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, startDate: e.target.value }))}
                      />
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>End Date</Form.Label>
                      <Form.Control
                        type="date"
                        value={searchCriteria.endDate}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, endDate: e.target.value }))}
                      />
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>Advocate Name</Form.Label>
                      <Form.Control
                        type="text"
                        value={searchCriteria.advocateName}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, advocateName: e.target.value }))}
                      />
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>Case Number</Form.Label>
                      <Form.Control
                        type="text"
                        value={searchCriteria.caseNumber}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, caseNumber: e.target.value }))}
                      />
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>Case Type</Form.Label>
                      <Form.Select
                        value={searchCriteria.caseType}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, caseType: e.target.value }))}
                      >
                        <option value="">Select Case Type</option>
                        <option value="WP">WP</option>
                        <option value="IA">IA</option>
                        <option value="CP">CP</option>
                        <option value="PIL">PIL</option>
                        <option value="CAW">CAW</option>
                      </Form.Select>
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>Case Year</Form.Label>
                      <Form.Control
                        type="text"
                        value={searchCriteria.caseYear}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, caseYear: e.target.value }))}
                      />
                    </Form.Group>
                    <Form.Group className="mb-2">
                      <Form.Label>Case Stage</Form.Label>
                      <Form.Select
                        value={searchCriteria.caseStage}
                        onChange={e => setSearchCriteria(sc => ({ ...sc, caseStage: e.target.value }))}
                      >
                        <option value="">Select Case Stage</option>
                        <option value="Registration">Registration</option>
                        <option value="Stamp">Stamp</option>
                      </Form.Select>
                    </Form.Group>
                    <Button variant="success" className="mt-2 w-100" onClick={() => fetchData()}>
                      Search
                    </Button>
                  </Form>
                </Card.Body>
              </Card>
            </div>
          </Collapse>
        </Col>
        {/* Data Table */}
        <Col>
          <h1>Table Data</h1>
          <div className="overflow-auto">
            <RBTable striped bordered hover responsive>
              <thead>
                <tr>
                  {columns.map(column => (
                    <th key={column.key}>{column.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {editedData.map((row, index) => (
                  <tr key={index}>
                    {columns.map(column => (
                      <td key={column.key}>
                        {column.key === 'Actions' ? (
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => deleteRow(index)}
                          >
                            Delete
                          </Button>
                        ) : (
                          <Form.Control
                            type="text"
                            value={row[column.key] || ''}
                            onChange={e => {
                              const value = e.target.value;
                              setEditedData(prev => prev.map((r, i) => i === index ? { ...r, [column.key]: value } : r));
                            }}
                            size="sm"
                          />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </RBTable>
          </div>
          <div className="d-flex gap-2 mt-3">
            <Button variant="success" onClick={addRow}>Add Row</Button>
            <Button variant="primary" onClick={saveData}>Save</Button>
            <Button variant="secondary" onClick={cancelEdit}>Cancel</Button>
          </div>
        </Col>
      </Row>
    </Container>
  );
};

export default Table;
