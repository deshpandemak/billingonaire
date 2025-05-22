import React, { useRef, useState, useEffect } from 'react';
// import { useNavigate } from 'react-router-dom'; // Uncomment if using React Router
// import { auth } from '../lib/firebase'; // Adjust import if you migrate firebase logic
// import { onAuthStateChanged } from 'firebase/auth'; // Uncomment if using Firebase Auth
import { API_BASE_URL } from './config';

const Upload = () => {
  // const navigate = useNavigate(); // Uncomment if using React Router
  const fileInput = useRef();
  const [dataframe, setDataframe] = useState(null);
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [tableData, setTableData] = useState([]);
  const [editedData, setEditedData] = useState([]);
  const [skipPreview, setSkipPreview] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [showModal, setShowModal] = useState(false);

  // useEffect(() => {
  //   onAuthStateChanged(auth, (user) => {
  //     if (!user) {
  //       navigate('/login');
  //     }
  //   });
  // }, [navigate]);

  const uploadFile = async (e) => {
    e.preventDefault();
    setIsUploading(true);
    setError('');
    const formData = new FormData();
    if (!fileInput.current.files[0]) {
      setError('Please select a file.');
      setIsUploading(false);
      return;
    }
    formData.append('file', fileInput.current.files[0]);
    formData.append('skip_preview', skipPreview);

    const maxRetries = 3;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await fetch(`${API_BASE_URL}/upload-pdf`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        if (!response.ok) {
          throw new Error('Failed to upload file');
        }
        const data = await response.json();
        if (skipPreview) {
          setSuccessMessage(data.message);
        } else {
          setDataframe(data);
          setTableData(data.data);
          setEditedData(JSON.parse(JSON.stringify(data.data)));
          setShowModal(true);
        }
        break;
      } catch (e) {
        setError(e.message);
        if (
          e.message.includes('Connection was reset by the remote host') &&
          attempt < maxRetries - 1
        ) {
          await new Promise((resolve) => setTimeout(resolve, 1000));
        } else {
          break;
        }
      } finally {
        setIsUploading(false);
      }
    }
  };

  const saveData = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/save-data`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ data: editedData }),
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error('Failed to save data');
      }
      const result = await response.json();
      // Optionally show a message or update state
      setSuccessMessage('Data saved successfully');
    } catch (e) {
      setError(e.message);
    }
  };

  const cancelEdit = () => {
    setEditedData(JSON.parse(JSON.stringify(tableData)));
  };

  const addRow = () => {
    setEditedData((prev) => [...prev, {}]);
  };

  const deleteRow = (index) => {
    setEditedData((prev) => prev.filter((_, i) => i !== index));
  };

  const toggleEdit = (index) => {
    setEditedData((prev) =>
      prev.map((row, i) =>
        i === index ? { ...row, isEditable: !row.isEditable } : row
      )
    );
  };

  return (
    <div className="upload-container">
      <h1>Upload PDF</h1>
      <form onSubmit={uploadFile}>
        <div>
          <label htmlFor="file">Choose PDF file</label>
          <input type="file" id="file" accept="application/pdf" ref={fileInput} required />
        </div>
        <div>
          <label htmlFor="skipPreview">Skip Preview</label>
          <input
            type="checkbox"
            id="skipPreview"
            checked={skipPreview}
            onChange={(e) => setSkipPreview(e.target.checked)}
          />
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={isUploading}>
          Upload
        </button>
      </form>
      {successMessage && <p className="success">{successMessage}</p>}
      {showModal && (
        <div className="modal">
          <div className="modal-content">
            <span className="close" onClick={() => setShowModal(false)}>
              &times;
            </span>
            <h2>Dataframe</h2>
            <table>
              <thead>
                <tr>
                  {editedData[0] &&
                    Object.keys(editedData[0]).map((key) => <th key={key}>{key}</th>)}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {editedData.map((row, index) => (
                  <tr key={index}>
                    {Object.keys(row).map((key) => (
                      <td key={key}>
                        <input
                          type="text"
                          value={row[key]}
                          readOnly={!row.isEditable}
                          className="table-input"
                          onChange={(e) => {
                            const value = e.target.value;
                            setEditedData((prev) =>
                              prev.map((r, i) =>
                                i === index ? { ...r, [key]: value } : r
                              )
                            );
                          }}
                        />
                      </td>
                    ))}
                    <td>
                      <button
                        onClick={() => toggleEdit(index)}
                        className="icon-button"
                        title={row.isEditable ? 'Save' : 'Edit'}
                        type="button"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          className="icon"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="2"
                            d="M11 17l-4 4m0 0l4-4m-4 4V3m13 13l-4 4m0 0l4-4m-4 4V3"
                          />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="button-row">
              <button type="button" onClick={addRow}>
                Add Row
              </button>
              <button type="button" onClick={saveData}>
                Save
              </button>
              <button type="button" onClick={cancelEdit}>
                Cancel
              </button>
              <button type="button" onClick={() => deleteRow()} className="delete-row">
                Delete Row
              </button>
            </div>
          </div>
        </div>
      )}
      <style>{`
        .upload-container {
          max-width: 600px;
          margin: 0 auto;
          padding: 1rem;
          border: 1px solid #ccc;
          border-radius: 4px;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
          background-color: #fff;
        }
        h1 {
          text-align: center;
          color: #333;
        }
        form {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        label {
          margin-bottom: 0.5rem;
          color: #333;
        }
        input {
          margin-bottom: 1rem;
          padding: 0.5rem;
          border: 1px solid #ccc;
          border-radius: 4px;
          width: 100%;
        }
        .error {
          color: red;
          margin-bottom: 1rem;
        }
        .success {
          color: green;
          margin-bottom: 1rem;
        }
        button {
          padding: 0.5rem;
          border: none;
          border-radius: 4px;
          background-color: #007bff;
          color: white;
          cursor: pointer;
          width: 100%;
        }
        button:hover {
          background-color: #0056b3;
        }
        .modal {
          display: block;
          position: fixed;
          z-index: 1;
          left: 0;
          top: 0;
          width: 100%;
          height: 100%;
          overflow: auto;
          background-color: rgb(0,0,0);
          background-color: rgba(0,0,0,0.4);
        }
        .modal-content {
          background-color: #fefefe;
          margin: 15% auto;
          padding: 20px;
          border: 1px solid #888;
          width: 80%;
          overflow-y: auto;
          max-height: 80vh;
        }
        .close {
          color: #aaa;
          float: right;
          font-size: 28px;
          font-weight: bold;
        }
        .close:hover,
        .close:focus {
          color: black;
          text-decoration: none;
          cursor: pointer;
        }
        .dataframe {
          margin-top: 1rem;
          width: 100%;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
        }
        th,
        td {
          padding: 0.3rem;
          border: 1px solid #ccc;
          text-align: left;
          word-wrap: break-word;
        }
        th {
          background-color: #f8f8f8;
        }
        .table-input {
          width: 100%;
          padding: 0.2rem;
          border: none;
          background-color: transparent;
        }
        .table-input[readonly] {
          color: #666;
        }
        .icon-button {
          background: none;
          border: none;
          cursor: pointer;
          padding: 0.2rem;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .icon-button:hover {
          background-color: #f0f0f0;
          border-radius: 4px;
        }
        .icon {
          width: 16px;
          height: 16px;
          color: #007bff;
        }
        .icon-button:hover .icon {
          color: #0056b3;
        }
        .button-row {
          display: flex;
          justify-content: flex-end;
          gap: 0.5rem;
          margin-top: 1rem;
        }
        .button-row button {
          padding: 0.3rem 0.6rem;
          font-size: 0.9rem;
          border-radius: 4px;
        }
        .delete-row {
          background-color: #ff4d4d;
          color: white;
        }
        .delete-row:hover {
          background-color: #cc0000;
        }
      `}</style>
    </div>
  );
};

export default Upload;
