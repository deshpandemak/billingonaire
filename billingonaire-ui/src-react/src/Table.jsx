import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from './config';
import Header from './Header';
import { Container } from 'react-bootstrap';

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
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header />
      <Container fluid className="flex-grow-1 d-flex flex-column p-0">
        <div className="table-container" style={{ display: 'flex', maxWidth: '1000px' }}>
          {/* Collapsible search panel on right */}
          <div style={{ width: searchOpen ? 300 : 40, transition: 'width 0.3s', background: '#f5f5f5', borderLeft: '1px solid #ccc', minHeight: '100vh', position: 'relative' }}>
            <button onClick={() => setSearchOpen((open) => !open)} style={{ position: 'absolute', left: -40, top: 20, zIndex: 2, background: '#007bff', color: '#fff', border: 'none', borderRadius: '0 4px 4px 0', width: 40, height: 40, cursor: 'pointer' }}>{searchOpen ? '<' : '>'}</button>
            {searchOpen && (
              <div className="search-criteria" style={{ padding: 20 }}>
                <h3>Search Criteria</h3>
                <label htmlFor="startDate">Start Date</label>
                <input type="date" id="startDate" value={searchCriteria.startDate} onChange={e => setSearchCriteria(sc => ({ ...sc, startDate: e.target.value }))} />
                <label htmlFor="endDate">End Date</label>
                <input type="date" id="endDate" value={searchCriteria.endDate} onChange={e => setSearchCriteria(sc => ({ ...sc, endDate: e.target.value }))} />
                <label htmlFor="advocateName">Advocate Name</label>
                <input type="text" id="advocateName" value={searchCriteria.advocateName} onChange={e => setSearchCriteria(sc => ({ ...sc, advocateName: e.target.value }))} />
                <label htmlFor="caseNumber">Case Number</label>
                <input type="text" id="caseNumber" value={searchCriteria.caseNumber} onChange={e => setSearchCriteria(sc => ({ ...sc, caseNumber: e.target.value }))} />
                <label htmlFor="caseType">Case Type</label>
                <select id="caseType" value={searchCriteria.caseType} onChange={e => setSearchCriteria(sc => ({ ...sc, caseType: e.target.value }))}>
                  <option value="">Select Case Type</option>
                  <option value="WP">WP</option>
                  <option value="IA">IA</option>
                  <option value="CP">CP</option>
                  <option value="PIL">PIL</option>
                  <option value="CAW">CAW</option>
                </select>
                <label htmlFor="caseYear">Case Year</label>
                <input type="text" id="caseYear" value={searchCriteria.caseYear} onChange={e => setSearchCriteria(sc => ({ ...sc, caseYear: e.target.value }))} />
                <label htmlFor="caseStage">Case Stage</label>
                <select id="caseStage" value={searchCriteria.caseStage} onChange={e => setSearchCriteria(sc => ({ ...sc, caseStage: e.target.value }))}>
                  <option value="">Select Case Stage</option>
                  <option value="Registration">Registration</option>
                  <option value="Stamp">Stamp</option>
                </select>
                <button type="button" onClick={() => fetchData()}>Search</button>
              </div>
            )}
          </div>
          {/* Data table on left */}
          <div style={{ flex: 1, padding: '1rem' }}>
            <h1>Table Data</h1>
            <div className="overflow-x-auto">
              <table className="min-w-full bg-white border border-gray-300">
                <thead>
                  <tr>
                    {columns.map(column => (
                      <th key={column.key} className="py-2 px-4 border-b border-gray-300">{column.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {editedData.map((row, index) => (
                    <tr key={index}>
                      {columns.map(column => (
                        <td key={column.key} className="py-2 px-4 border-b border-gray-300">
                          {column.key === 'Actions' ? (
                            <button type="button" onClick={() => deleteRow(index)} className="mr-2 p-1 bg-red-500 text-white rounded">Delete</button>
                          ) : (
                            <input
                              type="text"
                              value={row[column.key] || ''}
                              onChange={e => {
                                const value = e.target.value;
                                setEditedData(prev => prev.map((r, i) => i === index ? { ...r, [column.key]: value } : r));
                              }}
                              className="w-full p-1 border border-gray-300 rounded"
                            />
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={addRow} className="mt-2 p-2 bg-green-500 text-white rounded">Add Row</button>
            <button type="button" onClick={saveData} className="mt-2 p-2 bg-blue-500 text-white rounded">Save</button>
            <button type="button" onClick={cancelEdit} className="mt-2 p-2 bg-gray-500 text-white rounded">Cancel</button>
          </div>
        </div>
      </Container>
      <footer className="bg-light text-center text-muted py-3 mt-auto border-top w-100">
        &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
      </footer>
    </div>
  );
};

export default Table;
