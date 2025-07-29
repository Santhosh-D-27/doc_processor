import React, { useState, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';

const API_URL = 'http://127.0.0.1:8000';

const UploadPanel = () => {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const inputRef = useRef(null); // Ref for the hidden file input

  const showMessage = (text, type) => {
    setMessage(text);
    setMessageType(type);
    setTimeout(() => {
      setMessage('');
      setMessageType('');
    }, 5000);
  };

  const handleFiles = useCallback(async (files) => {
    if (!files || files.length === 0) return;

    const formData = new FormData();
    Array.from(files).forEach(file => {
      formData.append('files', file);
    });

    try {
      setUploading(true);
      setUploadProgress(0);

      const response = await axios.post(`${API_URL}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(percentCompleted);
        },
      });

      showMessage(
        `Successfully uploaded ${files.length} file(s)`,
        'success'
      );
    } catch (error) {
      console.error('Upload failed:', error);
      showMessage(
        error.response?.data?.detail || 'Upload failed. Please try again.',
        'error'
      );
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  }, []);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files);
    }
  }, [handleFiles]);

  const onButtonClick = () => {
    inputRef.current?.click(); // Programmatically click the hidden file input
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files);
    }
    // Clear the input value so the same file can be selected again
    e.target.value = null; 
  };

  return (
    <motion.div
      className={`flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-lg
        ${dragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-gray-50'}
        ${uploading ? 'pointer-events-none opacity-70' : ''}
        transition-all duration-200 ease-in-out`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      layout
    >
      <input
        type="file"
        id="file-upload-input"
        multiple
        onChange={handleChange}
        ref={inputRef}
        className="hidden" // Hide the input visually
      />

      {uploading ? (
        <div className="flex flex-col items-center">
          <p className="text-lg font-semibold text-blue-600">Uploading...</p>
          <div className="w-full bg-gray-200 rounded-full h-2.5 mt-2">
            <div
              className="bg-blue-600 h-2.5 rounded-full"
              style={{ width: `${uploadProgress}%` }}
            ></div>
          </div>
          <p className="mt-1 text-sm text-gray-600">{uploadProgress}%</p>
        </div>
      ) : (
        <>
          <svg
            className="w-16 h-16 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v8"
            ></path>
          </svg>
          <p className="mt-4 text-lg text-gray-600 text-center">
            Drag & drop files here, or
            <button
              className="ml-1 text-blue-600 hover:text-blue-800 font-semibold focus:outline-none"
              onClick={onButtonClick}
            >
              browse
            </button>
          </p>
          <p className="text-sm text-gray-500 mt-1">
            (e.g., images, documents, videos)
          </p>
        </>
      )}

      <AnimatePresence>
        {message && (
          <motion.p
            className={`mt-4 p-2 rounded-md text-sm font-medium ${
              messageType === 'success'
                ? 'bg-green-100 text-green-700'
                : 'bg-red-100 text-red-700'
            }`}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            {message}
          </motion.p>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

export default UploadPanel;