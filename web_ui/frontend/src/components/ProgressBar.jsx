// In web_ui/frontend/src/components/ProgressBar.jsx

import React from 'react';
import './ProgressBar.css'; // Import the new CSS file

const ProgressBar = ({ history }) => {
  const stages = ['Ingested', 'Extracted', 'Classified', 'Routed'];

  const stageHistoryMap = stages.reduce((acc, stage) => {
    const eventsForStage = history.filter(h => h.status === stage);
    if (eventsForStage.length > 0) {
      acc[stage] = eventsForStage.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
    }
    return acc;
  }, {});

  const lastCompletedIndex = stages.findLastIndex(stage => !!stageHistoryMap[stage]);

  const getTooltipText = (stage) => {
    const event = stageHistoryMap[stage];
    if (!event) return stage;
    const details = JSON.parse(event.details || '{}');
    let detailsText = `Status: ${stage}\nTimestamp: ${new Date(event.timestamp).toLocaleString()}`;
    if (stage === 'Extracted') detailsText += `\nChars Found: ${details.chars_extracted || 'N/A'}`;
    if (stage === 'Classified') detailsText += `\nType: ${event.doc_type || 'N/A'}\nConfidence: ${event.confidence?.toFixed(2) || 'N/A'}`;
    if (stage === 'Routed') detailsText += `\nDestination: ${details.destination || 'N/A'}`;
    return detailsText;
  };

  return (
    <div className="w-full flex justify-between items-start px-4 sm:px-8 py-4">
      {stages.map((stage, index) => {
        const isCompleted = !!stageHistoryMap[stage];
        const isProcessing = lastCompletedIndex === index - 1 && lastCompletedIndex < stages.length -1;

        return (
          <div key={stage} className="flex flex-col items-center group relative">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-300
                ${isCompleted ? 'bg-teal-500 border-teal-400' : 'bg-gray-600 border-gray-500'}
                ${isProcessing ? 'processing' : ''}`} // Apply the animation class
            >
              {isCompleted && <span className="text-white font-bold">✓</span>}
            </div>
            <p className={`mt-2 text-xs sm:text-sm text-center transition-colors duration-300 ${isCompleted || isProcessing ? 'text-gray-200' : 'text-gray-500'}`}>
              {stage}
            </p>
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