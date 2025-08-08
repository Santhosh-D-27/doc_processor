import React from 'react';
import { motion } from 'framer-motion';

const DocumentRow = ({ doc, index, expandedRow, handleRowClick, formatStatus, formatRoutingDestination }) => {
  const isExpanded = expandedRow?.id === doc.document_id;

  const rowVariants = {
    hidden: { 
      opacity: 0, 
      y: -20,
      scale: 0.95
    },
    visible: { 
      opacity: 1, 
      y: 0,
      scale: 1,
      transition: {
        type: "spring",
        stiffness: 300,
        damping: 30,
        delay: index * 0.05
      }
    },
    exit: { 
      opacity: 0,
      y: -20,
      scale: 0.95,
      transition: { duration: 0.2 }
    }
  };

  const getFileIcon = (filename) => {
    if (!filename) return '📄';
    const ext = filename.toLowerCase().split('.').pop();
    const iconMap = {
      'pdf': '📕',
      'docx': '📘',
      'doc': '📘',
      'txt': '📄',
      'jpg': '🖼️',
      'jpeg': '🖼️',
      'png': '🖼️',
      'gif': '🖼️'
    };
    return iconMap[ext] || '📄';
  };

  const getTypeColor = (docType) => {
    const colorMap = {
      'INVOICE': 'text-green-400',
      'RESUME': 'text-blue-400',
      'CONTRACT': 'text-purple-400',
      'REPORT': 'text-yellow-400',
      'MEMO': 'text-orange-400',
      'AGREEMENT': 'text-red-400',
      'GRIEVANCE': 'text-pink-400',
      'ID_PROOF': 'text-cyan-400',
      'HUMAN_REVIEW_NEEDED': 'text-gray-400',
    };
    return colorMap[docType] || 'text-slate-400';
  };

  const formatStatusWithModernStyle = (status) => {
    const statusConfig = {
      'Ingested': { 
        class: 'status-ingested status-badge', 
      },
      'Extracted': { 
        class: 'status-extracted status-badge', 
      },
      'Classified': { 
        class: 'status-classified status-badge', 
      },
      'Routed': { 
        class: 'status-routed status-badge', 
      },
      'Failed': { 
        class: 'status-failed status-badge', 
      },
      'Processing': { 
        class: 'status-processing status-badge',  
      }
    };

    let config = statusConfig['Processing']; // Default
    
    if (status?.startsWith('Re-')) {
      config = statusConfig['Processing'];
    } else if (status?.includes('Failed')) {
      config = statusConfig['Failed'];
    } else {
      config = statusConfig[status] || statusConfig['Processing'];
    }

    return (
      <span className={config.class}>
        <span className="mr-1">{config.icon}</span>
        {status || 'Unknown'}
      </span>
    );
  };

  return (
    <motion.tr
      variants={rowVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className={`border-b border-slate-700/30 cursor-pointer transition-all duration-300 ${
        isExpanded 
          ? 'bg-gradient-to-r from-cyan-500/10 to-purple-500/10 shadow-lg' 
          : 'hover:bg-gradient-to-r hover:from-slate-800/50 hover:to-slate-700/50'
      }`}
      onClick={() => handleRowClick(doc.document_id)}
      whileHover={{ 
        backgroundColor: isExpanded ? undefined : 'rgba(30, 41, 59, 0.3)',
        transition: { duration: 0.2 }
      }}
      layout
    >
      <td className="py-4 px-6">
        <motion.div 
          className="flex items-center space-x-3"
          whileHover={{ x: 2 }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        >
          <motion.span 
            className="text-2xl flex-shrink-0"
            whileHover={{ scale: 1.2, rotate: 5 }}
            transition={{ type: "spring", stiffness: 400 }}
          >
            {getFileIcon(doc.filename)}
          </motion.span>
          <div className="min-w-0 flex-1">
            <div 
              className="font-mono text-sm font-semibold text-slate-200 truncate hover:text-cyan-300 transition-colors" 
              title={doc.filename}
            >
              {doc.filename || 'N/A'}
            </div>
            {doc.filename && (
              <div className="text-xs text-slate-500 mt-1">
                {(doc.filename.split('.').pop() || '').toUpperCase()}
              </div>
            )}
          </div>
        </motion.div>
      </td>

      <td className="py-4 px-6">
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.05 + 0.1 }}
        >
          {doc.doc_type ? (
            <span className={`font-semibold ${getTypeColor(doc.doc_type)} text-sm`}>
              {doc.doc_type}
            </span>
          ) : (
            <span className="text-slate-500 text-sm">Unknown</span>
          )}
          {doc.confidence >0 && (
            <div className="flex items-center mt-1">
              <div className="w-12 h-1 bg-slate-700 rounded-full overflow-hidden">
                <motion.div
                  className={`h-full rounded-full ${
                    doc.confidence > 0.8 ? 'bg-green-500' :
                    doc.confidence > 0.6 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  initial={{ width: 0 }}
                  animate={{ width: `${doc.confidence * 100}%` }}
                  transition={{ delay: index * 0.05 + 0.3, duration: 0.6 }}
                />
              </div>
              <span className="text-xs text-slate-400 ml-2">
                {(doc.confidence * 100).toFixed(0)}%
              </span>
            </div>
          )}
        </motion.div>
      </td>

      <td className="py-4 px-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: index * 0.05 + 0.2 }}
        >
          {formatStatusWithModernStyle(doc.status)}
          
          {doc.override_in_progress >0 && (
            <motion.div 
              className="mt-2"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-purple-500/20 to-pink-500/20 text-purple-300 border border-purple-500/30">
                <motion.svg 
                  className="w-3 h-3 mr-1" 
                  fill="none" 
                  viewBox="0 0 24 24"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </motion.svg>
                {doc.override_type === 're-classify' ? 'Re-classifying' : 
                 doc.override_type === 're-extract' ? 'Re-extracting' : 
                 doc.override_type === 're-route' ? 'Re-routing' : 'Processing'}
              </span>
            </motion.div>
          )}
        </motion.div>
      </td>

      <td className="py-4 px-6">
        <motion.div
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.05 + 0.25 }}
        >
          {doc.routing_destination ? (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-blue-500/20 to-cyan-500/20 text-blue-300 border border-blue-500/30">
              
              {formatRoutingDestination(doc.routing_destination)}
            </span>
          ) : (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-slate-500/20 to-slate-600/20 text-slate-400 border border-slate-500/30">
              <span className="mr-1">⏳</span>
              Not routed
            </span>
          )}
        </motion.div>
      </td>

      <td className="py-4 px-6 text-sm">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: index * 0.05 + 0.3 }}
          className="text-slate-400"
        >
          <div className="font-mono text-xs">
            {doc.last_updated ? (
              <>
                <div>{new Date(doc.last_updated).toLocaleDateString()}</div>
                <div className="text-slate-500">
                  {new Date(doc.last_updated).toLocaleTimeString()}
                </div>
              </>
            ) : (
              'N/A'
            )}
          </div>
        </motion.div>
      </td>
    </motion.tr>
  );
};

export default React.memo(DocumentRow);