// frontend/src/components/ProgressBar.jsx

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
      return stages.findIndex(stage => latestStatus.includes(stage.name)) ?? -1;
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
    
    if (stageName === 'Routed' && latestEvent.details?.destination) {
      details.push(`Routed to ${latestEvent.details.destination.replace('_', ' ').toUpperCase()}`);
    }
    
    return details.join('; ');
  };

  const currentStage = getCurrentStage();
  const latestUpdate = safeHistory.length > 0 ? safeHistory[safeHistory.length - 1] : null;
  const hasError = latestUpdate?.status?.includes('Failed') || latestUpdate?.status?.includes('Error');
  const isProcessing = currentStage >= 0 && currentStage < (stages.length - 1);

  return (
    <div className="w-full">
      <h4 className="text-lg font-semibold text-slate-300 mb-4">Processing Pipeline</h4>
      
      {/* --- MODIFIED SECTION START --- */}
      <div className="grid grid-cols-[auto_1fr_auto_1fr_auto_1fr_auto] items-center gap-x-2">
        {stages.map((stage, index) => {
          const stageDetails = getStageDetails(stage.name);
          const isCompleted = index <= currentStage;
          const isActive = index === currentStage && isProcessing && !hasError;
          
          return (
            <React.Fragment key={stage.name}>
              {/* Stage Icon and Label */}
              <div className="flex flex-col items-center relative">
                <motion.div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold cursor-pointer transition-all duration-300 ${
                    isCompleted
                      ? hasError && index === currentStage
                        ? 'bg-red-500 text-white shadow-lg shadow-red-500/30'
                        : `${stage.color} text-white shadow-lg`
                      : 'bg-gray-700 text-gray-400'
                  }`}
                  animate={isActive ? { scale: [1, 1.08, 1], opacity: [1, 0.6, 1] } : { scale: 1 }}
                  transition={isActive ? { duration: 1.5, repeat: Infinity, ease: "easeInOut" } : { duration: 0.3 }}
                  onMouseEnter={() => setHoveredStage(stage.name)}
                  onMouseLeave={() => setHoveredStage(null)}
                >
                  <span className="text-lg">{hasError && index === currentStage ? '❌' : stage.icon}</span>
                </motion.div>
                
                {hoveredStage === stage.name && stageDetails && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute bottom-full mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-lg z-10 whitespace-nowrap"
                    style={{ left: '50%', transform: 'translateX(-50%)' }}
                  >
                    {stageDetails}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-gray-900"></div>
                  </motion.div>
                )}
                
                <span className={`text-xs mt-2 text-center font-medium ${isCompleted ? stage.textColor : 'text-gray-500'}`}>
                  {stage.name}
                </span>
              </div>

              {/* Connecting Line */}
              {index < stages.length - 1 && (
                <div className={`h-0.5 w-full rounded-full transition-all duration-500 ${
                  index < currentStage 
                    ? 'bg-gradient-to-r from-cyan-500 to-green-500' 
                    : 'bg-gray-700'
                }`} />
              )}
            </React.Fragment>
          );
        })}
      </div>
      {/* --- MODIFIED SECTION END --- */}
    </div>
  );
};

export default ProgressBar;