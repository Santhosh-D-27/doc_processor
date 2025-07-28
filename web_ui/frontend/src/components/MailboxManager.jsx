// In web_ui/frontend/src/components/MailboxManager.jsx

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import MailboxModal from './MailboxModal'; // 1. Import the new modal component
import { AnimatePresence } from 'framer-motion';

const API_URL = 'http://127.0.0.1:8000';

const MailboxManager = () => {
  const [mailboxes, setMailboxes] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false); // 2. State to control the modal

  const fetchMailboxes = async () => {
    try {
      setIsLoading(true);
      const response = await axios.get(`${API_URL}/mailboxes`);
      setMailboxes(response.data);
    } catch (error) {
      console.error("Failed to fetch mailboxes:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (mailboxId) => {
    if (window.confirm("Are you sure you want to delete this mailbox connection?")) {
      try {
        await axios.delete(`${API_URL}/mailboxes/${mailboxId}`);
        fetchMailboxes();
      } catch (error) {
        console.error("Failed to delete mailbox:", error);
        alert("Could not delete the mailbox connection.");
      }
    }
  };

  useEffect(() => {
    fetchMailboxes();
  }, []);
  
  // 3. This function will be called by the modal when a mailbox is successfully added
  const handleMailboxAdded = () => {
    fetchMailboxes();
  };

  return (
    <>
      <div className="bg-gray-400/10 backdrop-blur-md rounded-xl shadow-lg border border-gray-200/10 p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-semibold text-gray-200">Connected Mailboxes</h3>
          <button 
            onClick={() => setIsModalOpen(true)} // 4. Open the modal on click
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition-colors"
          >
            + Connect New Mailbox
          </button>
        </div>
        
        {isLoading ? (
          <p className="text-gray-400">Loading connections...</p>
        ) : (
          <div className="space-y-3">
            {mailboxes.length > 0 ? (
              mailboxes.map(mb => (
                <div key={mb.id} className="flex justify-between items-center bg-gray-900/50 p-3 rounded-lg">
                  <div>
                    <p className="font-semibold text-gray-200">{mb.email}</p>
                    <p className="text-sm text-gray-400">Monitoring folder: "{mb.folder}"</p>
                  </div>
                  <button 
                    onClick={() => handleDelete(mb.id)}
                    className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white text-xs font-bold rounded-md transition-colors"
                  >
                    Delete
                  </button>
                </div>
              ))
            ) : (
              <p className="text-gray-400">No mailboxes are connected yet.</p>
            )}
          </div>
        )}
      </div>

      {/* 5. Conditionally render the modal with an animation */}
      <AnimatePresence>
        {isModalOpen && (
          <MailboxModal 
            onClose={() => setIsModalOpen(false)} 
            onMailboxAdded={handleMailboxAdded} 
          />
        )}
      </AnimatePresence>
    </>
  );
};

export default MailboxManager;