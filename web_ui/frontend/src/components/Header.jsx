import React from 'react';
import { motion } from 'framer-motion';

const Header = ({ wsConnected, oauthStatus }) => {
  const getOAuthStatusConfig = () => {
    if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count > 0) {
      return { color: 'text-green-400', dot: 'bg-green-500', pulse: true };
    } else if (oauthStatus.ingestor_service_status === 'connected' && oauthStatus.connected_count === 0) {
      return { color: 'text-amber-400', dot: 'bg-amber-500', pulse: true };
    } else {
      return { color: 'text-red-400', dot: 'bg-red-500', pulse: false };
    }
  };

  const oauthConfig = getOAuthStatusConfig();

  return (
    <motion.header 
      className="text-center mb-8 lg:mb-12"
      initial={{ opacity: 0, y: -30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
    >
      {/* Main Title with Gradient */}
      <motion.div
        className="relative"
        initial={{ scale: 0.9 }}
        animate={{ scale: 1 }}
        transition={{ duration: 0.6, delay: 0.2 }}
      >
        <h1 className="text-3xl sm:text-4xl lg:text-5xl xl:text-6xl font-bold px-4 mb-3">
          <span className="gradient-text">Document Processing</span>
          <br />
          <span className="text-slate-200 text-2xl sm:text-3xl lg:text-4xl xl:text-5xl">
            Operator Dashboard
          </span>
        </h1>
        
        {/* Decorative elements */}
        <motion.div
          className="absolute -top-4 -right-4 w-20 h-20 bg-gradient-to-br from-cyan-500/20 to-purple-500/20 rounded-full blur-xl"
          animate={{ 
            scale: [1, 1.2, 1],
            rotate: [0, 180, 360]
          }}
          transition={{ 
            duration: 8,
            repeat: Infinity,
            ease: "linear"
          }}
        />
        <motion.div
          className="absolute -bottom-4 -left-4 w-16 h-16 bg-gradient-to-tr from-purple-500/20 to-cyan-500/20 rounded-full blur-xl"
          animate={{ 
            scale: [1.2, 1, 1.2],
            rotate: [360, 180, 0]
          }}
          transition={{ 
            duration: 6,
            repeat: Infinity,
            ease: "linear"
          }}
        />
      </motion.div>

      {/* Status Indicators */}
      <motion.div 
        className="glass-card rounded-2xl p-4 sm:p-6 max-w-4xl mx-auto mt-6"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.4 }}
      >
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 sm:gap-8">
          
          {/* WebSocket Status */}
          <motion.div 
            className={`flex items-center space-x-3 px-4 py-2 rounded-full glass-card ${
              wsConnected ? 'text-green-400' : 'text-red-400'
            }`}
            whileHover={{ scale: 1.05 }}
            transition={{ type: "spring", stiffness: 300 }}
          >
            <div className="relative">
              <div className={`w-3 h-3 rounded-full ${
                wsConnected ? 'bg-green-500' : 'bg-red-500'
              }`} />
              {wsConnected && (
                <motion.div
                  className="absolute inset-0 w-3 h-3 rounded-full bg-green-500"
                  animate={{ scale: [1, 1.4, 1], opacity: [1, 0, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
            </div>
            <div className="flex flex-col items-start">
              <span className="text-sm font-semibold">
                WebSocket
              </span>
              <span className="text-xs opacity-75">
                {wsConnected ? 'Live Updates' : 'Disconnected'}
              </span>
            </div>
          </motion.div>
          
          {/* Gmail Status */}
          <motion.div 
            className={`flex items-center space-x-3 px-4 py-2 rounded-full glass-card ${oauthConfig.color}`}
            whileHover={{ scale: 1.05 }}
            transition={{ type: "spring", stiffness: 300 }}
          >
            <div className="relative">
              <div className={`w-3 h-3 rounded-full ${oauthConfig.dot}`} />
              {oauthConfig.pulse && (
                <motion.div
                  className={`absolute inset-0 w-3 h-3 rounded-full ${oauthConfig.dot}`}
                  animate={{ scale: [1, 1.4, 1], opacity: [1, 0, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
            </div>
            <div className="flex flex-col items-start">
              <span className="text-sm font-semibold">
                Gmail Integration
              </span>
              <span className="text-xs opacity-75">
                {oauthStatus.connected_count > 0 
                  ? `${oauthStatus.connected_count} account${oauthStatus.connected_count > 1 ? 's' : ''}`
                  : 'No accounts'
                }
              </span>
            </div>
          </motion.div>
          
          {/* Ingestor Service Status */}
          <motion.div 
            className={`flex items-center space-x-3 px-4 py-2 rounded-full glass-card ${
              oauthStatus.ingestor_service_status === 'connected' 
                ? 'text-cyan-400' 
                : 'text-red-400'
            }`}
            whileHover={{ scale: 1.05 }}
            transition={{ type: "spring", stiffness: 300 }}
          >
            <div className="relative">
              <div className={`w-3 h-3 rounded-full ${
                oauthStatus.ingestor_service_status === 'connected' 
                  ? 'bg-cyan-500' 
                  : 'bg-red-500'
              }`} />
              {oauthStatus.ingestor_service_status === 'connected' && (
                <motion.div
                  className="absolute inset-0 w-3 h-3 rounded-full bg-cyan-500"
                  animate={{ scale: [1, 1.4, 1], opacity: [1, 0, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
            </div>
            <div className="flex flex-col items-start">
              <span className="text-sm font-semibold">
                Ingestor Service
              </span>
              <span className="text-xs opacity-75">
                {oauthStatus.ingestor_service_status}
              </span>
            </div>
          </motion.div>
        </div>

        {/* Connected Mailboxes Preview */}
        {oauthStatus.connected_count > 0 && (
          <motion.div 
            className="mt-4 pt-4 border-t border-slate-700/50"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            transition={{ duration: 0.4, delay: 0.6 }}
          >
            <div className="flex flex-wrap justify-center gap-2">
              {oauthStatus.mailboxes.slice(0, 3).map((mailbox, index) => (
                <motion.span
                  key={index}
                  className="px-3 py-1 bg-gradient-to-r from-cyan-500/20 to-purple-500/20 rounded-full text-xs font-medium text-slate-300 border border-slate-600/50"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.4, delay: 0.8 + index * 0.1 }}
                  whileHover={{ scale: 1.05, y: -2 }}
                >
                  {mailbox.email.split('@')[0]}
                </motion.span>
              ))}
              {oauthStatus.mailboxes.length > 3 && (
                <motion.span
                  className="px-3 py-1 bg-gradient-to-r from-slate-500/20 to-slate-600/20 rounded-full text-xs font-medium text-slate-400 border border-slate-600/50"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.4, delay: 1.1 }}
                >
                  +{oauthStatus.mailboxes.length - 3} more
                </motion.span>
              )}
            </div>
          </motion.div>
        )}
      </motion.div>
    </motion.header>
  );
};

export default React.memo(Header);