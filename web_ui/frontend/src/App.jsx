// In web_ui/frontend/src/App.jsx

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import ProgressBar from './components/ProgressBar';
import UploadPanel from './components/UploadPanel';

const API_URL = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';
const OAUTH_MANAGER_URL = 'http://127.0.0.1:8001';

// Error Boundary Component
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Error Boundary caught an error:', error, errorInfo);
    this.setState({ error, errorInfo });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen p-4 bg-gray-900 text-gray-100 flex items-center justify-center">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-red-400 mb-4">Something went wrong</h1>
            <p className="text-gray-300 mb-4">The application encountered an error and crashed.</p>
            <button 
              onClick={() => window.location.reload()} 
              className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded"
            >
              Reload Page
            </button>
            {this.state.error && (
              <details className="mt-4 text-left">
                <summary className="cursor-pointer text-gray-400">Error Details</summary>
                <pre className="text-xs text-red-300 mt-2 overflow-auto">
                  {this.state.error.toString()}
                </pre>
              </details>
            )}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// Simple Debug Component
const DebugComponent = () => {
  console.log('[Debug] Debug component rendering');
  return null; // Disabled debug component
};

function App() {
  console.log('[App] Component rendering...');
  
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

  // Test mode - bypass API calls to isolate the issue
  const TEST_MODE = false;
  const TEST_DOCUMENTS = [
    {
      document_id: 'test-1',
      filename: 'test-document.pdf',
      status: 'Routed',
      doc_type: 'Invoice',
      routing_destination: 'erp_system',
      last_updated: new Date().toISOString()
    }
  ];

  console.log('[App] Current state:', { 
    documentsCount: documents.length, 
    loading, 
    error, 
    expandedRow: expandedRow?.id,
    wsConnected,
    testMode: TEST_MODE
  });

  const handleRowClick = async (docId) => {
    console.log('[App] Row clicked:', docId);
    try {
      if (expandedRow && expandedRow.id === docId) {
        console.log('[App] Collapsing row:', docId);
        setExpandedRow(null);
      } else {
        console.log('[App] Expanding row:', docId);
        
        if (TEST_MODE) {
          console.log('[App] Using test history data');
          setExpandedRow({ 
            id: docId, 
            history: [
              { status: 'Ingested', timestamp: new Date().toISOString() },
              { status: 'Extracted', timestamp: new Date().toISOString() },
              { status: 'Classified', timestamp: new Date().toISOString() },
              { status: 'Routed', timestamp: new Date().toISOString() }
            ] 
          });
        } else {
          const response = await axios.get(`${API_URL}/history/${docId}`);
          console.log('[App] History response:', response.data);
          
          if (response.data && Array.isArray(response.data)) {
            setExpandedRow({ id: docId, history: response.data });
          } else {
            console.warn('[App] Invalid history data received:', response.data);
            setExpandedRow({ id: docId, history: [] });
          }
        }
      }
    } catch (err) {
      console.error('[App] Failed to fetch document history:', err);
      // Don't set error state for history fetch failures, just show empty history
      setExpandedRow({ id: docId, history: [] });
      // Only show error if it's not a 404 (no history found) and not a network error
      if (err.response && err.response.status !== 404 && 
          err.code !== 'ERR_NETWORK' && !err.message.includes('Network Error')) {
        setError("Could not load document details.");
      }
    }
  };

  const handleManualAction = async (action, docId, e) => {
    console.log('[App] Manual action:', action, docId);
    e.stopPropagation();
    try {
      let response;
      
      if (action === 're-classify') {
        // Use enhanced re-classify with override parameters
        response = await axios.post(`${API_URL}/re-classify/${docId}`, {
          manual_type_hint: null,  // Let AI decide
          confidence_threshold: 0.75,
          force_classification: false,
          reason: 'Manual re-classification request'
        });
      } else if (action === 're-extract') {
        // Use enhanced re-extract with override parameters
        response = await axios.post(`${API_URL}/re-extract/${docId}`, {
          ocr_engine: 'default',
          dpi: 300,
          language: 'eng',
          manual_text: null,
          preprocessing: null,
          reason: 'Manual re-extraction request'
        });
      } else {
        // Fallback to old endpoint for other actions
        response = await axios.post(`${API_URL}/${action}/${docId}`);
      }
      
      console.log(`[App] ${action} response:`, response.data);
      
      // Update document status to show override in progress
      setDocuments(docs => docs.map(d => 
        d.document_id === docId ? { 
          ...d, 
          status: `Re-${action}...`,
          override_in_progress: true,
          override_type: action
        } : d
      ));
      
      // Show success message
      setError(null);
      
    } catch (err) {
      console.error(`[App] Failed to ${action}:`, err);
      
      // Handle specific error cases
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
      console.error("[App] Failed to fetch OAuth status:", err);
      setOauthStatus({
        connected_count: 0,
        mailboxes: [],
        ingestor_service_status: 'error'
      });
    }
  };

  const handleOAuthAction = () => {
    console.log('[App] OAuth action triggered');
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
    console.log('[App] useEffect running...');
    
    const fetchInitialDocuments = async () => {
      try {
        console.log('[App] Fetching initial documents...');
        setLoading(true);
        
        if (TEST_MODE) {
          console.log('[App] Using test data');
          setDocuments(TEST_DOCUMENTS);
          setError(null);
        } else {
          const response = await axios.get(`${API_URL}/documents`);
          const docs = response.data || [];
          console.log('[App] Documents received:', docs.length);
          // Ensure documents is always an array
          setDocuments(Array.isArray(docs) ? docs : []);
          setError(null);
        }
      } catch (err) {
        console.error("[App] Failed to fetch initial documents:", err);
        if (err.code === 'ERR_NETWORK' || err.message.includes('Network Error')) {
          setError("Backend service is not available. Please ensure the web_ui service is running on port 8000.");
        } else {
          setError("Could not connect to the backend.");
        }
        setDocuments([]); // Ensure documents is always an array
      } finally {
        setLoading(false);
      }
    };

    fetchInitialDocuments();
    
    if (!TEST_MODE) {
      fetchOAuthStatus();
    }

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
            console.log('[WebSocket] Received message:', event.data);
            const newStatusEvent = JSON.parse(event.data);
            console.log('[WebSocket] Parsed event:', newStatusEvent);
            
            let isNewDocument = false;
            setDocuments(prevDocs => {
              console.log('[WebSocket] Current documents count:', prevDocs.length);
              const docIndex = prevDocs.findIndex(doc => doc.document_id === newStatusEvent.document_id);
              console.log('[WebSocket] Document index:', docIndex);
              
              let newDocs;
              if (docIndex > -1) {
                console.log('[WebSocket] Updating existing document');
                newDocs = [...prevDocs];
                // Clear override flags when processing is complete
                const updatedDoc = { 
                  ...newDocs[docIndex], 
                  ...newStatusEvent,
                  override_in_progress: false,
                  override_type: null
                };
                newDocs[docIndex] = updatedDoc;
              } else {
                console.log('[WebSocket] Adding new document');
                isNewDocument = true;
                newDocs = [newStatusEvent, ...prevDocs];
              }
              console.log('[WebSocket] New documents count:', newDocs.length);
              return newDocs.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));
            });

            setExpandedRow(prevExpanded => {
              if (isNewDocument) {
                console.log('[WebSocket] Setting expanded row for new document');
                return { id: newStatusEvent.document_id, history: [newStatusEvent] };
              }
              if (prevExpanded && prevExpanded.id === newStatusEvent.document_id) {
                console.log('[WebSocket] Updating expanded row history');
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

  const formatRoutingDestination = (destination) => {
    if (!destination) return 'Not routed';
    
    // Convert snake_case to Title Case
    return destination
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  };

  if (loading) {
    return (
      <ErrorBoundary>
        <DebugComponent />
        <div className="min-h-screen p-4 sm:p-8 bg-gray-900 text-gray-100 flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-teal-500 mx-auto"></div>
            <p className="mt-4 text-xl">Loading dashboard...</p>
          </div>
        </div>
      </ErrorBoundary>
    );
  }

  // Show fallback UI if no documents and no error (likely backend not available)
  if (documents.length === 0 && !error && !loading) {
    return (
      <ErrorBoundary>
        <DebugComponent />
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
      </ErrorBoundary>
    );
  }

  try {
    return (
      <ErrorBoundary>
        <DebugComponent />
        <div className="min-h-screen p-2 sm:p-4 lg:p-8 bg-gray-900 text-gray-100">
        <header className="text-center mb-6 lg:mb-10">
          <motion.h1
            initial={{ opacity: 0, y: -50 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="text-2xl sm:text-3xl lg:text-4xl xl:text-5xl font-bold text-gray-100 px-2"
          >
            Operator Dashboard
          </motion.h1>
          
          {/* Connection Status Indicators - Responsive Layout */}
          <div className="mt-4 flex flex-col sm:flex-row items-center justify-center gap-2 sm:gap-4 lg:gap-6 px-2">
            <div className={`flex items-center space-x-2 ${wsConnected ? 'text-green-400' : 'text-red-400'}`}>
              <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-red-500'}`}></div>
              <span className="text-xs sm:text-sm">WebSocket {wsConnected ? 'Connected' : 'Disconnected'}</span>
            </div>
            
            <div className={`flex items-center space-x-2 ${getOAuthStatusColor()}`}>
              <div className={`w-2 h-2 rounded-full ${getOAuthStatusDot()}`}></div>
              <span className="text-xs sm:text-sm">
                Gmail: {oauthStatus.connected_count} connected
                {oauthStatus.connected_count > 0 && (
                  <span className="hidden sm:inline">
                    {` (${oauthStatus.mailboxes.map(m => m.email.split('@')[0]).join(', ')})`}
                  </span>
                )}
              </span>
            </div>
            
            <div className={`flex items-center space-x-2 ${oauthStatus.ingestor_service_status === 'connected' ? 'text-blue-400' : 'text-red-400'}`}>
              <div className={`w-2 h-2 rounded-full ${oauthStatus.ingestor_service_status === 'connected' ? 'bg-blue-500' : 'bg-red-500'}`}></div>
              <span className="text-xs sm:text-sm">Ingestor {oauthStatus.ingestor_service_status}</span>
            </div>
          </div>
        </header>

        <main className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="mb-6 lg:mb-10"
          >
            <UploadPanel />
          </motion.div>

          {/* OAuth Status Panel - Responsive */}
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

          {/* Tab Navigation */}
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

          {/* Documents Tab - Responsive Design */}
          {activeTab === 'documents' && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5 }}
              className="bg-gray-800 backdrop-blur-md rounded-xl shadow-lg border border-gray-700 overflow-hidden"
            >
              {/* Desktop Table View */}
              <div className="hidden lg:block overflow-x-auto">
                <table className="w-full text-left table-fixed">
                  <thead className="border-b border-gray-700 bg-gray-900/50">
                    <tr>
                      <th className="p-3 sm:p-4 font-semibold text-sm w-1/5">Name</th>
                      <th className="p-3 sm:p-4 font-semibold text-sm w-1/8">Type</th>
                      <th className="p-3 sm:p-4 font-semibold text-sm w-1/8">Status</th>
                      <th className="p-3 sm:p-4 font-semibold text-sm w-1/6">Routed To</th>
                      <th className="p-3 sm:p-4 font-semibold text-sm w-1/5">Last Updated</th>
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
                          <td colSpan="5" className="p-8 text-center text-gray-400">
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
                        documents.filter(doc => doc && doc.document_id).map((doc) => (
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
                              <td className="p-3 sm:p-4">
                                <div className="font-mono text-sm truncate" title={doc.filename}>
                                  {doc.filename || 'N/A'}
                                </div>
                              </td>
                              <td className="p-3 sm:p-4 text-sm">{doc.doc_type || 'N/A'}</td>
                              <td className="p-3 sm:p-4">
                                {formatStatus(doc.status)}
                                {doc.override_in_progress && (
                                  <div className="mt-1">
                                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-purple-900 text-purple-300">
                                      <svg className="animate-spin -ml-1 mr-1 h-3 w-3 text-purple-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                      </svg>
                                      {doc.override_type === 're-classify' ? 'Re-classifying...' : 
                                       doc.override_type === 're-extract' ? 'Re-extracting...' : 
                                       doc.override_type === 're-route' ? 'Re-routing...' : 'Processing...'}
                                    </span>
                                  </div>
                                )}
                              </td>
                              <td className="p-3 sm:p-4 text-sm">
                                {doc.routing_destination ? (
                                  <span className="px-2 py-1 bg-blue-700 text-blue-300 rounded-full text-xs font-medium">
                                    {formatRoutingDestination(doc.routing_destination)}
                                  </span>
                                ) : (
                                  <span className="text-gray-500 text-xs">Not routed</span>
                                )}
                              </td>
                              <td className="p-3 sm:p-4 text-sm text-gray-400">
                                <div className="whitespace-nowrap">
                                  {doc.last_updated ? new Date(doc.last_updated).toLocaleString() : 'N/A'}
                                </div>
                              </td>
                            </motion.tr>
                            
                            {expandedRow && expandedRow.id === doc.document_id && (
                              <motion.tr
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                              >
                                <td colSpan="5" className="p-0 bg-gray-900/50">
                                  <div className="p-4 sm:p-6 flex flex-col lg:flex-row items-start lg:items-center justify-between border-t border-gray-600 gap-4">
                                    <div className="flex-grow w-full lg:w-auto min-w-0">
                                      <ProgressBar history={expandedRow.history || []} />
                                    </div>
                                    <div className="action-buttons flex-col">
                                      <button
                                        onClick={(e) => handleManualAction('re-extract', doc.document_id, e)}
                                        className="action-button bg-orange-600 hover:bg-orange-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                                        disabled={doc.status === 'Ingestion Failed' || doc.status === 'Extraction Failed'}
                                      >
                                        Re-extract
                                      </button>
                                      <button
                                        onClick={(e) => handleManualAction('re-classify', doc.document_id, e)}
                                        className="action-button bg-yellow-600 hover:bg-yellow-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
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

              {/* Mobile Card View */}
              <div className="lg:hidden">
                <AnimatePresence>
                  {documents.length === 0 ? (
                    <motion.div 
                      initial={{ opacity: 0 }} 
                      animate={{ opacity: 1 }} 
                      exit={{ opacity: 0 }}
                      className="p-8 text-center text-gray-400"
                    >
                      <div className="flex flex-col items-center space-y-3">
                        <div className="w-16 h-16 rounded-full bg-gray-700 flex items-center justify-center">
                          <svg className="w-8 h-8 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                        </div>
                        <p className="text-lg">No documents processed yet</p>
                        <p className="text-sm">Upload a document or connect your Gmail accounts!</p>
                      </div>
                    </motion.div>
                  ) : (
                    <div className="space-y-3 p-4">
                      {documents.map((doc) => (
                        <motion.div
                          key={doc.document_id}
                          initial={{ opacity: 0, y: -20 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          className={`bg-gray-700/30 rounded-lg p-4 cursor-pointer transition-colors ${
                            expandedRow?.id === doc.document_id ? 'ring-2 ring-teal-500' : 'hover:bg-gray-700/50'
                          }`}
                          onClick={() => handleRowClick(doc.document_id)}
                        >
                          {/* Document Header */}
                          <div className="flex justify-between items-start mb-3">
                            <div className="flex-1 min-w-0">
                              <h3 className="font-mono text-sm font-semibold text-gray-200 truncate" title={doc.filename}>
                                {doc.filename || 'N/A'}
                              </h3>
                              <div className="flex items-center gap-2 mt-1">
                                <span className="text-xs text-gray-400">{doc.doc_type || 'N/A'}</span>
                                <span className="text-xs text-gray-400">•</span>
                                {formatStatus(doc.status)}
                                {doc.override_in_progress && (
                                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium bg-purple-900 text-purple-300">
                                    <svg className="animate-spin -ml-0.5 mr-0.5 h-2 w-2 text-purple-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                    </svg>
                                    {doc.override_type === 're-classify' ? 'Re-classifying' : 
                                     doc.override_type === 're-extract' ? 'Re-extracting' : 
                                     doc.override_type === 're-route' ? 'Re-routing' : 'Processing'}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Document Details */}
                          <div className="space-y-2 text-sm">
                            <div className="flex justify-between">
                              <span className="text-gray-400">Routed To:</span>
                              <span className="text-gray-300 text-xs">
                                {doc.routing_destination ? (
                                  <span className="px-2 py-1 bg-blue-700 text-blue-300 rounded-full text-xs font-medium">
                                    {formatRoutingDestination(doc.routing_destination)}
                                  </span>
                                ) : (
                                  <span className="text-gray-500">Not routed</span>
                                )}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-gray-400">Last Updated:</span>
                              <span className="text-gray-300 text-xs">
                                {doc.last_updated ? new Date(doc.last_updated).toLocaleString() : 'N/A'}
                              </span>
                            </div>
                          </div>

                          {/* Expanded Content */}
                          {expandedRow && expandedRow.id === doc.document_id && (
                            <motion.div
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: 'auto' }}
                              exit={{ opacity: 0, height: 0 }}
                              className="mt-4 pt-4 border-t border-gray-600"
                            >
                              <div className="space-y-4">
                                <ProgressBar history={expandedRow.history} />
                                <div className="flex gap-2">
                                  <button
                                    onClick={(e) => handleManualAction('re-extract', doc.document_id, e)}
                                    className="flex-1 px-3 py-2 bg-orange-600 hover:bg-orange-500 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    disabled={doc.status === 'Ingestion Failed' || doc.status === 'Extraction Failed'}
                                  >
                                    Re-extract
                                  </button>
                                  <button
                                    onClick={(e) => handleManualAction('re-classify', doc.document_id, e)}
                                    className="flex-1 px-3 py-2 bg-yellow-600 hover:bg-yellow-500 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    disabled={doc.status === 'Classification Failed'}
                                  >
                                    Re-classify
                                  </button>
                                </div>
                              </div>
                            </motion.div>
                          )}
                        </motion.div>
                      ))}
                    </div>
                  )}
                </AnimatePresence>
              </div>
            </motion.div>
          )}

         
        </main>
      </div>
    </ErrorBoundary>
  );
  } catch (renderError) {
    console.error("Error during App rendering:", renderError);
    return (
      <ErrorBoundary>
        <DebugComponent />
        <div className="min-h-screen p-4 sm:p-8 bg-gray-900 text-gray-100 flex items-center justify-center">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-red-400 mb-4">Rendering Error</h1>
            <p className="text-gray-300 mb-4">The application encountered an error during rendering.</p>
            <button 
              onClick={() => window.location.reload()} 
              className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded"
            >
              Reload Page
            </button>
            {renderError && (
              <details className="mt-4 text-left">
                <summary className="cursor-pointer text-gray-400">Error Details</summary>
                <pre className="text-xs text-red-300 mt-2 overflow-auto">
                  {renderError.toString()}
                </pre>
              </details>
            )}
          </div>
        </div>
      </ErrorBoundary>
    );
  }
}

// Wrap the entire App with ErrorBoundary
const AppWithErrorBoundary = () => (
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);

export default AppWithErrorBoundary;