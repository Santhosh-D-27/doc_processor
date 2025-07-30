// In web_ui/frontend/src/components/ProgressBar.jsx

import React from 'react';
import { motion } from 'framer-motion';

const ProgressBar = ({ history = [] }) => {
  const stages = [
    { name: 'Ingested', color: 'bg-gray-500', textColor: 'text-gray-300' },
    { name: 'Extracted', color: 'bg-yellow-500', textColor: 'text-yellow-300' },
    { name: 'Classified', color: 'bg-purple-500', textColor: 'text-purple-300' },
    { name: 'Routed', color: 'bg-green-500', textColor: 'text-green-300' }
  ];

  const getCurrentStage = () => {
    if (!history || history.length === 0) return -1;
    
    const latestStatus = history[history.length - 1]?.status;
    
    if (!latestStatus) return -1;
    
    if (latestStatus.includes('Failed') || latestStatus.includes('Error')) {
      return stages.findIndex(stage => latestStatus.includes(stage.name)) || -1;
    }
    
    return stages.findIndex(stage => stage.name === latestStatus);
  };

  const currentStage = getCurrentStage();
  const latestUpdate = history && history.length > 0 ? history[history.length - 1] : null;
  const hasError = latestUpdate?.status?.includes('Failed') || latestUpdate?.status?.includes('Error');

  return (
    <div className="w-full">
      <div className="mb-4">
        <h4 className="text-lg font-semibold text-gray-200 mb-2">Processing Pipeline</h4>
        <div className="flex items-center justify-between mb-3">
          {stages.map((stage, index) => (
            <div key={stage.name} className="flex items-center">
              <div className="flex flex-col items-center">
                <motion.div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                    index <= currentStage
                      ? hasError && index === currentStage
                        ? 'bg-red-500 text-white'
                        : `${stage.color} text-white`
                      : 'bg-gray-700 text-gray-400'
                  }`}
                  initial={{ scale: 0.8 }}
                  animate={{ 
                    scale: index === currentStage ? 1.1 : 1,
                    transition: { duration: 0.3 }
                  }}
                >
                  {index <= currentStage ? (
                    hasError && index === currentStage ? (
                      '✕'
                    ) : (
                      '✓'
                    )
                  ) : (
                    index + 1
                  )}
                </motion.div>
                <span className={`text-xs mt-1 ${
                  index <= currentStage ? stage.textColor : 'text-gray-500'
                }`}>
                  {stage.name}
                </span>
              </div>
              {index < stages.length - 1 && (
                <div className={`flex-1 h-0.5 mx-2 ${
                  index < currentStage ? stage.color : 'bg-gray-700'
                }`} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-gray-700 rounded-full h-2 mb-4">
        <motion.div
          className={`h-2 rounded-full ${
            hasError ? 'bg-red-500' : 'bg-gradient-to-r from-teal-500 to-green-500'
          }`}
          initial={{ width: 0 }}
          animate={{ 
            width: `${Math.max(0, ((currentStage + 1) / stages.length) * 100)}%` 
          }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>

      {/* Timeline */}
      <div className="bg-gray-800 rounded-lg p-4">
        <h5 className="text-sm font-semibold text-gray-300 mb-3">Processing History</h5>
        <div className="space-y-2 max-h-40 overflow-y-auto">
          {history && history.length > 0 ? (
            history.map((event, index) => (
              <motion.div
                key={index}
                className="flex items-center justify-between text-xs p-2 bg-gray-700 rounded"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.1 }}
              >
                <div className="flex items-center space-x-2">
                  <div className={`w-2 h-2 rounded-full ${
                    event.status?.includes('Failed') ? 'bg-red-500' : 'bg-teal-500'
                  }`} />
                  <span className="text-gray-300">{event.status || 'Unknown Status'}</span>
                </div>
                <span className="text-gray-500">
                  {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : 
                   event.last_updated ? new Date(event.last_updated).toLocaleTimeString() : 
                   'Unknown Time'}
                </span>
              </motion.div>
            ))
          ) : (
            <div className="text-gray-500 text-center py-2">No history available</div>
          )}
        </div>
      </div>

      {/* Additional Info */}
      {latestUpdate && (
        <div className="mt-4 p-3 bg-gray-800 rounded-lg">
          <div className="grid grid-cols-2 gap-4 text-xs">
            {latestUpdate.doc_type && (
              <div>
                <span className="text-gray-400">Type:</span>
                <span className="text-gray-200 ml-2">{latestUpdate.doc_type}</span>
              </div>
            )}
            {latestUpdate.confidence !== undefined && latestUpdate.confidence !== null && (
              <div>
                <span className="text-gray-400">Confidence:</span>
                <span className={`ml-2 ${
                  latestUpdate.confidence > 0.8 ? 'text-green-400' :
                  latestUpdate.confidence > 0.6 ? 'text-yellow-400' : 'text-red-400'
                }`}>
                  {latestUpdate.confidence.toFixed(2)}
                </span>
              </div>
            )}
            {latestUpdate.is_vip && (
              <div>
                <span className="text-gray-400">VIP Level:</span>
                <span className={`ml-2 ${
                  latestUpdate.vip_level?.toLowerCase() === 'high' ? 'text-red-400' :
                  latestUpdate.vip_level?.toLowerCase() === 'medium' ? 'text-orange-400' :
                  'text-teal-400'
                }`}>
                  {latestUpdate.vip_level || 'Low'}
                </span>
              </div>
            )}
            {latestUpdate.summary && (
              <div className="col-span-2">
                <span className="text-gray-400">Summary:</span>
                <p className="text-gray-200 mt-1 text-sm">{latestUpdate.summary}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProgressBar;