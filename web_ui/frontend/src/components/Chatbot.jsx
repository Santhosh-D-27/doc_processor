import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';

const API_URL = 'http://127.0.0.1:8000';

const Chatbot = ({ isOpen, onClose }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async () => {
    if (input.trim() === '') return;

    const userMessage = { sender: 'user', text: input };
    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await axios.post(`${API_URL}/chat`, { query: input });
      const botMessage = { sender: 'bot', text: response.data.response };
      setMessages((prevMessages) => [...prevMessages, botMessage]);
    } catch (error) {
      console.error("Error sending message to chatbot:", error);
      setMessages((prevMessages) => [
        ...prevMessages,
        { sender: 'bot', text: 'Sorry, I am having trouble connecting to the document intelligence service.' },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !isLoading) {
      handleSendMessage();
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, y: 50, scale: 0.8 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 50, scale: 0.8 }}
          transition={{ type: "spring", stiffness: 200, damping: 20 }}
          className="fixed bottom-4 right-4 w-80 h-96 bg-gray-800 rounded-lg shadow-lg flex flex-col z-50"
        >
          <div className="flex justify-between items-center p-3 bg-gray-700 rounded-t-lg">
            <h3 className="text-white font-semibold">Document Chatbot</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-white">
              ✕
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`flex ${
                  msg.sender === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`max-w-[70%] p-2 rounded-lg ${
                    msg.sender === 'user'
                      ? 'bg-blue-500 text-white'
                      : 'bg-gray-600 text-white'
                  }`}
                >
                  {msg.text}
                </motion.div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
          <div className="p-3 border-t border-gray-700 flex">
            <input
              type="text"
              className="flex-1 p-2 rounded-l-lg bg-gray-700 text-white border border-gray-600 focus:outline-none focus:border-blue-500"
              placeholder="Ask about documents..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={isLoading}
            />
            <button
              onClick={handleSendMessage}
              className="bg-blue-500 hover:bg-blue-600 text-white p-2 rounded-r-lg disabled:opacity-50"
              disabled={isLoading}
            >
              Send
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default Chatbot;