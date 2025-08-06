import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { motion } from 'framer-motion';
import Header from './Header';
import UploadPanel from './UploadPanel';
import DocumentTable from './DocumentTable';

const API_URL = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';
const OAUTH_MANAGER_URL = 'http://172.0.0.1:8001';

const Dashboard = () => {
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState(null);
  const [activeTab, setActiveTab] = useState('documents');
  const [wsConnected, setWsConnected] = useState(false);
  const [isChatbotOpen, setIsChatbotOpen] = useState(false); // New state for chatbot
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
              const sortedDocs = newDocs.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));
              console.log("Documents array updated:", sortedDocs);
              return sortedDocs;
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
  }, [fetchOAuthStatus, handleRowClick]);

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

  if (documents.length === 0 && !error && !loading) {
    return (
      <div className="min-h-screen p-4 sm:p-8 bg-gray-900 text-gray-100 flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="w-16 h-16 rounded-full bg-gray-700 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-200 mb-4">Backend Service Unavailable</h1>
          <p className="text-gray-400 mb-6">
            The document processing backend is not running. Please start the web_ui service to view documents.
          </p>
          <div className="space-y-2 text-sm text-gray-500">
            <p>To start the backend service:</p>
            <code className="bg-gray-800 px-2 py-1 rounded text-teal-400">
              cd web_ui && python main.py
            </code>
          </div>
          <button 
            onClick={() => window.location.reload()} 
            className="mt-6 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-2 sm:p-4 lg:p-8 bg-gray-900 text-gray-100">
      <Header wsConnected={wsConnected} oauthStatus={oauthStatus} />

      <main className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mb-6 lg:mb-10"
        >
          <UploadPanel />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mb-6 lg:mb-10"
        >
          <div className="bg-gray-400/10 backdrop-blur-md rounded-xl shadow-lg border border-gray-200/10 p-4 sm:p-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
              <h3 className="text-lg sm:text-xl font-semibold text-gray-200">Gmail Integration</h3>
              <button 
                onClick={handleOAuthAction}
                className={`px-3 sm:px-4 py-2 font-bold rounded-lg transition-colors text-sm sm:text-base whitespace-nowrap ${
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
                  <div key={index} className="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-gray-900/50 p-3 rounded-lg gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-200 text-sm sm:text-base truncate">{mailbox.email}</p>
                      <p className="text-xs sm:text-sm text-gray-400">
                        Connected: {new Date(mailbox.connected_at).toLocaleString()}
                      </p>
                      {mailbox.expires_at && (
                        <p className="text-xs text-gray-500">
                          Token expires: {new Date(mailbox.expires_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                    <div className="text-green-400 text-xs sm:text-sm font-semibold flex-shrink-0">
                      ✓ Active
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-4">
                  <p className="text-gray-400 mb-3 text-sm sm:text-base">
                    {oauthStatus.ingestor_service_status === 'connected' 
                      ? "No Gmail accounts connected." 
                      : "Ingestor service unavailable."}
                  </p>
                  <p className="text-xs sm:text-sm text-gray-500">
                    {oauthStatus.ingestor_service_status === 'connected' 
                      ? "Click 'Connect Mailbox' to add your Gmail accounts." 
                      : "Please ensure the ingestor service is running on port 8001."}
                  </p>
                </div>
              )}
            </div>
          </div>
        </motion.div>

        <div className="bg-gray-800 rounded-xl shadow-lg mb-4 lg:mb-6">
          <div className="border-b border-gray-700">
            <nav className="flex space-x-4 sm:space-x-8 px-4 sm:px-6">
              <button
                onClick={() => setActiveTab('documents')}
                className={`py-3 sm:py-4 px-1 border-b-2 font-medium text-xs sm:text-sm flex items-center space-x-2 transition-colors ${
                  activeTab === 'documents'
                    ? 'border-teal-500 text-teal-400'
                    : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500'
                }`}
              >
                <span>Recent Documents</span>
                <span className="bg-gray-700 text-gray-300 px-1.5 sm:px-2 py-0.5 sm:py-1 rounded-full text-xs">
                  {documents.length}
                </span>
              </button>
            </nav>
          </div>
          <div className="p-4 flex justify-between items-center">
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-400">
                WebSocket: {wsConnected ? '🟢 Connected' : '🔴 Disconnected'}
              </span>
            </div>
          </div>
        </div>

        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-red-400 bg-red-900/50 p-3 sm:p-4 rounded-lg mb-4 lg:mb-6 border border-red-800"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm sm:text-base">{error}</span>
              <button
                onClick={() => setError(null)}
                className="text-red-300 hover:text-red-100 ml-2"
              >
                ✕
              </button>
            </div>
          </motion.div>
        )}

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
  );
};

export default Dashboard;