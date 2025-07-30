import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

const INGESTOR_API_URL = 'http://127.0.0.1:8001';

const UploadPanel = () => {
  const [uploadStatus, setUploadStatus] = useState('');
  const [senderEmail] = useState('manual_upload@example.com'); 

  const onDrop = useCallback(async (acceptedFiles) => {
    try {
      if (acceptedFiles.length === 0) {
        return;
      }
      
      const file = acceptedFiles[0];
      
      setUploadStatus(`Uploading ${file.name}...`);
      
      const formData = new FormData();
      formData.append('file', file);
      formData.append('sender', senderEmail);
      
      const response = await axios.post(`${INGESTOR_API_URL}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 30000,
      });
      
      setUploadStatus(`✅ Success: ${response.data.filename}`);
      
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message || 'Unknown error';
      setUploadStatus(`❌ Error: ${errorMessage}`);
    } finally {
      setTimeout(() => {
        setUploadStatus('');
      }, 5000);
    }
  }, [senderEmail]);

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
    <div className="bg-gray-800 rounded-xl shadow-lg border border-gray-700 p-6">
      <h2 className="text-2xl font-bold text-gray-100 mb-6">Upload Document</h2>
      
      <div 
        {...getRootProps()} 
        className="p-10 border-2 border-dashed rounded-xl text-center cursor-pointer transition-colors duration-300 border-gray-600 hover:border-gray-400"
        style={{
          borderColor: isDragActive ? '#14b8a6' : '#4b5563',
          backgroundColor: isDragActive ? 'rgba(6, 95, 70, 0.5)' : 'transparent'
        }}
      >
        <input {...getInputProps()} />
        
        <div className="space-y-2">
          <div className="text-4xl mb-4">📁</div>
          {isDragActive ? (
            <p className="text-lg text-teal-300">Drop the file here...</p>
          ) : (
            <div>
              <p className="text-lg mb-2">Drop a document here, or click to select</p>
              <p className="text-sm text-gray-400">Supports: PDF, DOCX, TXT, JPG, PNG</p>
            </div>
          )}
        </div>
      </div>
      
      {uploadStatus && (
        <div className="mt-4 p-3 bg-gray-700 rounded-lg">
          <p className="text-sm text-white">{uploadStatus}</p>
        </div>
      )}
    </div>
  );
};

export default UploadPanel;
