import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import DocumentRow from './DocumentRow';
import DocumentDetails from './DocumentDetails';
import MobileCard from './MobileCard';

const DocumentTable = ({ 
  documents, 
  expandedRow, 
  handleRowClick, 
  handleManualAction, 
  formatStatus, 
  formatRoutingDestination,
  setExpandedRow
}) => {
  const NoDocuments = () => (
    <motion.div 
      className="flex flex-col items-center justify-center py-16 px-8 text-center"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.6 }}
    >
      <motion.div 
        className="relative mb-6"
        animate={{ y: [0, -10, 0] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      >
        <div className="w-24 h-24 rounded-full glass-card flex items-center justify-center mx-auto">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
          >
            <span className="text-4xl">📚</span>
          </motion.div>
        </div>
        <motion.div
          className="absolute -inset-4 bg-gradient-to-r from-cyan-500/20 to-purple-500/20 rounded-full blur-xl"
          animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0.8, 0.5] }}
          transition={{ duration: 3, repeat: Infinity }}
        />
      </motion.div>
      
      <motion.h3 
        className="text-2xl font-bold text-slate-200 mb-3"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        No Documents Yet
      </motion.h3>
      
      <motion.p 
        className="text-slate-400 mb-6 max-w-md"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        Start your document processing journey! Upload files or connect your Gmail accounts to begin.
      </motion.p>
      
      <motion.div 
        className="flex flex-col sm:flex-row gap-4"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <div className="glass-card rounded-xl p-4 text-center">
          <div className="text-2xl mb-2">📁</div>
          <div className="text-sm text-slate-300 font-medium">Upload Documents</div>
          <div className="text-xs text-slate-500 mt-1">Drag & drop files above</div>
        </div>
        <div className="glass-card rounded-xl p-4 text-center">
          <div className="text-2xl mb-2">📧</div>
          <div className="text-sm text-slate-300 font-medium">Connect Gmail</div>
          <div className="text-xs text-slate-500 mt-1">Auto-process emails</div>
        </div>
      </motion.div>
    </motion.div>
  );

  const tableVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.05
      }
    }
  };

  return (
    <motion.div
      className="glass-card-strong rounded-2xl shadow-modern-lg overflow-hidden"
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      {/* Desktop Table View */}
      <div className="hidden lg:block overflow-x-auto">
        {documents.length === 0 ? (
          <NoDocuments />
        ) : (
          <table className="modern-table w-full">
            <motion.thead 
              className="sticky top-0 z-10"
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
            >
              <tr>
                <th className="text-left font-bold text-slate-200 py-4 px-6" style={{ minWidth: '250px', width: '30%' }}>
                  <div className="flex items-center space-x-2">
                    <span>📄</span>
                    <span>Document Name</span>
                  </div>
                </th>
                <th className="text-left font-bold text-slate-200 py-4 px-6" style={{ minWidth: '150px', width: '20%' }}>
                  <div className="flex items-center space-x-2">
                    <span>🏷️</span>
                    <span>Type</span>
                  </div>
                </th>
                <th className="text-left font-bold text-slate-200 py-4 px-6" style={{ minWidth: '150px', width: '20%' }}>
                  <div className="flex items-center space-x-2">
                    <span>⚡</span>
                    <span>Status</span>
                  </div>
                </th>
                <th className="text-left font-bold text-slate-200 py-4 px-6" style={{ minWidth: '150px', width: '15%' }}>
                  <div className="flex items-center space-x-2">
                    <span>🎯</span>
                    <span>Routed To</span>
                  </div>
                </th>
                <th className="text-left font-bold text-slate-200 py-4 px-6" style={{ minWidth: '150px', width: '15%' }}>
                  <div className="flex items-center space-x-2">
                    <span>🕐</span>
                    <span>Last Updated</span>
                  </div>
                </th>
              </tr>
            </motion.thead>
            <motion.tbody
              variants={tableVariants}
              initial="hidden"
              animate="visible"
            >
              <AnimatePresence>
                {documents
                  .filter(doc => doc && doc.document_id)
                  .map((doc, index) => (
                    <React.Fragment key={doc.document_id}>
                      <DocumentRow 
                        doc={doc}
                        index={index}
                        expandedRow={expandedRow}
                        handleRowClick={handleRowClick}
                        formatStatus={formatStatus}
                        formatRoutingDestination={formatRoutingDestination}
                      />
                      {expandedRow && expandedRow.id === doc.document_id && (
                        <DocumentDetails 
                          doc={doc}
                          expandedRow={expandedRow}
                          handleManualAction={handleManualAction}
                          setExpandedRow={setExpandedRow}
                        />
                      )}
                    </React.Fragment>
                  ))
                }
              </AnimatePresence>
            </motion.tbody>
          </table>
        )}
      </div>

      {/* Mobile Card View */}
      <div className="lg:hidden">
        <AnimatePresence>
          {documents.length === 0 ? (
            <NoDocuments />
          ) : (
            <motion.div 
              className="space-y-4 p-4"
              variants={tableVariants}
              initial="hidden"
              animate="visible"
            >
              {documents
                .filter(doc => doc && doc.document_id)
                .map((doc, index) => (
                  <MobileCard 
                    key={doc.document_id}
                    doc={doc}
                    index={index}
                    expandedRow={expandedRow}
                    handleRowClick={handleRowClick}
                    handleManualAction={handleManualAction}
                    formatStatus={formatStatus}
                    formatRoutingDestination={formatRoutingDestination}
                    setExpandedRow={setExpandedRow}
                  />
                ))
              }
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Footer with Statistics */}
      {documents.length > 0 && (
        <motion.div 
          className="border-t border-slate-700/50 px-6 py-4 bg-gradient-to-r from-slate-800/50 to-slate-700/50"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
        >
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
            <div className="flex items-center space-x-6 text-sm text-slate-400">
              <span className="flex items-center space-x-2">
                <span className="w-2 h-2 bg-gradient-to-r from-cyan-500 to-blue-500 rounded-full"></span>
                <span>Total: {documents.length}</span>
              </span>
              <span className="flex items-center space-x-2">
                <span className="w-2 h-2 bg-gradient-to-r from-green-500 to-emerald-500 rounded-full"></span>
                <span>Processed: {documents.filter(d => d.status === 'Routed').length}</span>
              </span>
              <span className="flex items-center space-x-2">
                <span className="w-2 h-2 bg-gradient-to-r from-yellow-500 to-orange-500 rounded-full animate-pulse"></span>
                <span>Processing: {documents.filter(d => d.override_in_progress || d.status?.includes('ing')).length}</span>
              </span>
            </div>
            <div className="text-xs text-slate-500">
              Last refresh: {new Date().toLocaleTimeString()}
            </div>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
};

export default DocumentTable;