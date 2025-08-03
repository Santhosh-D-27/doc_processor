// In web_ui/frontend/src/App.jsx

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import ProgressBar from './components/ProgressBar';
import UploadPanel from './components/UploadPanel';


const API_URL = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';
const OAUTH_MANAGER_URL = 'http://127.0.0.1:8001';

function App() {
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

  const handleRowClick = async (docId) => {
    if (expandedRow && expandedRow.id === docId) {
      setExpandedRow(null);
    } else {
      try {
        const response = await axios.get(`${API_URL}/history/${docId}`);
        setExpandedRow({ id: docId, history: response.data });
      } catch (err) {
        console.error("Failed to fetch document history:", err);
        setError("Could not load document details.");
      }
    }
  };

  const handleManualAction = async (action, docId, e) => {
    e.stopPropagation();
    try {
      await axios.post(`${API_URL}/${action}/${docId}`);
      setDocuments(docs => docs.map(d => 
        d.document_id === docId ? { ...d, status: `Re-${action}...` } : d
      ));
    } catch (err) {
      console.error(`Failed to ${action}:`, err);
      setError(`Failed to start re-${action} process.`);
    }
  };

  const fetchOAuthStatus = async () => {
    try {
      const response = await axios.get(`${API_URL}/oauth-status`);
      setOauthStatus(response.data || {
        connected_count: 0,
        mailboxes: [],
        ingestor_service_status: 'disconnected'
      });
    } catch (err) {
      console.error("Failed to fetch OAuth status:", err);
      setOauthStatus({
        connected_count: 0,
        mailboxes: [],
        ingestor_service_status: 'error'
      });
    }
  };

  const handleOAuthAction = () => {
    // Open OAuth manager in new window
    window.open(OAUTH_MANAGER_URL, '_blank', 'width=800,height=600');
    
    // Set up interval to check for updates while window is open
    const checkInterval = setInterval(() => {
      fetchOAuthStatus();
    }, 2000);
    
    // Clear interval after 2 minutes
    setTimeout(() => {
      clearInterval(checkInterval);
    }, 120000);
  };

  useEffect(() => {
    const fetchInitialDocuments = async () => {
      try {
        setLoading(true);
        const response = await axios.get(`${API_URL}/documents`);
        setDocuments(response.data || []);
        setError(null);
      } catch (err) {
        console.error("Failed to fetch initial documents:", err);
        setError("Could not connect to the backend.");
      } finally {
        setLoading(false);
      }
    };

    fetchInitialDocuments();
    fetchOAuthStatus();

    // WebSocket connection with reconnection logic
    let ws;
    let reconnectInterval;

    const connectWebSocket = () => {
      try {
        ws = new WebSocket(WS_URL);
        
        ws.onopen = () => {
          console.log("WebSocket connection established.");
          setWsConnected(true);
          setError(null);
          if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
          }
        };

        ws.onclose = () => {
          console.log("WebSocket connection closed.");
          setWsConnected(false);
          
          // Attempt to reconnect every 5 seconds
          if (!reconnectInterval) {
            reconnectInterval = setInterval(() => {
              console.log("Attempting to reconnect WebSocket...");
              connectWebSocket();
            }, 5000);
          }
        };

        ws.onerror = (error) => {
          console.error("WebSocket error:", error);
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
                newDocs[docIndex] = { ...newDocs[docIndex], ...newStatusEvent };
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
        console.error("Error creating WebSocket connection:", err);
        setError("Failed to establish WebSocket connection.");
      }
    };

    connectWebSocket();

    // Refresh OAuth status every 30 seconds
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
  }, []);

  const formatStatus = (status) => {
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
  };

  const getOAuthStatusColor = () => {
    if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count > 0) {
      return 'text-green-400';
    } else if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count === 0) {
      return 'text-yellow-400';
    } else {
      return 'text-red-400';
    }
  };

  const getOAuthStatusDot = () => {
    if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count > 0) {
      return 'bg-green-500';
    } else if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count === 0) {
      return 'bg-yellow-500';
    } else {
      return 'bg-red-500';
    }
  };

  const getOAuthButtonText = () => {
    if (oauthStatus.connected_count > 0) {
      return '⚙️ Manage OAuth Connections';
    } else {
      return '🔗 Connect Mailbox';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen p-4 sm:p-8 bg-gray-900 text-gray-100 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-teal-500 mx-auto"></div>
          <p className="mt-4 text-xl">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-gray-900 text-gray-100">
      <header className="text-center mb-10">
        <motion.h1
          initial={{ opacity: 0, y: -50 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-4xl sm:text-5xl font-bold text-gray-100"
        >
          Document Processing Dashboard
        </motion.h1>
        
        {/* Connection Status Indicators */}
        <div className="mt-4 flex items-center justify-center space-x-6">
          <div className={`flex items-center space-x-2 ${wsConnected ? 'text-green-400' : 'text-red-400'}`}>
            <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-red-500'}`}></div>
            <span className="text-sm">WebSocket {wsConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
          
          <div className={`flex items-center space-x-2 ${getOAuthStatusColor()}`}>
            <div className={`w-2 h-2 rounded-full ${getOAuthStatusDot()}`}></div>
            <span className="text-sm">
              Gmail: {oauthStatus.connected_count} connected
              {oauthStatus.connected_count > 0 && ` (${oauthStatus.mailboxes.map(m => m.email.split('@')[0]).join(', ')})`}
            </span>
          </div>
          
          <div className={`flex items-center space-x-2 ${oauthStatus.ingestor_service_status === 'connected' ? 'text-blue-400' : 'text-red-400'}`}>
            <div className={`w-2 h-2 rounded-full ${oauthStatus.ingestor_service_status === 'connected' ? 'bg-blue-500' : 'bg-red-500'}`}></div>
            <span className="text-sm">Ingestor {oauthStatus.ingestor_service_status}</span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mb-10"
        >
          <UploadPanel />
        </motion.div>

        {/* OAuth Status Panel */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mb-10"
        >
          <div className="bg-gray-400/10 backdrop-blur-md rounded-xl shadow-lg border border-gray-200/10 p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-semibold text-gray-200">Gmail Integration</h3>
              <button 
                onClick={handleOAuthAction}
                className={`px-4 py-2 font-bold rounded-lg transition-colors ${
                  oauthStatus.ingestor_service_status === 'connected' 
                    ? 'bg-blue-600 hover:bg-blue-500 text-white' 
                    : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                }`}
                disabled={oauthStatus.ingestor_service_status !== 'connected'}
                title={oauthStatus.ingestor_service_status !== 'connected' ? 'Ingestor service not available' : ''}
              >
                {getOAuthButtonText()}
              </button>
            </div>
            
            <div className="space-y-3">
              {oauthStatus.connected_count > 0 ? (
                oauthStatus.mailboxes.map((mailbox, index) => (
                  <div key={index} className="flex justify-between items-center bg-gray-900/50 p-3 rounded-lg">
                    <div>
                      <p className="font-semibold text-gray-200">{mailbox.email}</p>
                      <p className="text-sm text-gray-400">
                        Connected: {new Date(mailbox.connected_at).toLocaleString()}
                      </p>
                      {mailbox.expires_at && (
                        <p className="text-xs text-gray-500">
                          Token expires: {new Date(mailbox.expires_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                    <div className="text-green-400 text-sm font-semibold">
                      ✓ Active
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-4">
                  <p className="text-gray-400 mb-3">
                    {oauthStatus.ingestor_service_status === 'connected' 
                      ? "No Gmail accounts connected." 
                      : "Ingestor service unavailable."}
                  </p>
                  <p className="text-sm text-gray-500">
                    {oauthStatus.ingestor_service_status === 'connected' 
                      ? "Click 'Connect Mailbox' to add your Gmail accounts." 
                      : "Please ensure the ingestor service is running on port 8001."}
                  </p>
                </div>
              )}
            </div>
          </div>
        </motion.div>

        {/* Tab Navigation */}
        <div className="bg-gray-800 rounded-xl shadow-lg mb-6">
          <div className="border-b border-gray-700">
            <nav className="flex space-x-8 px-6">
              <button
                onClick={() => setActiveTab('documents')}
                className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
                  activeTab === 'documents'
                    ? 'border-teal-500 text-teal-400'
                    : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500'
                }`}
              >
                <span>Recent Documents</span>
                <span className="bg-gray-700 text-gray-300 px-2 py-1 rounded-full text-xs">
                  {documents.length}
                </span>
              </button>
            </nav>
          </div>
        </div>

        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-red-400 bg-red-900/50 p-4 rounded-lg mb-6 border border-red-800"
          >
            <div className="flex items-center justify-between">
              <span>{error}</span>
              <button
                onClick={() => setError(null)}
                className="text-red-300 hover:text-red-100"
              >
                ✕
              </button>
            </div>
          </motion.div>
        )}

        {/* Documents Tab */}
        {activeTab === 'documents' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="bg-gray-800 backdrop-blur-md rounded-xl shadow-lg border border-gray-700 overflow-hidden"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="border-b border-gray-700 bg-gray-900/50">
                  <tr>
                    <th className="p-4 font-semibold">Filename</th>
                    <th className="p-4 font-semibold">Status</th>
                    <th className="p-4 font-semibold">Type</th>
                    <th className="p-4 font-semibold">Confidence</th>
                    <th className="p-4 font-semibold">VIP</th>
                    <th className="p-4 font-semibold">Summary</th>
                    <th className="p-4 font-semibold">Last Updated</th>
                  </tr>
                </thead>
                <tbody>
                  <AnimatePresence>
                    {documents.length === 0 ? (
                      <motion.tr 
                        initial={{ opacity: 0 }} 
                        animate={{ opacity: 1 }} 
                        exit={{ opacity: 0 }}
                      >
                        <td colSpan="7" className="p-8 text-center text-gray-400">
                          <div className="flex flex-col items-center space-y-3">
                            <div className="w-16 h-16 rounded-full bg-gray-700 flex items-center justify-center">
                              <svg className="w-8 h-8 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                            </div>
                            <p className="text-lg">No documents processed yet</p>
                            <p className="text-sm">Upload a document or connect your Gmail accounts!</p>
                          </div>
                        </td>
                      </motion.tr>
                    ) : (
                      documents.map((doc) => (
                        <React.Fragment key={doc.document_id}>
                          <motion.tr
                            className={`border-b border-gray-700 hover:bg-gray-700/50 cursor-pointer transition-colors ${
                              expandedRow?.id === doc.document_id ? 'bg-gray-700/30' : ''
                            }`}
                            onClick={() => handleRowClick(doc.document_id)}
                            layout
                            initial={{ opacity: 0, y: -20 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0 }}
                          >
                            <td className="p-4">
                              <div className="font-mono text-sm truncate max-w-xs" title={doc.filename}>
                                {doc.filename || 'N/A'}
                              </div>
                            </td>
                            <td className="p-4">
                              {formatStatus(doc.status)}
                            </td>
                            <td className="p-4 text-sm">{doc.doc_type || 'N/A'}</td>
                            <td className="p-4 text-sm">
                              {doc.confidence != null ? (
                                <span className={`${
                                  doc.confidence > 0.8 ? 'text-green-400' :
                                  doc.confidence > 0.6 ? 'text-yellow-400' : 'text-red-400'
                                }`}>
                                  {doc.confidence.toFixed(2)}
                                </span>
                              ) : 'N/A'}
                            </td>
                            <td className="p-4">
                              {doc.is_vip ? (
                                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${
                                  doc.vip_level?.toLowerCase() === 'high' ? 'bg-red-700 text-red-300' :
                                  doc.vip_level?.toLowerCase() === 'medium' ? 'bg-orange-700 text-orange-300' :
                                  'bg-teal-700 text-teal-300'
                                }`}>
                                  VIP ({doc.vip_level?.toUpperCase() || 'LOW'})
                                </span>
                              ) : (
                                <span className="text-gray-500 text-sm">No</span>
                              )}
                            </td>
                            <td className="p-4 text-sm max-w-xs">
                              <div className="truncate" title={doc.summary}>
                                {doc.summary || 'N/A'}
                              </div>
                            </td>
                            <td className="p-4 text-sm text-gray-400">
                              {doc.last_updated ? new Date(doc.last_updated).toLocaleString() : 'N/A'}
                            </td>
                          </motion.tr>
                          
                          {expandedRow && expandedRow.id === doc.document_id && (
                            <motion.tr
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: 'auto' }}
                              exit={{ opacity: 0, height: 0 }}
                            >
                              <td colSpan="7" className="p-0 bg-gray-900/50">
                                <div className="p-6 flex items-center justify-between border-t border-gray-600">
                                  <div className="flex-grow mr-6">
                                    <ProgressBar history={expandedRow.history} />
                                  </div>
                                  <div className="flex flex-col gap-2 min-w-0">
                                    <button
                                      onClick={(e) => handleManualAction('re-extract', doc.document_id, e)}
                                      className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                      disabled={doc.status === 'Ingestion Failed' || doc.status === 'Extraction Failed'}
                                    >
                                      Re-extract
                                    </button>
                                    <button
                                      onClick={(e) => handleManualAction('re-classify', doc.document_id, e)}
                                      className="px-4 py-2 bg-yellow-600 hover:bg-yellow-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                      disabled={doc.status === 'Classification Failed'}
                                    >
                                      Re-classify
                                    </button>
                                  </div>
                                </div>
                              </td>
                            </motion.tr>
                          )}
                        </React.Fragment>
                      ))
                    )}
                  </AnimatePresence>
                </tbody>
              </table>
            </div>
          </motion.div>
        )}

       
      </main>
    </div>
  );
}

export default App;