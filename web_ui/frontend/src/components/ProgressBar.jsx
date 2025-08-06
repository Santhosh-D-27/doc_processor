import React, { useState } from 'react';
import { motion } from 'framer-motion';

const ProgressBar = ({ history = [] }) => {
  const [hoveredStage, setHoveredStage] = useState(null);
  
  const safeHistory = Array.isArray(history) ? history : [];
  
  const stages = [
    { name: 'Ingested', color: 'bg-gray-500', textColor: 'text-gray-300', icon: '📥' },
    { name: 'Extracted', color: 'bg-yellow-500', textColor: 'text-yellow-300', icon: '🔍' },
    { name: 'Classified', color: 'bg-purple-500', textColor: 'text-purple-300', icon: '🏷️' },
    { name: 'Routed', color: 'bg-green-500', textColor: 'text-green-300', icon: '✅' }
  ];

  const getCurrentStage = () => {
    if (!safeHistory || safeHistory.length === 0) return -1;
    const latestStatus = safeHistory[safeHistory.length - 1]?.status;
    if (!latestStatus) return -1;
    
    if (latestStatus.includes('Failed') || latestStatus.includes('Error')) {
      return stages.findIndex(stage => latestStatus.includes(stage.name)) || -1;
    }
    
    return stages.findIndex(stage => stage.name === latestStatus);
  };

  const getStageDetails = (stageName) => {
    const stageEvents = safeHistory.filter(event => event && event.status === stageName);
    if (stageEvents.length === 0) return null;
    
    const latestEvent = stageEvents[stageEvents.length - 1];
    const details = [];
    
    if (latestEvent.timestamp) {
      const time = new Date(latestEvent.timestamp).toLocaleTimeString();
      details.push(`Completed at ${time}`);
    }
    
    if (stageName === 'Classified' && latestEvent.doc_type && latestEvent.confidence) {
      details.push(`Type: ${latestEvent.doc_type} (${(latestEvent.confidence * 100).toFixed(0)}% confidence)`);
    }
    
    if (stageName === 'Extracted') {
      details.push('OCR and text extraction completed');
    }
    
    if (stageName === 'Routed') {
      const routingEvent = stageEvents.find(event => event.details && event.details.destination);
      if (routingEvent && routingEvent.details) {
        const destination = routingEvent.details.destination;
        details.push(`Routed to ${destination.replace('_', ' ').toUpperCase()}`);
      } else {
        details.push('Document routed successfully');
      }
    }
    
    return details.join(', ');
  };

  const currentStage = getCurrentStage();
  const latestUpdate = safeHistory && safeHistory.length > 0 ? safeHistory[safeHistory.length - 1] : null;
  const hasError = latestUpdate?.status?.includes('Failed') || latestUpdate?.status?.includes('Error');
  const isProcessing = currentStage >= 0 && currentStage < 3; // Still processing if not fully routed

  return (
    <div className="w-full">
      {/* Processing Pipeline Header */}
      <div className="mb-6">
        <h4 className="text-lg font-semibold text-gray-200 mb-4">Processing Pipeline</h4>
        
        {/* Pipeline Visualization */}
        <div className="flex items-center justify-between mb-4">
          {stages.map((stage, index) => {
            const stageDetails = getStageDetails(stage.name);
            const isCompleted = index <= currentStage;
            const isActive = index === currentStage && isProcessing;
            
            return (
              <div key={stage.name} className="flex items-center flex-1">
                <div className="flex flex-col items-center min-w-0 relative">
                  {/* Stage Icon with Blinking Animation */}
                  <motion.div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold cursor-pointer transition-all duration-300 ${
                      isCompleted
                        ? hasError && index === currentStage
                          ? 'bg-red-500 text-white shadow-lg shadow-red-500/30'
                          : `${stage.color} text-white shadow-lg`
                        : 'bg-gray-700 text-gray-400'
                    }`}
                    animate={isActive ? {
                      scale: [1, 1.1, 1],
                      boxShadow: [
                        '0 0 0 0 rgba(59, 130, 246, 0.7)',
                        '0 0 0 8px rgba(59, 130, 246, 0)',
                        '0 0 0 0 rgba(59, 130, 246, 0.7)'
                      ]
                    } : { scale: 1 }}
                    transition={isActive ? {
                      duration: 2,
                      repeat: Infinity,
                      ease: "easeInOut"
                    } : { duration: 0.3 }}
                    onMouseEnter={() => setHoveredStage(stage.name)}
                    onMouseLeave={() => setHoveredStage(null)}
                    style={{
                      filter: isActive ? 'brightness(1.2)' : 'brightness(1)'
                    }}
                  >
                    <span className="text-lg">{stage.icon}</span>
                  </motion.div>
                  
                  {/* Hover Tooltip */}
                  {hoveredStage === stage.name && stageDetails && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 10 }}
                      className="absolute bottom-full mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-lg z-10 whitespace-nowrap max-w-xs"
                      style={{ left: '50%', transform: 'translateX(-50%)' }}
                    >
                      {stageDetails}
                      <div className="absolute top-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>
                    </motion.div>
                  )}
                  
                  {/* Stage Label */}
                  <span className={`text-xs mt-2 text-center font-medium ${
                    isCompleted ? stage.textColor : 'text-gray-500'
                  }`}>
                    {stage.name}
                  </span>
                </div>
                
                {/* Connecting Line */}
                {index < stages.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-3 transition-all duration-500 ${
                    index < currentStage 
                      ? 'bg-gradient-to-r from-cyan-500 to-green-500' 
                      : 'bg-gray-700'
                  }`} />
                )}
              </div>
            );
          })}
        </div>
        
        {/* Progress Bar */}
        <div className="w-full bg-gray-700 rounded-full h-2 mb-4 overflow-hidden">
          <motion.div
            className={`h-2 rounded-full ${
              hasError 
                ? 'bg-gradient-to-r from-red-500 to-red-600' 
                : 'bg-gradient-to-r from-cyan-500 to-green-500'
            }`}
            initial={{ width: 0 }}
            animate={{ 
              width: `${Math.max(0, ((currentStage + 1) / stages.length) * 100)}%` 
            }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </div>
      </div>

      {/* Processing History */}
      <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700/50">
        <h5 className="text-base font-semibold text-gray-300 mb-3 flex items-center">
          <span className="text-lg mr-2">📋</span>
          Processing History
        </h5>
        <div className="space-y-2 max-h-32 overflow-y-auto custom-scrollbar">
          {safeHistory && safeHistory.length > 0 ? (
            [...safeHistory].reverse().filter(event => event && event.status).map((event, index) => (
              <motion.div
                key={index}
                className="flex items-center justify-between text-sm p-2 bg-gray-700/50 rounded-lg hover:bg-gray-700/70 transition-colors"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05, duration: 0.3 }}
              >
                <div className="flex items-center space-x-2 min-w-0 flex-1">
                  <div className={`w-2 h-2 rounded-full ${
                    event.status?.includes('Failed') ? 'bg-red-400' : 'bg-cyan-400'
                  }`} />
                  <span className="text-gray-300 truncate font-medium">
                    {event.status || 'Unknown Status'}
                  </span>
                </div>
                <span className="text-gray-500 text-sm flex-shrink-0 ml-2 font-mono">
                  {(() => {
                    const timeValue = event.timestamp || event.last_updated || event.created_at || event.updated_at || event.time;
                    if (!timeValue) return '--:--';
                    
                    try {
                      const date = new Date(timeValue);
                      return isNaN(date.getTime()) ? '--:--' : date.toLocaleTimeString('en-US', {
                        hour12: false,
                        hour: '2-digit',
                        minute: '2-digit'
                      });
                    } catch (error) {
                      return '--:--';
                    }
                  })()}
                </span>
              </motion.div>
            ))
          ) : (
            <div className="text-gray-500 text-center py-4 text-base">
              <span className="text-2xl block mb-2">📄</span>
              No processing history available
            </div>
          )}
        </div>
      </div>

      {/* Document Details */}
      {latestUpdate && (latestUpdate.doc_type || latestUpdate.confidence || latestUpdate.summary) && (
        <motion.div 
          className="mt-4 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <h5 className="text-base font-semibold text-gray-300 mb-3 flex items-center">
            <span className="text-lg mr-2">ℹ️</span>
            Document Information
          </h5>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            {latestUpdate.doc_type && (
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Document Type:</span>
                <span className="text-cyan-300 font-semibold">
                  {latestUpdate.doc_type}
                </span>
              </div>
            )}
            {latestUpdate.confidence !== undefined && latestUpdate.confidence !== null && (
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Confidence:</span>
                <div className="flex items-center space-x-2">
                  <div className={`w-2 h-2 rounded-full ${
                    latestUpdate.confidence > 0.8 ? 'bg-green-400' :
                    latestUpdate.confidence > 0.6 ? 'bg-yellow-400' : 'bg-red-400'
                  }`} />
                  <span className={`font-semibold ${
                    latestUpdate.confidence > 0.8 ? 'text-green-400' :
                    latestUpdate.confidence > 0.6 ? 'text-yellow-400' : 'text-red-400'
                  }`}>
                    {(latestUpdate.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )}
          </div>
          
          {latestUpdate.summary && (
            <div className="mt-3 pt-3 border-t border-gray-700/50">
              <span className="text-gray-400 text-base block mb-2">Summary:</span>
              <p className="text-gray-300 text-base leading-relaxed bg-gray-700/30 p-2 rounded">
                {latestUpdate.summary}
              </p>
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
};

export default ProgressBar;