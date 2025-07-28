// In web_ui/frontend/src/components/ProgressBar.jsx

import React from 'react';

const ProgressBar = ({ history }) => {
  const stages = ['Ingested', 'Extracted', 'Classified', 'Routed'];

  // Create a map of the latest event for each stage
  const stageHistoryMap = stages.reduce((acc, stage) => {
    const eventsForStage = history.filter(h => h.status === stage);
    if (eventsForStage.length > 0) {
      // Find the most recent event for this stage
      acc[stage] = eventsForStage.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
    }
    return acc;
  }, {});

  const getTooltipText = (stage) => {
    const event = stageHistoryMap[stage];
    if (!event) return stage;

    const details = JSON.parse(event.details || '{}');
    let detailsText = `Status: ${stage}\nTimestamp: ${new Date(event.timestamp).toLocaleString()}`;
    
    if (stage === 'Extracted' && details.chars_extracted) {
      detailsText += `\nChars Found: ${details.chars_extracted}`;
    }
    if (stage === 'Classified' && event.confidence != null) {
      detailsText += `\nType: ${event.doc_type || 'N/A'}\nConfidence: ${event.confidence.toFixed(2)}`;
    }
    if (stage === 'Routed' && details.destination) {
        detailsText += `\nDestination: ${details.destination}`;
    }
    return detailsText;
  };

  return (
    <div className="w-full flex justify-between items-start px-4 sm:px-8 py-4">
      {stages.map((stage) => {
        const isCompleted = !!stageHistoryMap[stage];
        return (
          <div key={stage} className="flex flex-col items-center group relative">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-300
                ${isCompleted ? 'bg-teal-500 border-teal-400' : 'bg-gray-600 border-gray-500'}`}
            >
              {isCompleted && <span className="text-white font-bold">✓</span>}
            </div>
            <p className={`mt-2 text-xs sm:text-sm text-center transition-colors duration-300 ${isCompleted ? 'text-gray-200' : 'text-gray-500'}`}>
              {stage}
            </p>
            {/* Tooltip with Timestamps and Details */}
            {isCompleted && (
              <div className="absolute bottom-full mb-2 w-48 p-2 bg-gray-800 text-white text-xs rounded-md shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 z-10 whitespace-pre-wrap text-left">
                {getTooltipText(stage)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ProgressBar;