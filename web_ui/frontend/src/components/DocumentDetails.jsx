import React from 'react';
import { motion } from 'framer-motion';
import ProgressBar from './ProgressBar';

const DocumentDetails = ({ doc, expandedRow, handleManualAction, setExpandedRow }) => {
  return (
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
            <div className="relative">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setExpandedRow(prev => ({ ...prev, showRouteOptions: prev.showRouteOptions === doc.document_id ? null : doc.document_id }));
                }}
                className="action-button bg-blue-600 hover:bg-blue-500 text-white"
              >
                Re-route
              </button>
              {expandedRow?.showRouteOptions === doc.document_id && (
                <div className="absolute right-0 mt-2 w-48 bg-gray-800 rounded-md shadow-lg z-10">
                  <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'crm_system')} className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700">CRM</button>
                  <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'erp_system')} className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700">ERP</button>
                  <button onClick={(e) => handleManualAction('re-route', doc.document_id, e, 'dms_system')} className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700">DMS</button>
                </div>
              )}
            </div>
          </div>
        </div>
      </td>
    </motion.tr>
  );
};

export default React.memo(DocumentDetails);