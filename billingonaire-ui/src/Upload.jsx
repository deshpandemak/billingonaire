import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged } from 'firebase/auth';
import './styles/professional.css';

const Upload = () => {
  const _navigate = useNavigate();
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
    setSuccessMessage('');
    
    const files = fileInput.current.files;
    if (!files.length) {
      setError('Please select at least one file.');
      setIsUploading(false);
      return;
    }

    try {
      // Process files one by one to show proper progress
      for (const file of Array.from(files)) {
        try {
          const formData = new FormData();
          formData.append('files', file);
          
          // Get authentication token
          const user = auth.currentUser;
          if (!user) {
            throw new Error('User not authenticated');
          }
          const idToken = await user.getIdToken(true); // Force refresh token
          
          // Create custom upload with progress tracking
          const uploadPromise = new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            
            // Set up progress tracking
            xhr.upload.onprogress = (event) => {
              if (event.lengthComputable) {
                const percent = Math.round((event.loaded / event.total) * 100);
                setProgress((prev) => ({ ...prev, [file.name]: percent }));
              }
            };
            
            // Handle response
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                resolve(JSON.parse(xhr.responseText));
              } else {
                reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`));
              }
            };
            
            xhr.onerror = () => reject(new Error('Network error during upload'));
            
            // Configure request
            const API_BASE_URL = import.meta.env.PROD 
              ? "https://billingonaire-backend-819125105651.asia-south1.run.app"
              : "/api";
            xhr.open('POST', `${API_BASE_URL}/upload-pdf`, true);
            xhr.setRequestHeader('Authorization', `Bearer ${idToken}`);
            
            // Send the file
            xhr.send(formData);
          });
          
          const result = await uploadPromise;
          const fileResult = result.results?.[0] || result || {};
          setFileResults((prev) => ({ 
            ...prev, 
            [file.name]: {
              ...fileResult,
              success: true
            }
          }));
          
        } catch (e) {
          console.error(`Error uploading ${file.name}:`, e);
          setFileResults((prev) => ({ 
            ...prev, 
            [file.name]: { 
              error: e.message,
              success: false
            }
          }));
        }
      }
      
      setSuccessMessage('Upload process completed!');
    } catch (e) {
      setError(`Upload failed: ${e.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Helper to get icon for file type (PDF only for now)
  const getFileIcon = () => (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#d32f2f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginRight: '0.5rem', minWidth: 32}}>
      <rect x="3" y="3" width="18" height="18" rx="2" fill="#fff" stroke="#d32f2f"/>
      <text x="7" y="19" fontSize="10" fill="#d32f2f" fontWeight="bold">PDF</text>
    </svg>
  );

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Upload Board Files</h1>
        <p className="dashboard-subtitle">
          Upload daily board PDF files to extract case information and AGP assignments
        </p>
      </div>
      
      <div className="dashboard-section">
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">📄 PDF File Upload</h2>
          </div>
          <div className="card-body">
            {user ? (
              <>
                <form onSubmit={uploadFile}>
                  <div className="form-group">
                    <label className="form-label" htmlFor="file">
                      Choose PDF File(s)
                    </label>
                    <input
                      id="file"
                      type="file"
                      className="form-control"
                      accept="application/pdf"
                      ref={fileInput}
                      multiple
                      required
                      onChange={handleFileChange}
                      disabled={isUploading}
                    />
                    <small style={{ color: 'var(--gray-500)', fontSize: '0.875rem', marginTop: '0.25rem', display: 'block' }}>
                      Select one or more PDF files containing daily board information
                    </small>
                  </div>
                  {selectedFiles.length > 0 && (
                    <div style={{ margin: 'var(--spacing-lg) 0' }}>
                      <p style={{ fontWeight: '500', marginBottom: 'var(--spacing-sm)', color: 'var(--gray-700)' }}>
                        Selected file{selectedFiles.length > 1 ? 's' : ''}:
                      </p>
                      <div style={{ backgroundColor: 'var(--gray-50)', padding: 'var(--spacing-md)', borderRadius: 'var(--radius-md)', border: '1px solid var(--gray-200)' }}>
                        {selectedFiles.map((file) => (
                          <div key={file.name} style={{ display: 'flex', alignItems: 'center', marginBottom: 'var(--spacing-sm)' }}>
                            {getFileIcon()}
                            <span style={{ color: 'var(--gray-700)', fontSize: '0.875rem' }}>{file.name}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {error && (
                    <div className="alert-error">
                      <strong>Error:</strong> {error}
                    </div>
                  )}
                  
                  <button 
                    type="submit" 
                    className="btn-professional btn-primary"
                    disabled={isUploading || selectedFiles.length === 0}
                    style={{ width: '100%', marginBottom: 'var(--spacing-lg)' }}
                  >
                    {isUploading ? (
                      <span className="loading-text">
                        <span className="loading"></span>
                        Processing files...
                      </span>
                    ) : (
                      `Upload ${selectedFiles.length > 0 ? selectedFiles.length : ''} File${selectedFiles.length !== 1 ? 's' : ''}`
                    )}
                  </button>
                </form>
                {(isUploading || Object.keys(progress).length > 0) && (
                  <div>
                    <h3 style={{ fontSize: '1.25rem', fontWeight: '600', marginBottom: 'var(--spacing-lg)', color: 'var(--gray-900)' }}>
                      📊 Upload Progress
                    </h3>
                    {selectedFiles.map((file) => {
                      const percent = progress[file.name] || 0;
                      const result = fileResults[file.name] || {};
                      
                      let statusText = '';
                      let statusColor = 'var(--gray-600)';
                      
                      if (result.error) {
                        statusText = `Error: ${result.error}`;
                        statusColor = '#dc2626';
                      } else if (result.success && typeof result.records_processed === 'number') {
                        statusText = `✅ ${result.records_processed} record${result.records_processed !== 1 ? 's' : ''} processed`;
                        statusColor = 'var(--secondary-color)';
                      } else if (percent === 100) {
                        statusText = '✅ Upload complete';
                        statusColor = 'var(--secondary-color)';
                      } else if (percent > 0) {
                        statusText = `${percent}% uploaded`;
                        statusColor = 'var(--primary-color)';
                      } else {
                        statusText = 'Waiting...';
                      }
                      
                      return (
                        <div key={file.name} style={{ marginBottom: 'var(--spacing-lg)', padding: 'var(--spacing-md)', backgroundColor: 'var(--gray-50)', borderRadius: 'var(--radius-md)', border: '1px solid var(--gray-200)' }}>
                          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 'var(--spacing-sm)' }}>
                            {getFileIcon()}
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontWeight: '500', color: 'var(--gray-900)', fontSize: '0.875rem' }}>
                                  {file.name}
                                </span>
                                <span style={{ color: statusColor, fontWeight: '500', fontSize: '0.875rem' }}>
                                  {statusText}
                                </span>
                              </div>
                              <div style={{ 
                                width: '100%', 
                                height: '8px', 
                                backgroundColor: 'var(--gray-200)', 
                                borderRadius: '4px',
                                marginTop: 'var(--spacing-sm)',
                                overflow: 'hidden'
                              }}>
                                <div style={{
                                  width: `${percent}%`,
                                  height: '100%',
                                  backgroundColor: result.error ? '#dc2626' : 'var(--primary-color)',
                                  borderRadius: '4px',
                                  transition: 'width 0.3s ease'
                                }} />
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                
                {successMessage && (
                  <div className="alert-success">
                    <strong>Success:</strong> {successMessage}
                  </div>
                )}
              </>
            ) : (
              <div className="alert-error">
                <strong>Authentication Required:</strong> Please log in to upload files.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Upload;
