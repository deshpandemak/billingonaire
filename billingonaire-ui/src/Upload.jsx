import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { API_BASE_URL } from './config';
import { Container, Row, Col, Button, ProgressBar, Alert, Form } from 'react-bootstrap';

const Upload = () => {
  const navigate = useNavigate();
  const fileInput = useRef();
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState({});
  const [fileResults, setFileResults] = useState({});
  const [successMessage, setSuccessMessage] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [user, setUser] = useState(null);

  React.useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setUser(user);
    });
    return () => unsubscribe();
  }, []);

  const handleFileChange = (e) => {
    setSelectedFiles(Array.from(e.target.files));
  };

  const uploadFile = async (e) => {
    e.preventDefault();
    setIsUploading(true);
    setError('');
    setProgress({});
    setFileResults({});
    const files = fileInput.current.files;
    if (!files.length) {
      setError('Please select at least one file.');
      setIsUploading(false);
      return;
    }
    await Promise.all(
      Array.from(files).map(async (file) => {
        const formData = new FormData();
        formData.append('files', file);
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('POST', `${API_BASE_URL}/upload-pdf`, true);
          xhr.withCredentials = true;
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
              setProgress((prev) => ({ ...prev, [file.name]: Math.round((event.loaded / event.total) * 100) }));
            }
          };
          const uploadPromise = new Promise((resolve, reject) => {
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                resolve(JSON.parse(xhr.responseText));
              } else {
                reject(new Error(xhr.statusText));
              }
            };
            xhr.onerror = () => reject(new Error('Upload failed'));
          });
          xhr.send(formData);
          const result = await uploadPromise;
          const fileResult = result.results?.[0] || {};
          setFileResults((prev) => ({ ...prev, [file.name]: fileResult }));
        } catch (e) {
          setError(`Error uploading ${file.name}: ${e.message}`);
          setFileResults((prev) => ({ ...prev, [file.name]: { error: e.message } }));
        }
      })
    );
    setIsUploading(false);
    setSuccessMessage('Upload complete!');
  };

  // Helper to get icon for file type (PDF only for now)
  const getFileIcon = () => (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#d32f2f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginRight: '0.5rem', minWidth: 32}}>
      <rect x="3" y="3" width="18" height="18" rx="2" fill="#fff" stroke="#d32f2f"/>
      <text x="7" y="19" fontSize="10" fill="#d32f2f" fontWeight="bold">PDF</text>
    </svg>
  );

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Container fluid className="flex-grow-1 d-flex flex-column align-items-center justify-content-center p-0">
        <Row className="w-100 justify-content-center">
          <Col xs={12} sm={10} md={8} lg={7} xl={6}>
            <div className="upload-container py-4">
              <h1 className="mb-4 text-center">Upload PDF</h1>
              {user ? (
                <>
                  <Form onSubmit={uploadFile}>
                    <Form.Group controlId="file" className="mb-3">
                      <Form.Label>Choose PDF file(s)</Form.Label>
                      <Form.Control
                        type="file"
                        accept="application/pdf"
                        ref={fileInput}
                        multiple
                        required
                        onChange={handleFileChange}
                        disabled={isUploading}
                      />
                    </Form.Group>
                    {selectedFiles.length > 0 && (
                      <div className="file-list mb-3">
                        <strong>Selected file{selectedFiles.length > 1 ? 's' : ''}:</strong>
                        <ul style={{listStyle: 'none', padding: 0, margin: 0}}>
                          {selectedFiles.map((file) => (
                            <li key={file.name} style={{display: 'flex', alignItems: 'center', marginBottom: '0.5rem', overflow: 'hidden'}}>
                              {getFileIcon()}
                              <span style={{whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 200}}>{file.name}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {error && <Alert variant="danger">{error}</Alert>}
                    <Button type="submit" variant="primary" disabled={isUploading || selectedFiles.length === 0} className="w-100">
                      {isUploading ? 'Uploading...' : 'Upload'}
                    </Button>
                  </Form>
                  {selectedFiles.length > 0 && (
                    <div style={{ marginTop: '1.5rem' }}>
                      <h4>Upload Progress</h4>
                      {selectedFiles.map((file) => {
                        const percent = progress[file.name] || 0;
                        const result = fileResults[file.name] || {};
                        let status = '';
                        if (result.error) {
                          status = `Error: ${result.error}`;
                        } else if (typeof result.records_processed === 'number') {
                          status = `${percent}% - ${result.records_processed} record${result.records_processed !== 1 ? 's' : ''} processed`;
                        } else {
                          status = `${percent}%`;
                        }
                        return (
                          <div key={file.name} style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', overflow: 'hidden' }}>
                            {getFileIcon()}
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 0 }}>
                                <span style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 200 }}>{file.name}</span>
                                <span style={{ color: result.error ? 'red' : '#388e3c', fontWeight: 500, marginLeft: 8 }}>
                                  {status}
                                </span>
                              </div>
                              <ProgressBar now={percent} label={`${percent}%`} style={{ width: '100%' }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {successMessage && <Alert variant="success" className="mt-3">{successMessage}</Alert>}
                </>
              ) : (
                <Alert variant="danger" className="text-center mt-4">Please log in to upload files.</Alert>
              )}
            </div>
          </Col>
        </Row>
      </Container>
    </div>
  );
};

export default Upload;
