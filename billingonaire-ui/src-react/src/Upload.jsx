import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { API_BASE_URL } from './config';
import Header from './Header';
import { Container } from 'react-bootstrap';

const Upload = () => {
  const navigate = useNavigate();
  const fileInput = useRef();
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState({}); // Track progress per file
  const [fileResults, setFileResults] = useState({}); // Store backend response per file
  const [successMessage, setSuccessMessage] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]); // Track selected files
  const [user, setUser] = useState(null);

  React.useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setUser(user);
    });
    return () => unsubscribe();
  }, []);

  const handleLogout = async () => {
    await signOut(auth);
    setUser(null);
    navigate('/login');
  };

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
    // Upload all files in parallel
    await Promise.all(
      Array.from(files).map(async (file) => {
        const formData = new FormData();
        formData.append('files', file); // 'files' matches FastAPI param
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
          // result.results is always an array, but we only sent one file
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
  const getFileIcon = (file) => {
    return (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#d32f2f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginRight: '0.5rem'}}>
        <rect x="3" y="3" width="18" height="18" rx="2" fill="#fff" stroke="#d32f2f"/>
        <text x="7" y="19" fontSize="10" fill="#d32f2f" fontWeight="bold">PDF</text>
      </svg>
    );
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header />
      <Container fluid className="flex-grow-1 d-flex flex-column p-0">
        <div className="upload-container">
          <h1>Upload PDF</h1>
          {/* Remove logout button here, as it's already in the main menu */}
          {/* Hide upload form and progress if not logged in */}
          {user ? (
            <>
              <form onSubmit={uploadFile}>
                <div>
                  <label htmlFor="file">Choose PDF file(s)</label>
                  <input
                    type="file"
                    id="file"
                    accept="application/pdf"
                    ref={fileInput}
                    multiple
                    required
                    onChange={handleFileChange}
                    disabled={isUploading}
                  />
                </div>
                {/* Show selected file icons and names only once */}
                {selectedFiles.length > 0 && (
                  <div className="file-list">
                    <strong>Selected file{selectedFiles.length > 1 ? 's' : ''}:</strong>
                    <ul style={{listStyle: 'none', padding: 0}}>
                      {selectedFiles.map((file) => (
                        <li key={file.name} style={{display: 'flex', alignItems: 'center', marginBottom: '0.5rem'}}>
                          {getFileIcon(file)}
                          <span>{file.name}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {error && <p className="error">{error}</p>}
                <button type="submit" disabled={isUploading || selectedFiles.length === 0}>
                  {isUploading ? 'Uploading...' : 'Upload'}
                </button>
              </form>
              {/* Show progress bars for each file, but not a separate status table */}
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
                      <div key={file.name} style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center' }}>
                        {getFileIcon(file)}
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontWeight: 500 }}>{file.name}</span>
                            <span style={{ color: result.error ? 'red' : '#388e3c', fontWeight: 500 }}>
                              {status}
                            </span>
                          </div>
                          <progress value={percent} max="100" style={{ width: '100%' }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {successMessage && <p className="success">{successMessage}</p>}
            </>
          ) : (
            <p style={{ color: '#d32f2f', textAlign: 'center', marginTop: '2rem' }}>Please log in to upload files.</p>
          )}
        </div>
      </Container>
      <footer className="bg-light text-center text-muted py-3 mt-auto border-top w-100">
        &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
      </footer>
    </div>
  );
};

export default Upload;
