import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import Header from './components/Header';
import UploadPanel from './components/UploadPanel';
import DocumentTable from './components/DocumentTable';

const API_URL = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';
const OAUTH_MANAGER_URL = 'http://127.0.0.1:8001';

const Dashboard = () => {
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState(null);
  const [activeTab, setActiveTab] = useState('documents');
  const [wsConnected, setWsConnected] = useState(false);
  const [oauthStatus, setOauthStatus] = useState({    
    connected_count: 0,
    mailboxes: [],
    ingestor_service_status: 'disconnected'
  });

  const handleRowClick = useCallback(async (docId) => {
    try {
      if (expandedRow && expandedRow.id === docId) {
        setExpandedRow(null);
      } else {
        const response = await axios.get(`${API_URL}/history/${docId}`);
        if (response.data && Array.isArray(response.data)) {
          setExpandedRow({ id: docId, history: response.data });
        } else {
          setExpandedRow({ id: docId, history: [] });
        }
      }
    } catch (err) {
      setExpandedRow({ id: docId, history: [] });
      if (err.response && err.response.status !== 404 && err.code !== 'ERR_NETWORK' && !err.message.includes('Network Error')) {
        setError("Could not load document details.");
      }
    }
  }, [expandedRow]);

  const handleManualAction = useCallback(async (action, docId, e, destination = null) => {
    e.stopPropagation();
    try {
      let response;
      if (action === 're-classify') {
        response = await axios.post(`${API_URL}/re-classify/${docId}`, {
          manual_type_hint: null,
          confidence_threshold: 0.75,
          force_classification: false,
          reason: 'Manual re-classification request'
        });
      } else if (action === 're-extract') {
        response = await axios.post(`${API_URL}/re-extract/${docId}`, {
          ocr_engine: 'default',
          dpi: 300,
          language: 'eng',
          manual_text: null,
          preprocessing: null,
          reason: 'Manual re-extraction request'
        });
      } else if (action === 're-route') {
        response = await axios.post(`${API_URL}/re-route/${docId}`, { destination: destination });
      } else {
        response = await axios.post(`${API_URL}/${action}/${docId}`);
      }
      
      setDocuments(docs => docs.map(d => 
        d.document_id === docId ? { 
          ...d, 
          status: `Re-${action}...`,
          override_in_progress: true,
          override_type: action
        } : d
      ));
      setError(null);
    } catch (err) {
      if (err.response?.status === 404) {
        if (action === 're-classify') {
          setError("No extraction data found. Please re-extract the document first.");
        } else if (action === 're-extract') {
          setError("No original file content found. Cannot re-extract.");
        } else {
          setError("Document not found or no data available for this action.");
        }
      } else if (err.response?.status === 500) {
        setError(`Server error during ${action}. Please try again.`);
      } else if (err.code === 'ERR_NETWORK') {
        setError("Network error. Please check your connection.");
      } else {
        setError(`Failed to start re-${action} process: ${err.response?.data?.detail || err.message}`);
      }
    }
  }, []);

  const fetchOAuthStatus = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/oauth-status`);
      setOauthStatus(response.data || {
        connected_count: 0,
        mailboxes: [],
        ingestor_service_status: 'disconnected'
      });
    } catch (err) {
      setOauthStatus({
        connected_count: 0,
        mailboxes: [],
        ingestor_service_status: 'error'
      });
    }
  }, []);

  const handleOAuthAction = useCallback(() => {
    window.open(OAUTH_MANAGER_URL, '_blank', 'width=800,height=600');
    const checkInterval = setInterval(() => {
      fetchOAuthStatus();
    }, 2000);
    setTimeout(() => {
      clearInterval(checkInterval);
    }, 120000);
  }, [fetchOAuthStatus]);

  useEffect(() => {
    const fetchInitialDocuments = async () => {
      try {
        setLoading(true);
        const response = await axios.get(`${API_URL}/documents`);
        const docs = response.data || [];
        setDocuments(Array.isArray(docs) ? docs : []);
        setError(null);
      } catch (err) {
        if (err.code === 'ERR_NETWORK' || err.message.includes('Network Error')) {
          setError("Backend service is not available. Please ensure the web_ui service is running on port 8000.");
        } else {
          setError("Could not connect to the backend.");
        }
        setDocuments([]);
      } finally {
        setLoading(false);
      }
    };

    fetchInitialDocuments();
    fetchOAuthStatus();

    let ws;
    let reconnectInterval;

    const connectWebSocket = () => {
      try {
        ws = new WebSocket(WS_URL);
        
        ws.onopen = () => {
          setWsConnected(true);
          setError(null);
          if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
          }
        };

        ws.onclose = () => {
          setWsConnected(false);
          if (!reconnectInterval) {
            reconnectInterval = setInterval(() => {
              connectWebSocket();
            }, 5000);
          }
        };

        ws.onerror = (error) => {
          setWsConnected(false);
          setError("WebSocket connection error.");
        };

        ws.onmessage = (event) => {
          try {
            const newStatusEvent = JSON.parse(event.data);
            let isNewDocument = false;
            setDocuments(prevDocs => {
              const docIndex = prevDocs.findIndex(doc => doc.document_id === newStatusEvent.document_id);
              let newDocs;
              if (docIndex > -1) {
                newDocs = [...prevDocs];
                const updatedDoc = { 
                  ...newDocs[docIndex], 
                  ...newStatusEvent,
                  override_in_progress: false,
                  override_type: null
                };
                newDocs[docIndex] = updatedDoc;
              } else {
                isNewDocument = true;
                newDocs = [newStatusEvent, ...prevDocs];
              }
              return newDocs.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));
            });

            setExpandedRow(prevExpanded => {
              if (isNewDocument) {
                return { id: newStatusEvent.document_id, history: [newStatusEvent] };
              }
              if (prevExpanded && prevExpanded.id === newStatusEvent.document_id) {
                const updatedHistory = [...prevExpanded.history, newStatusEvent];
                return { ...prevExpanded, history: updatedHistory };
              }
              return prevExpanded;
            });
          } catch (err) {
            console.error("Error parsing WebSocket message:", err);
          }
        };
      } catch (err) {
        setError("Failed to establish WebSocket connection.");
      }
    };

    connectWebSocket();

    const oauthInterval = setInterval(fetchOAuthStatus, 30000);

    return () => {
      if (ws) {
        ws.close();
      }
      if (reconnectInterval) {
        clearInterval(reconnectInterval);
      }
      if (oauthInterval) {
        clearInterval(oauthInterval);
      }
    };
  }, [fetchOAuthStatus]);

  const formatStatus = useCallback((status) => {
    const statusClasses = {
      'Ingested': 'bg-gray-700 text-gray-300',
      'Extracted': 'bg-yellow-900 text-yellow-300',
      'Classified': 'bg-purple-900 text-purple-300',
      'Routed': 'bg-green-900 text-green-300',
      'Failed': 'bg-red-900 text-red-300',
      'Processing': 'bg-blue-900 text-blue-300'
    };

    let className = 'bg-gray-700 text-gray-300';
    if (status?.startsWith('Re-')) {
      className = 'bg-blue-900 text-blue-300';
    } else if (status?.includes('Failed')) {
      className = 'bg-red-900 text-red-300';
    } else {
      className = statusClasses[status] || 'bg-gray-700 text-gray-300';
    }

    return (
      <span className={`px-2 py-1 rounded-full text-xs font-semibold ${className}`}>
        {status || 'Unknown'}
      </span>
    );
  }, []);

  const getOAuthButtonText = useCallback(() => {
    if (oauthStatus.connected_count > 0) {
      return '⚙️ Manage OAuth Connections';
    } else {
      return '🔗 Connect Mailbox';
    }
  }, [oauthStatus.connected_count]);

  const formatRoutingDestination = useCallback((destination) => {
    if (!destination) return 'Not routed';
    return destination
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  }, []);

  // Loading Screen
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
        <motion.div 
          className="text-center"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6 }}
        >
          <motion.div
            className="relative mb-8"
            animate={{ rotate: 360 }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          >
            <div className="w-24 h-24 border-4 border-slate-700 border-t-cyan-500 rounded-full"></div>
            <motion.div
              className="absolute inset-0 w-24 h-24 border-4 border-transparent border-t-purple-500 rounded-full"
              animate={{ rotate: -360 }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
            />
          </motion.div>
          <motion.h2 
            className="text-2xl font-bold gradient-text mb-4"
            animate={{ opacity: [0.5, 1, 0.5] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            Loading Dashboard
          </motion.h2>
          <motion.p 
            className="text-slate-400"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
          >
            Initializing document processing pipeline...
          </motion.p>
        </motion.div>
      </div>
    );
  }

  // Service Unavailable Screen
  if (documents.length === 0 && !error && !loading) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <motion.div 
          className="text-center max-w-lg glass-card-strong rounded-2xl p-8 shadow-modern-lg"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6 }}
        >
          <motion.div 
            className="w-20 h-20 rounded-full glass-card flex items-center justify-center mx-auto mb-6"
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          >
            <span className="text-4xl">⚡</span>
          </motion.div>
          <h1 className="text-3xl font-bold gradient-text mb-4">Service Starting</h1>
          <p className="text-slate-400 mb-8 leading-relaxed">
            The document processing backend is initializing. Please ensure the web_ui service is running on port 8000.
          </p>
          <div className="space-y-4 text-sm text-slate-500 mb-8">
            <p>To start the backend service:</p>
            <div className="glass-card rounded-lg p-4 text-left">
              <code className="text-cyan-400 font-mono">
                cd web_ui && python main.py
              </code>
            </div>
          </div>
          <motion.button 
            onClick={() => window.location.reload()} 
            className="btn-modern px-6 py-3 text-white font-semibold"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            Retry Connection
          </motion.button>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8">
      {/* Background Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <motion.div
          className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-cyan-500/10 to-purple-500/10 rounded-full blur-3xl"
          animate={{ 
            scale: [1, 1.1, 1],
            rotate: [0, 90, 180, 270, 360]
          }}
          transition={{ 
            duration: 20,
            repeat: Infinity,
            ease: "linear"
          }}
        />
        <motion.div
          className="absolute -bottom-40 -left-40 w-80 h-80 bg-gradient-to-tr from-purple-500/10 to-pink-500/10 rounded-full blur-3xl"
          animate={{ 
            scale: [1.1, 1, 1.1],
            rotate: [360, 270, 180, 90, 0]
          }}
          transition={{ 
            duration: 25,
            repeat: Infinity,
            ease: "linear"
          }}
        />
      </div>

      {/* Main Content */}
      <div className="relative z-10">
        <Header wsConnected={wsConnected} oauthStatus={oauthStatus} />

        <main className="max-w-7xl mx-auto space-y-8">
          {/* Upload Panel */}
          <UploadPanel />

          {/* Gmail Integration Panel */}
          <motion.div
            className="glass-card-strong rounded-2xl shadow-modern-lg p-6"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
          >
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
              <div>
                <h3 className="text-2xl font-bold text-slate-100 mb-2">
                  Gmail Integration
                </h3>
                <p className="text-slate-400 text-sm">
                  Connect your Gmail accounts for automatic document processing
                </p>
              </div>
              <motion.button 
                onClick={handleOAuthAction}
                className={`btn-modern px-6 py-3 font-semibold whitespace-nowrap ${
                  oauthStatus.ingestor_service_status === 'connected' 
                    ? 'text-white' 
                    : 'opacity-50 cursor-not-allowed'
                }`}
                disabled={oauthStatus.ingestor_service_status !== 'connected'}
                title={oauthStatus.ingestor_service_status !== 'connected' ? 'Ingestor service not available' : ''}
                whileHover={oauthStatus.ingestor_service_status === 'connected' ? { scale: 1.05 } : {}}
                whileTap={oauthStatus.ingestor_service_status === 'connected' ? { scale: 0.95 } : {}}
              >
                {getOAuthButtonText()}
              </motion.button>
            </div>
            
            <div className="space-y-4">
              <AnimatePresence>
                {oauthStatus.connected_count > 0 ? (
                  oauthStatus.mailboxes.map((mailbox, index) => (
                    <motion.div 
                      key={index} 
                      className="glass-card rounded-xl p-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4"
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.1 }}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-slate-200 truncate">{mailbox.email}</p>
                        
                        
                      </div>
                      <motion.div 
                        className="flex items-center space-x-2 text-green-400 font-semibold flex-shrink-0"
                        animate={{ opacity: [0.7, 1, 0.7] }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                        <span className="text-sm">Active</span>
                      </motion.div>
                    </motion.div>
                  ))
                ) : (
                  <motion.div 
                    className="text-center py-8 glass-card rounded-xl"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    <div className="text-6xl mb-4">📧</div>
                    <p className="text-slate-400 mb-4">
                      {oauthStatus.ingestor_service_status === 'connected' 
                        ? "No Gmail accounts connected yet" 
                        : "Ingestor service unavailable"}
                    </p>
                    <p className="text-sm text-slate-500">
                      {oauthStatus.ingestor_service_status === 'connected' 
                        ? "Click 'Connect Mailbox' to add your Gmail accounts and enable automatic document processing." 
                        : "Please ensure the ingestor service is running on port 8001."}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Document Management Section */}
          <motion.div
            className="glass-card rounded-2xl shadow-modern overflow-hidden"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
          >
            <div className="border-b border-slate-700/50 bg-gradient-to-r from-slate-800/50 to-slate-700/50">
              <nav className="flex space-x-8 px-6">
                <motion.button
                  onClick={() => setActiveTab('documents')}
                  className={`py-4 px-2 border-b-2 font-semibold text-sm flex items-center space-x-3 transition-all ${
                    activeTab === 'documents'
                      ? 'border-cyan-500 text-cyan-400'
                      : 'border-transparent text-slate-400 hover:text-slate-300 hover:border-slate-500'
                  }`}
                  whileHover={{ y: -2 }}
                >
                  <span className="text-lg">📊</span>
                  <span>Document Pipeline</span>
                  <motion.span 
                    className="bg-gradient-to-r from-cyan-500/20 to-purple-500/20 text-slate-300 px-2 py-1 rounded-full text-xs border border-slate-600/50"
                    animate={{ scale: [1, 1.05, 1] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  >
                    {documents.length}
                  </motion.span>
                </motion.button>
              </nav>
            </div>
          </motion.div>

          {/* Error Display */}
          <AnimatePresence>
            {error && (
              <motion.div
                className="glass-card-strong rounded-xl border border-red-500/30 bg-gradient-to-r from-red-500/10 to-red-600/5 p-4"
                initial={{ opacity: 0, y: -20, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -20, scale: 0.95 }}
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <span className="text-2xl">⚠️</span>
                    <span className="text-red-300 font-medium">{error}</span>
                  </div>
                  <motion.button
                    onClick={() => setError(null)}
                    className="text-red-300 hover:text-red-100 p-1 rounded-full hover:bg-red-500/20 transition-colors"
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                  >
                    ✕
                  </motion.button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Document Table */}
          {activeTab === 'documents' && (
            <DocumentTable 
              documents={documents}
              expandedRow={expandedRow}
              handleRowClick={handleRowClick}
              handleManualAction={handleManualAction}
              formatStatus={formatStatus}
              formatRoutingDestination={formatRoutingDestination}
              setExpandedRow={setExpandedRow}
            />
          )}
        </main>
      </div>
    </div>
  );
};

export default Dashboard;