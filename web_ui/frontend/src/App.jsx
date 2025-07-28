// In web_ui/frontend/src/App.jsx

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import ProgressBar from './components/ProgressBar';
import UploadPanel from './components/UploadPanel';
import MailboxManager from './components/MailboxManager';

const API_URL = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';

function App() {
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);
  const [expandedRow, setExpandedRow] = useState(null);

  const handleRowClick = async (docId) => {
    if (expandedRow && expandedRow.id === docId) {
      setExpandedRow(null);
    } else {
      try {
        const response = await axios.get(`${API_URL}/history/${docId}`);
        setExpandedRow({ id: docId, history: response.data });
      } catch (err) {
        console.error("Failed to fetch document history:", err);
        alert("Could not load document details.");
      }
    }
  };

  const handleManualAction = async (action, docId, e) => {
    e.stopPropagation();
    try {
      await axios.post(`${API_URL}/${action}/${docId}`);
      setDocuments(docs => docs.map(d => d.document_id === docId ? { ...d, status: `Re-${action}...` } : d));
    } catch (err) {
      console.error(`Failed to ${action}:`, err);
      alert(`Failed to start re-${action} process.`);
    }
  };

  useEffect(() => {
    const fetchInitialDocuments = async () => {
      try {
        const response = await axios.get(`${API_URL}/documents`);
        setDocuments(response.data);
        setError(null);
      } catch (err) {
        console.error("Failed to fetch initial documents:", err);
        setError("Could not connect to the backend.");
      }
    };
    fetchInitialDocuments();

    const ws = new WebSocket(WS_URL);
    ws.onopen = () => console.log("WebSocket connection established.");
    ws.onclose = () => console.log("WebSocket connection closed.");
    ws.onerror = () => setError("WebSocket connection error.");

    ws.onmessage = (event) => {
      const updatedDoc = JSON.parse(event.data);
      setDocuments(prevDocs => {
        const docIndex = prevDocs.findIndex(doc => doc.document_id === updatedDoc.document_id);
        let newDocs;
        if (docIndex > -1) {
          newDocs = [...prevDocs];
          newDocs[docIndex] = updatedDoc;
        } else {
          newDocs = [updatedDoc, ...prevDocs];
        }
        return newDocs.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));
      });
    };

    return () => ws.close();
  }, []);

  return (
    <div className="min-h-screen p-4 sm:p-8">
      <header className="text-center mb-10">
        <motion.h1
          initial={{ opacity: 0, y: -50 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-4xl sm:text-5xl font-bold text-gray-100"
        >
          Document Processing Dashboard
        </motion.h1>
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

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mb-10"
        >
          <MailboxManager />
        </motion.div>

        <motion.h2
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="text-2xl font-semibold text-gray-300 mb-4"
        >
          Recent Documents
        </motion.h2>

        {error && <p className="text-red-400 bg-red-900/50 p-3 rounded-lg">{error}</p>}

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.6 }}
          className="bg-gray-400/10 backdrop-blur-md rounded-xl shadow-lg border border-gray-200/10 overflow-hidden"
        >
          <table className="w-full text-left">
            <thead className="border-b border-gray-200/10">
              <tr>
                <th className="p-4">Filename</th>
                <th className="p-4">Status</th>
                <th className="p-4">Document Type</th>
                <th className="p-4">Confidence</th>
                <th className="p-4">Last Updated</th>
              </tr>
            </thead>
            <tbody>
              <AnimatePresence>
                {documents.map((doc) => (
                  <React.Fragment key={doc.document_id}>
                    <motion.tr
                      className="border-b border-gray-200/5 hover:bg-gray-500/10 cursor-pointer"
                      onClick={() => handleRowClick(doc.document_id)}
                      layout
                      initial={{ opacity: 0, y: -20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                    >
                      <td className="p-4 font-mono text-sm">{doc.filename || 'N/A'}</td>
                      <td className="p-4">
                        <span className={`px-2 py-1 rounded-full text-xs font-semibold ${
                          doc.status === 'Ingested' ? 'bg-gray-700 text-gray-300' :
                          doc.status === 'Extracted' ? 'bg-yellow-900 text-yellow-300' :
                          doc.status === 'Classified' ? 'bg-purple-900 text-purple-300' :
                          doc.status === 'Routed' ? 'bg-green-900 text-green-300' : 
                          doc.status.startsWith('Re-') ? 'bg-blue-900 text-blue-300' : 'bg-red-900 text-red-300'
                        }`}>{doc.status}</span>
                      </td>
                      <td className="p-4">{doc.doc_type || 'N/A'}</td>
                      <td className="p-4">{doc.confidence != null ? doc.confidence.toFixed(2) : 'N/A'}</td>
                      <td className="p-4">{new Date(doc.last_updated).toLocaleString()}</td>
                    </motion.tr>
                    
                    {expandedRow && expandedRow.id === doc.document_id && (
                       <motion.tr
                         initial={{ opacity: 0 }}
                         animate={{ opacity: 1 }}
                         exit={{ opacity: 0 }}
                       >
                        <td colSpan="5" className="p-0 bg-gray-900/20">
                          <div className="p-4 flex items-center justify-between">
                            <div className="flex-grow">
                              <ProgressBar history={expandedRow.history} />
                            </div>
                            <div className="ml-4 flex flex-col gap-2">
                              <button
                                onClick={(e) => handleManualAction('re-extract', doc.document_id, e)}
                                className="px-3 py-1 bg-orange-600 hover:bg-orange-500 text-white text-xs font-bold rounded-md transition-colors"
                              >
                                Re-extract
                              </button>
                              <button
                                onClick={(e) => handleManualAction('re-classify', doc.document_id, e)}
                                className="px-3 py-1 bg-yellow-600 hover:bg-yellow-500 text-white text-xs font-bold rounded-md transition-colors"
                              >
                                Re-classify
                              </button>
                            </div>
                          </div>
                        </td>
                      </motion.tr>
                    )}
                  </React.Fragment>
                ))}
              </AnimatePresence>
            </tbody>
          </table>
        </motion.div>
      </main>
    </div>
  );
}

export default App;