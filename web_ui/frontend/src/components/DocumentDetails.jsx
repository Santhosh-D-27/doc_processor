// frontend/src/components/DocumentDetails.jsx

import React from 'react';
import { motion } from 'framer-motion';
import ProgressBar from './ProgressBar';

// Helper function to format timestamps
const formatHistoryTime = (event) => {
  const timeValue = event.timestamp || event.last_updated || event.created_at;
  if (!timeValue) return '--:--';
  try {
    const date = new Date(timeValue);
    return isNaN(date.getTime()) ? '--:--' : date.toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit'
    });
  } catch (error) { return '--:--'; }
};

const DocumentDetails = ({ doc, expandedRow, handleManualAction, setExpandedRow }) => {
  const history = Array.isArray(expandedRow.history) ? expandedRow.history : [];
  const latestUpdate = history.length > 0 ? history[history.length - 1] : doc;

  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="bg-slate-800/20"
    >
      <td colSpan="5" className="p-0">
        <div className="p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-3 gap-6 border-t-2 border-slate-700">
          
          {/* Progress Bar (Spans all 3 columns) */}
          <div className="lg:col-span-3">
            <ProgressBar history={history} />
          </div>

          {/* TOP ROW: Processing History (Spans 2 of 3 columns) */}
          <div className="lg:col-span-2">
            <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-700/50 h-full">
              <h5 className="text-base font-semibold text-slate-300 mb-3 flex items-center">
                <span className="text-lg mr-2">📋</span>
                Processing History
              </h5>
              <div className="space-y-2 max-h-48 overflow-y-auto custom-scrollbar">
                {history.length > 0 ? (
                  [...history].reverse().map((event, index) => (
                    <div key={index} className="flex items-center justify-between text-sm p-2 bg-slate-700/40 rounded-lg">
                      <div className="flex items-center space-x-2 min-w-0">
                        <div className={`w-2 h-2 rounded-full ${event.status?.includes('Failed') ? 'bg-red-400' : 'bg-cyan-400'}`} />
                        <span className="text-slate-300 truncate font-medium">{event.status}</span>
                      </div>
                      <span className="text-slate-500 text-xs font-mono ml-2">{formatHistoryTime(event)}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-slate-500 text-center py-4">No history available.</div>
                )}
              </div>
            </div>
          </div>

          {/* TOP ROW: Manual Actions (Spans 1 of 3 columns) */}
          <div className="lg:col-span-1">
            <div className="flex flex-col gap-5 p-4 bg-slate-900/50 rounded-xl border border-slate-700/50 h-full">
              <h5 className="text-base font-semibold text-slate-300 mb-1">Manual Actions</h5>
              <motion.button
                onClick={(e) => handleManualAction('re-extract', doc.document_id, e)}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white text-sm font-medium rounded-lg shadow-lg disabled:opacity-50"
                disabled={doc.status === 'Ingestion Failed'}
              >
                <span>Re-extract</span>
              </motion.button>
              <motion.button
                onClick={(e) => handleManualAction('re-classify', doc.document_id, e)}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-sky-500 to-sky-600 hover:from-sky-600 hover:to-sky-700 text-white text-sm font-medium rounded-lg shadow-lg disabled:opacity-50"
                disabled={doc.status === 'Extraction Failed'}
              >
                <span>Re-classify</span>
              </motion.button>
              <div className="relative w-full">
                <motion.button
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpandedRow(prev => ({ ...prev, showRouteOptions: prev.showRouteOptions === doc.document_id ? null : doc.document_id }));
                  }}
                  className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white text-sm font-medium rounded-lg shadow-lg w-full"
                >
                  <span>Re-route</span>
                </motion.button>
                {expandedRow?.showRouteOptions === doc.document_id && (
                  <motion.div 
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute bottom-full mb-2 w-full bg-slate-800 rounded-md shadow-lg z-20 border border-slate-700">
                    <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'crm_system')} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded-t-md">CRM</button>
                    <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'erp_system')} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700">ERP</button>
                    <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'dms_system')} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded-b-md">DMS</button>
                  </motion.div>
                )}
              </div>
            </div>
          </div>

          {/* BOTTOM ROW: Document Information (Spans all 3 columns) */}
          {(latestUpdate.doc_type || latestUpdate.summary) && (
            <div className="lg:col-span-3">
              <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-700/50">
                <h5 className="text-base font-semibold text-slate-300 mb-3 flex items-center">
                  <span className="text-lg mr-2">ℹ️</span>
                  Document Information
                </h5>
                <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm">
                    <span className="text-slate-400">Document Type:</span>
                    <span className="text-cyan-300 font-semibold">{latestUpdate.doc_type || 'N/A'}</span>
                  </div>
                  {latestUpdate.summary && (
                    <div>
                      <span className="text-slate-400 text-sm block mb-1">Summary:</span>
                      <p className="text-slate-300 text-sm leading-relaxed bg-slate-700/30 p-3 rounded-md">
                        {latestUpdate.summary}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

        </div>
      </td>
    </motion.tr>
  );
};

export default React.memo(DocumentDetails);