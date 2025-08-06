import React from 'react';
import { motion } from 'framer-motion';
import ProgressBar from './ProgressBar';

const MobileCard = ({ doc, expandedRow, handleRowClick, handleManualAction, formatStatus, formatRoutingDestination, setExpandedRow }) => {
    const isExpanded = expandedRow?.id === doc.document_id;

    return (
        <motion.div
            key={doc.document_id}
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={`bg-gray-700/30 rounded-lg p-4 cursor-pointer transition-colors ${
            isExpanded ? 'ring-2 ring-teal-500' : 'hover:bg-gray-700/50'
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
            {isExpanded && (
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
                        <div className="relative">
                        <button
                            onClick={(e) => {
                            e.stopPropagation();
                            setExpandedRow(prev => ({ ...prev, showRouteOptions: prev.showRouteOptions === doc.document_id ? null : doc.document_id }));
                            }}
                            className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded-lg transition-colors"
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
                </motion.div>
            )}
        </motion.div>
    );
};

export default React.memo(MobileCard);