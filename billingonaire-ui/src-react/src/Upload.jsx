import React, { useRef, useState } from 'react';
// import { useNavigate } from 'react-router-dom'; // Uncomment if using React Router
// import { auth } from '../lib/firebase'; // Adjust import if you migrate firebase logic
// import { onAuthStateChanged } from 'firebase/auth'; // Uncomment if using Firebase Auth
import { API_BASE_URL } from './config';

const Upload = () => {
  // const navigate = useNavigate(); // Uncomment if using React Router
  const fileInput = useRef();
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState({}); // Track progress per file
  const [fileResults, setFileResults] = useState({}); // Store backend response per file
  const [successMessage, setSuccessMessage] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]); // Track selected files

  // useEffect(() => {
  //   onAuthStateChanged(auth, (user) => {
  //     if (!user) {
  //       navigate('/login');
  //     }
  //   });
  // }, [navigate]);

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

  return (
    <div className="upload-container">
      <h1>Upload PDF</h1>
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
          />
        </div>
        {/* Show selected file names */}
        {selectedFiles.length > 0 && (
          <div style={{ marginBottom: '1rem' }}>
            <strong>Selected file{selectedFiles.length > 1 ? 's' : ''}:</strong>
            <ul>
              {selectedFiles.map((file) => (
                <li key={file.name}>{file.name}</li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={isUploading}>
          Upload
        </button>
      </form>
      {/* Show currently uploading file names */}
      {isUploading && selectedFiles.length > 0 && (
        <div style={{ margin: '1rem 0', color: '#007bff' }}>
          <strong>Uploading and processing:</strong>
          <ul>
            {selectedFiles.map((file) => (
              <li key={file.name}>{file.name}</li>
            ))}
          </ul>
        </div>
      )}
      {successMessage && <p className="success">{successMessage}</p>}
      {/* Progress and results UI unchanged */}
      {Object.keys(progress).length > 0 && (
        <div>
          <h4>Upload Progress</h4>
          {Object.entries(progress).map(([name, percent]) => (
            <div key={name} style={{ marginBottom: '0.5rem' }}>
              <span>{name}: {percent}%</span>
              <progress value={percent} max="100" style={{ width: '100%' }} />
              {fileResults[name] && (
                <div style={{ marginTop: '0.25rem', color: fileResults[name].error ? 'red' : 'green' }}>
                  {fileResults[name].error
                    ? `Error: ${fileResults[name].error}`
                    : fileResults[name].message
                      ? fileResults[name].message
                      : 'Processed successfully'}
                </div>
              )}
            </div>
          ))}
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
        h4 {
          margin-top: 1.5rem;
        }
      `}</style>
    </div>
  );
};

export default Upload;
