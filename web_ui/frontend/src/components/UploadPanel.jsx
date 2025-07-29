// In web_ui/frontend/src/components/UploadPanel.jsx

import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

const INGESTOR_API_URL = 'http://127.0.0.1:8001';

const UploadPanel = () => {
  const [uploadStatus, setUploadStatus] = useState('');
  // NEW: State for sender, with a default value
  const [senderEmail, setSenderEmail] = useState('manual_upload@example.com'); 

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    
    setUploadStatus(`Uploading ${file.name}...`);
    
    const formData = new FormData();
    formData.append('file', file);
    // NEW: Append the sender field
    formData.append('sender', senderEmail); 

    try {
      const response = await axios.post(`${INGESTOR_API_URL}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      setUploadStatus(`Successfully uploaded ${response.data.filename}! (ID: ${response.data.document_id})`);
    } catch (error) {
      console.error('Upload failed:', error);
      // Access error.response.data for more details from FastAPI
      const errorMessage = error.response?.data?.detail || `Upload failed for ${file.name}. Is the Ingestor agent running?`;
      setUploadStatus(errorMessage);
    }

    // Clear the status message after 5 seconds
    setTimeout(() => setUploadStatus(''), 5000);
  }, [senderEmail]); // Add senderEmail to useCallback dependencies

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ 
    onDrop,
    multiple: false,
    accept: {
      'image/jpeg': [],
      'image/png': [],
      'application/pdf': [],
      'text/plain': [],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    }
  });

  return (
    <div className="p-10 border-2 border-dashed rounded-xl text-center cursor-pointer transition-colors duration-300
        ${isDragActive ? 'border-teal-400 bg-teal-900/50' : 'border-gray-600 hover:border-gray-400'}">
      <input {...getInputProps()} />
      {/* NEW: Add an input for sender email */}
      <div className="mb-4">
        <label htmlFor="senderEmail" className="block text-sm font-medium text-gray-300 mb-1">Sender Email (for testing VIP)</label>
        <input
          id="senderEmail"
          type="email"
          value={senderEmail}
          onChange={(e) => setSenderEmail(e.target.value)}
          className="w-full max-w-sm mx-auto px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white focus:ring-teal-500 focus:border-teal-500"
          placeholder="e.g., ceo@yourcompany.com"
          onClick={(e) => e.stopPropagation()} // Prevent dropzone from activating when clicking input
        />
      </div>

      {
        isDragActive ?
          <p>Drop the file here ...</p> :
          <p>Drag 'n' drop a document here, or click to select a file</p>
      }
      {uploadStatus && <p className="mt-4 text-sm text-gray-400">{uploadStatus}</p>}
    </div>
  );
};

export default UploadPanel;