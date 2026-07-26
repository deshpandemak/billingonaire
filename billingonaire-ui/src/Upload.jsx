import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged } from 'firebase/auth';
import './styles/professional.css';

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
  const [isDragging, setIsDragging] = useState(false);

  React.useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (u) => setUser(u));
    return () => unsubscribe();
  }, []);

  const applyFiles = (fileList) => {
    const pdfs = Array.from(fileList).filter(
      (f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    );
    if (!pdfs.length) {
      setError('Only PDF files are accepted.');
      return;
    }
    setError('');
    setSelectedFiles(pdfs);
  };

  const handleFileChange = (e) => applyFiles(e.target.files);

  const handleDragEnter = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); };
  const handleDragOver  = (e) => { e.preventDefault(); e.stopPropagation(); };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    applyFiles(e.dataTransfer.files);
  };

  const uploadFile = async (e) => {
    e.preventDefault();
    setIsUploading(true);
    setError('');
    setProgress({});
    setFileResults({});
    setSuccessMessage('');

    if (!selectedFiles.length) {
      setError('Please select at least one file.');
      setIsUploading(false);
      return;
    }

    try {
      for (const file of selectedFiles) {
        try {
          const formData = new FormData();
          formData.append('files', file);

          const currentUser = auth.currentUser;
          if (!currentUser) throw new Error('User not authenticated');
          const idToken = await currentUser.getIdToken(true);

          const uploadPromise = new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            xhr.upload.onprogress = (event) => {
              if (event.lengthComputable) {
                const percent = Math.round((event.loaded / event.total) * 100);
                setProgress((prev) => ({ ...prev, [file.name]: percent }));
              }
            };

            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                resolve(JSON.parse(xhr.responseText));
              } else {
                reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`));
              }
            };

            xhr.onerror = () => reject(new Error('Network error during upload'));

            const API_BASE_URL =
              import.meta.env.VITE_API_URL ||
              (import.meta.env.PROD
                ? 'https://billingonaire-backend-819125105651.asia-south1.run.app'
                : '/api');
            xhr.open('POST', `${API_BASE_URL}/upload-pdf`, true);
            xhr.setRequestHeader('Authorization', `Bearer ${idToken}`);
            xhr.send(formData);
          });

          const result = await uploadPromise;
          const fileResult = result.results?.[0] || result || {};
          setFileResults((prev) => ({
            ...prev,
            [file.name]: { ...fileResult, success: fileResult.error == null },
          }));
        } catch (err) {
          console.error(`Error uploading ${file.name}:`, err);
          setFileResults((prev) => ({
            ...prev,
            [file.name]: { error: err.message, success: false },
          }));
        }
      }

      setSuccessMessage('Upload process completed!');
    } catch (err) {
      setError(`Upload failed: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const getFileIcon = () => (
    <svg
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="#d32f2f"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ marginRight: '0.5rem', minWidth: 28, flexShrink: 0 }}
    >
      <rect x="3" y="3" width="18" height="18" rx="2" fill="#fff" stroke="#d32f2f" />
      <text x="7" y="19" fontSize="10" fill="#d32f2f" fontWeight="bold">PDF</text>
    </svg>
  );

  const removeFile = (name) => {
    setSelectedFiles((prev) => prev.filter((f) => f.name !== name));
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Upload Board Files</h1>
        <p className="dashboard-subtitle">
          Upload daily board PDF files to extract case information and AGP (Assistant Government Pleader) assignments
        </p>
      </div>

      <div className="dashboard-section">
        <div className="card-professional" style={{ maxWidth: 680, margin: '0 auto' }}>
          <div className="card-header">
            <h2 className="section-title">PDF File Upload</h2>
          </div>
          <div className="card-body">
            {user ? (
              <form onSubmit={uploadFile}>
                {/* ── Drop zone ── */}
                <div
                  onDragEnter={handleDragEnter}
                  onDragLeave={handleDragLeave}
                  onDragOver={handleDragOver}
                  onDrop={handleDrop}
                  onClick={() => !isUploading && fileInput.current.click()}
                  style={{
                    border: `2px dashed ${isDragging ? 'var(--primary-color)' : 'var(--gray-300)'}`,
                    borderRadius: 'var(--radius-lg)',
                    padding: '2.5rem 1.5rem',
                    textAlign: 'center',
                    cursor: isUploading ? 'default' : 'pointer',
                    background: isDragging
                      ? 'rgba(59,130,246,0.04)'
                      : 'var(--gray-50)',
                    transition: 'border-color 0.2s ease, background 0.2s ease',
                    marginBottom: 'var(--spacing-lg)',
                  }}
                >
                  <svg
                    width="44"
                    height="44"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke={isDragging ? 'var(--primary-color)' : 'var(--gray-400)'}
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ display: 'block', margin: '0 auto 0.75rem' }}
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  <p
                    style={{
                      fontWeight: 600,
                      color: isDragging ? 'var(--primary-color)' : 'var(--gray-700)',
                      marginBottom: '0.25rem',
                    }}
                  >
                    {isDragging ? 'Drop files here' : 'Drag & drop PDF files here'}
                  </p>
                  <p style={{ fontSize: '0.875rem', color: 'var(--gray-500)', marginBottom: 0 }}>
                    or click to browse
                  </p>
                  <input
                    id="file"
                    type="file"
                    accept="application/pdf"
                    ref={fileInput}
                    multiple
                    style={{ display: 'none' }}
                    onChange={handleFileChange}
                    disabled={isUploading}
                  />
                </div>

                {/* ── Selected files list ── */}
                {selectedFiles.length > 0 && (
                  <div style={{ marginBottom: 'var(--spacing-lg)' }}>
                    <p
                      style={{
                        fontWeight: 500,
                        marginBottom: 'var(--spacing-sm)',
                        color: 'var(--gray-700)',
                        fontSize: '0.875rem',
                      }}
                    >
                      {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
                    </p>
                    <div
                      style={{
                        backgroundColor: 'var(--gray-50)',
                        padding: 'var(--spacing-md)',
                        borderRadius: 'var(--radius-md)',
                        border: '1px solid var(--gray-200)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.5rem',
                      }}
                    >
                      {selectedFiles.map((file) => (
                        <div
                          key={file.name}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
                            {getFileIcon()}
                            <span
                              style={{
                                color: 'var(--gray-700)',
                                fontSize: '0.875rem',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {file.name}
                            </span>
                          </div>
                          {!isUploading && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); removeFile(file.name); }}
                              style={{
                                background: 'none',
                                border: 'none',
                                cursor: 'pointer',
                                color: 'var(--gray-400)',
                                fontSize: '1rem',
                                padding: '0 0.25rem',
                                lineHeight: 1,
                                flexShrink: 0,
                              }}
                              title="Remove file"
                            >
                              ✕
                            </button>
                          )}
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
                      <span className="loading" />
                      Processing files…
                    </span>
                  ) : (
                    `Upload ${selectedFiles.length > 0 ? selectedFiles.length : ''} File${selectedFiles.length !== 1 ? 's' : ''}`
                  )}
                </button>

                {/* ── Per-file upload progress ── */}
                {(isUploading || Object.keys(progress).length > 0) && (
                  <div style={{ marginBottom: 'var(--spacing-lg)' }}>
                    <h3
                      style={{
                        fontSize: '1rem',
                        fontWeight: 600,
                        marginBottom: 'var(--spacing-md)',
                        color: 'var(--gray-900)',
                      }}
                    >
                      Upload Progress
                    </h3>
                    {selectedFiles.map((file) => {
                      const percent = progress[file.name] || 0;
                      const result = fileResults[file.name] || {};
                      let statusText = '';
                      let statusColor = 'var(--gray-600)';

                      if (result.error) {
                        statusText = `Error: ${result.error}`;
                        statusColor = '#dc2626';
                      } else if (
                        result.success &&
                        typeof result.records_processed === 'number'
                      ) {
                        const boardDateStr = result.board_date
                          ? ` · Board date: ${result.board_date}`
                          : '';
                        statusText = `${result.records_processed} case${result.records_processed !== 1 ? 's' : ''} imported${boardDateStr}`;
                        statusColor = 'var(--secondary-color)';
                      } else if (percent === 100) {
                        statusText = 'Upload complete';
                        statusColor = 'var(--secondary-color)';
                      } else if (percent > 0) {
                        statusText = `${percent}%`;
                        statusColor = 'var(--primary-color)';
                      } else {
                        statusText = 'Waiting…';
                      }

                      return (
                        <div
                          key={file.name}
                          style={{
                            marginBottom: 'var(--spacing-md)',
                            padding: 'var(--spacing-md)',
                            backgroundColor: 'var(--gray-50)',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--gray-200)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center' }}>
                            {getFileIcon()}
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div
                                style={{
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center',
                                  marginBottom: '0.375rem',
                                }}
                              >
                                <span
                                  style={{
                                    fontWeight: 500,
                                    color: 'var(--gray-900)',
                                    fontSize: '0.875rem',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                    maxWidth: '60%',
                                  }}
                                >
                                  {file.name}
                                </span>
                                <span
                                  style={{
                                    color: statusColor,
                                    fontWeight: 500,
                                    fontSize: '0.8rem',
                                    flexShrink: 0,
                                    marginLeft: '0.5rem',
                                  }}
                                >
                                  {statusText}
                                </span>
                              </div>
                              <div
                                style={{
                                  width: '100%',
                                  height: 6,
                                  backgroundColor: 'var(--gray-200)',
                                  borderRadius: 3,
                                  overflow: 'hidden',
                                }}
                              >
                                <div
                                  style={{
                                    width: `${percent}%`,
                                    height: '100%',
                                    backgroundColor: result.error
                                      ? '#dc2626'
                                      : 'var(--primary-color)',
                                    borderRadius: 3,
                                    transition: 'width 0.3s ease',
                                  }}
                                />
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* ── Success summary ── */}
                {successMessage && Object.keys(fileResults).length > 0 && (
                  <div className="alert-success">
                    <strong>Upload complete.</strong>
                    {Object.entries(fileResults).map(([name, result]) =>
                      result.success && typeof result.records_processed === 'number' ? (
                        <div key={name} style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>
                          <strong>{name}</strong>
                          {result.board_date && (
                            <span style={{ marginLeft: '0.5rem', color: 'var(--gray-700)' }}>
                              Board date: <strong>{result.board_date}</strong>
                            </span>
                          )}
                          <span style={{ marginLeft: '0.5rem' }}>
                            {result.records_processed} case
                            {result.records_processed !== 1 ? 's' : ''} imported. Order
                            processing started in background.
                          </span>
                        </div>
                      ) : null
                    )}
                    <div style={{ marginTop: '0.75rem' }}>
                      <button
                        type="button"
                        className="btn-professional btn-primary"
                        style={{ fontSize: '0.875rem', padding: '0.4rem 1rem' }}
                        onClick={() => navigate('/dashboard')}
                      >
                        View on Dashboard →
                      </button>
                    </div>
                  </div>
                )}
              </form>
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
