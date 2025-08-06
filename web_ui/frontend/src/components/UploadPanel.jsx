import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';

const INGESTOR_API_URL = 'http://127.0.0.1:8001';

const UploadPanel = () => {
  const [uploadStatus, setUploadStatus] = useState('');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [senderEmail] = useState('manual_upload@example.com');

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    
    const file = acceptedFiles[0];
    setIsUploading(true);
    setUploadProgress(0);
    setUploadStatus(`Uploading ${file.name}...`);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('sender', senderEmail);
      
      const response = await axios.post(`${INGESTOR_API_URL}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
        onUploadProgress: (progressEvent) => {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setUploadProgress(progress);
        }
      });
      
      setUploadStatus(`✅ Success: ${response.data.filename} uploaded successfully!`);
      setUploadProgress(100);
      
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message || 'Unknown error';
      setUploadStatus(`❌ Error: ${errorMessage}`);
      setUploadProgress(0);
    } finally {
      setIsUploading(false);
      setTimeout(() => {
        setUploadStatus('');
        setUploadProgress(0);
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
    <motion.div 
      className="glass-card-strong rounded-2xl shadow-modern-lg p-6 sm:p-8"
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      {/* Header */}
      <motion.div 
        className="text-center mb-6"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.2 }}
      >
        <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 mb-2">
          Upload Document
        </h2>
        <p className="text-slate-400 text-sm">
          Process documents instantly with our AI-powered pipeline
        </p>
      </motion.div>

      {/* Upload Zone */}
      <motion.div 
        {...getRootProps()} 
        className={`upload-zone p-8 sm:p-12 text-center cursor-pointer transition-all duration-300 ${
          isDragActive ? 'drag-active' : ''
        } ${isUploading ? 'pointer-events-none opacity-75' : ''}`}
        whileHover={!isUploading ? { scale: 1.01, y: -2 } : {}}
        whileTap={!isUploading ? { scale: 0.99 } : {}}
      >
        <input {...getInputProps()} />
        
        <motion.div 
          className="space-y-6"
          animate={isDragActive ? { scale: 1.05 } : { scale: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
        >
          {/* Upload Icon */}
          <motion.div 
            className="mx-auto w-20 h-20 rounded-full glass-card flex items-center justify-center mb-4"
            animate={isUploading ? { 
              rotate: 360,
              scale: [1, 1.1, 1]
            } : isDragActive ? {
              scale: [1, 1.1, 1],
              rotate: [0, 5, -5, 0]
            } : {}}
            transition={isUploading ? { 
              rotate: { duration: 2, repeat: Infinity, ease: "linear" },
              scale: { duration: 1, repeat: Infinity, ease: "easeInOut" }
            } : isDragActive ? {
              duration: 0.6,
              repeat: Infinity,
              ease: "easeInOut"
            } : {}}
          >
            <span className="text-4xl">
              {isUploading ? '⏳' : isDragActive ? '📥' : '📁'}
            </span>
          </motion.div>

          {/* Upload Text */}
          <div>
            <AnimatePresence mode="wait">
              {isDragActive ? (
                <motion.div
                  key="dragging"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                >
                  <p className="text-xl font-semibold text-cyan-300 mb-2">
                    Drop it like it's hot! 🔥
                  </p>
                  <p className="text-slate-400">Release to upload your document</p>
                </motion.div>
              ) : isUploading ? (
                <motion.div
                  key="uploading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <p className="text-xl font-semibold text-blue-300 mb-2">
                    Processing your document...
                  </p>
                  <p className="text-slate-400">Please wait while we upload</p>
                </motion.div>
              ) : (
                <motion.div
                  key="default"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                >
                  <p className="text-xl font-semibold text-slate-200 mb-2">
                    Drag & drop your document here
                  </p>
                  <p className="text-slate-400 mb-4">
                    or <span className="text-cyan-400 font-semibold">click to browse</span>
                  </p>
                  <div className="flex justify-center items-center gap-2 text-xs text-slate-500">
                    <span>Max size: 10MB</span>
                    <span>•</span>
                    <span>PDF, DOCX, Images, Text</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Progress Bar */}
          <AnimatePresence>
            {isUploading && (
              <motion.div
                className="w-full max-w-md mx-auto"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.3 }}
              >
                <div className="progress-container mb-2 bg-gray-700/50 rounded-full h-2 overflow-hidden">
                  <motion.div 
                    className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${uploadProgress}%` }}
                    transition={{ duration: 0.3, ease: "easeOut" }}
                  />
                </div>
                <p className="text-sm text-slate-400 font-mono">
                  {uploadProgress}% uploaded
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </motion.div>

      {/* Status Message */}
      <AnimatePresence>
        {uploadStatus && (
          <motion.div 
            className={`mt-6 p-4 rounded-xl border backdrop-blur-sm ${
              uploadStatus.includes('✅') 
                ? 'bg-green-500/10 border-green-500/30 text-green-300' 
                : uploadStatus.includes('❌')
                ? 'bg-red-500/10 border-red-500/30 text-red-300'
                : 'bg-blue-500/10 border-blue-500/30 text-blue-300'
            }`}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          >
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium flex-1 mr-4 break-words">
                {uploadStatus}
              </p>
              <motion.button
                onClick={() => setUploadStatus('')}
                className="text-slate-400 hover:text-slate-200 transition-colors flex-shrink-0 p-1 hover:bg-white/10 rounded-full"
                whileHover={{ scale: 1.1, rotate: 90 }}
                whileTap={{ scale: 0.9 }}
              >
                ✕
              </motion.button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

export default UploadPanel;