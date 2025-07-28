// In web_ui/frontend/src/components/UploadPanel.jsx

import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

const INGESTOR_API_URL = 'http://127.0.0.1:8001';

const UploadPanel = () => {
  const [uploadStatus, setUploadStatus] = useState('');

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    
    setUploadStatus(`Uploading ${file.name}...`);
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(`${INGESTOR_API_URL}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setUploadStatus(`Successfully uploaded ${response.data.filename}!`);
    } catch (error) {
      console.error('Upload failed:', error);
      setUploadStatus(`Upload failed for ${file.name}. Is the Ingestor agent running?`);
    }
    setTimeout(() => setUploadStatus(''), 5000);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ 
    onDrop,
    multiple: false,
    accept: {
      'image/jpeg': [], 'image/png': [],
      'application/pdf': [], 'text/plain': [],
    }
  });

  return (
    <div 
      {...getRootProps()} 
      className={`p-10 border-2 border-dashed rounded-xl text-center cursor-pointer transition-colors duration-300
        ${isDragActive ? 'border-teal-400 bg-teal-900/50' : 'border-gray-600 hover:border-gray-400'}`}
    >
      <input {...getInputProps()} />
      {isDragActive ?
          <p>Drop the file here ...</p> :
          <p>Drag 'n' drop a document here, or click to select a file</p>
      }
      {uploadStatus && <p className="mt-4 text-sm text-gray-400">{uploadStatus}</p>}
    </div>
  );
};

export default UploadPanel;