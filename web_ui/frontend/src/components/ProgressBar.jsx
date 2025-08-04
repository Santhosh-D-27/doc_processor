// In web_ui/frontend/src/components/ProgressBar.jsx

import React, { useState } from 'react';
import { motion } from 'framer-motion';

const ProgressBar = ({ history = [] }) => {
  const [hoveredStage, setHoveredStage] = useState(null);
  
  // Ensure history is always an array
  const safeHistory = Array.isArray(history) ? history : [];
  
  const stages = [
    { name: 'Ingested', color: 'bg-gray-500', textColor: 'text-gray-300' },
    { name: 'Extracted', color: 'bg-yellow-500', textColor: 'text-yellow-300' },
    { name: 'Classified', color: 'bg-purple-500', textColor: 'text-purple-300' },
    { name: 'Routed', color: 'bg-green-500', textColor: 'text-green-300' }
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
    
    // Add timing information if available
    if (latestEvent.timestamp) {
      const time = new Date(latestEvent.timestamp).toLocaleTimeString();
      details.push(`Completed at ${time}`);
    }
    
    // Add processing time if we have multiple events for this stage
    if (stageEvents.length > 1) {
      const firstEvent = stageEvents[0];
      const lastEvent = stageEvents[stageEvents.length - 1];
      if (firstEvent.timestamp && lastEvent.timestamp) {
        const startTime = new Date(firstEvent.timestamp).getTime();
        const endTime = new Date(lastEvent.timestamp).getTime();
        const duration = ((endTime - startTime) / 1000).toFixed(1);
        details.push(`Processing took ${duration}s`);
      }
    }
    
    // Add type and confidence for classification stage
    if (stageName === 'Classified' && latestEvent.doc_type && latestEvent.confidence) {
      details.push(`Type=${latestEvent.doc_type} (${(latestEvent.confidence * 100).toFixed(0)}% confidence)`);
    }
    
    // Add extraction details
    if (stageName === 'Extracted') {
      details.push('OCR and text extraction completed');
    }
    
    // Add routing details
    if (stageName === 'Routed') {
      const routingEvent = stageEvents.find(event => event.details && event.details.destination);
      if (routingEvent && routingEvent.details) {
        const destination = routingEvent.details.destination;
        details.push(`Document routed to ${destination.replace('_', ' ').toUpperCase()}`);
      } else {
        details.push('Document routed to appropriate system');
      }
    }
    
    return details.join(', ');
  };

  const currentStage = getCurrentStage();
  const latestUpdate = safeHistory && safeHistory.length > 0 ? safeHistory[safeHistory.length - 1] : null;
  const hasError = latestUpdate?.status?.includes('Failed') || latestUpdate?.status?.includes('Error');

  return (
    <div className="w-full">
      <div className="mb-3 sm:mb-4">
        <h4 className="text-base sm:text-lg font-semibold text-gray-200 mb-2">Processing Pipeline</h4>
        <div className="flex items-center justify-between mb-2 sm:mb-3">
          {stages.map((stage, index) => {
            const stageDetails = getStageDetails(stage.name);
            const isCompleted = index <= currentStage;
            
            return (
              <div key={stage.name} className="flex items-center flex-1">
                <div className="flex flex-col items-center min-w-0 relative">
                  <motion.div
                    className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-xs sm:text-sm font-bold cursor-pointer transition-all ${
                      isCompleted
                        ? hasError && index === currentStage
                          ? 'bg-red-500 text-white'
                          : `${stage.color} text-white`
                        : 'bg-gray-700 text-gray-400'
                    } ${stageDetails ? 'hover:scale-110' : ''}`}
                    initial={{ scale: 0.8 }}
                    animate={{ 
                      scale: index === currentStage ? 1.1 : 1,
                      transition: { duration: 0.3 }
                    }}
                    onMouseEnter={() => setHoveredStage(stage.name)}
                    onMouseLeave={() => setHoveredStage(null)}
                  >
                    {isCompleted ? (
                      hasError && index === currentStage ? (
                        '✕'
                      ) : (
                        '✓'
                      )
                    ) : (
                      index + 1
                    )}
                  </motion.div>
                  
                  {/* Hover Tooltip */}
                  {hoveredStage === stage.name && stageDetails && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 10 }}
                      className="absolute bottom-full mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-lg z-10 whitespace-nowrap"
                      style={{ left: '50%', transform: 'translateX(-50%)' }}
                    >
                      {stageDetails}
                      <div className="absolute top-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>
                    </motion.div>
                  )}
                  
                  <span className={`text-xs mt-1 text-center ${
                    isCompleted ? stage.textColor : 'text-gray-500'
                  }`}>
                    {stage.name}
                  </span>
                </div>
                {index < stages.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-1 sm:mx-2 ${
                    index < currentStage ? stage.color : 'bg-gray-700'
                  }`} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-gray-700 rounded-full h-2 mb-3 sm:mb-4">
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
      <div className="bg-gray-800 rounded-lg p-3 sm:p-4">
        <h5 className="text-xs sm:text-sm font-semibold text-gray-300 mb-2 sm:mb-3">Processing History</h5>
        <div className="space-y-1.5 sm:space-y-2 max-h-32 sm:max-h-40 overflow-y-auto">
          {safeHistory && safeHistory.length > 0 ? (
            safeHistory.filter(event => event && event.status).map((event, index) => (
              <motion.div
                key={index}
                className="flex items-center justify-between text-xs p-1.5 sm:p-2 bg-gray-700 rounded"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.1 }}
              >
                <div className="flex items-center space-x-1.5 sm:space-x-2 min-w-0 flex-1">
                  <div className={`w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full flex-shrink-0 ${
                    event.status?.includes('Failed') ? 'bg-red-500' : 'bg-teal-500'
                  }`} />
                  <span className="text-gray-300 truncate">{event.status || 'Unknown Status'}</span>
                </div>
                <span className="text-gray-500 text-xs flex-shrink-0 ml-2">
                  {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : 
                   event.last_updated ? new Date(event.last_updated).toLocaleTimeString() : 
                   'Unknown Time'}
                </span>
              </motion.div>
            ))
          ) : (
            <div className="text-gray-500 text-center py-2 text-xs sm:text-sm">No history available</div>
          )}
        </div>
      </div>

      {/* Additional Info */}
      {latestUpdate && (
        <div className="mt-3 sm:mt-4 p-2 sm:p-3 bg-gray-800 rounded-lg">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-4 text-xs">
            {latestUpdate.doc_type && (
              <div className="flex flex-col sm:flex-row sm:items-center">
                <span className="text-gray-400 sm:mr-2">Type:</span>
                <span className="text-gray-200">{latestUpdate.doc_type}</span>
              </div>
            )}
            {latestUpdate.confidence !== undefined && latestUpdate.confidence !== null && (
              <div className="flex flex-col sm:flex-row sm:items-center">
                <span className="text-gray-400 sm:mr-2">Confidence:</span>
                <span className={`${
                  latestUpdate.confidence > 0.8 ? 'text-green-400' :
                  latestUpdate.confidence > 0.6 ? 'text-yellow-400' : 'text-red-400'
                }`}>
                  {latestUpdate.confidence.toFixed(2)}
                </span>
              </div>
            )}
            {latestUpdate.is_vip && (
              <div className="flex flex-col sm:flex-row sm:items-center">
                <span className="text-gray-400 sm:mr-2">VIP Level:</span>
                <span className={`${
                  latestUpdate.vip_level?.toLowerCase() === 'high' ? 'text-red-400' :
                  latestUpdate.vip_level?.toLowerCase() === 'medium' ? 'text-orange-400' :
                  'text-teal-400'
                }`}>
                  {latestUpdate.vip_level || 'Low'}
                </span>
              </div>
            )}
            {latestUpdate.summary && (
              <div className="col-span-1 sm:col-span-2">
                <span className="text-gray-400 block mb-1">Summary:</span>
                <p className="text-gray-200 text-xs sm:text-sm leading-relaxed">{latestUpdate.summary}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProgressBar;