import React, { useState, useEffect, useCallback } from 'react';
import { Crown, AlertTriangle, Users, FileText, Calendar, Download, Eye, User, Plus, Trash2, Clock, TrendingUp } from 'lucide-react';
import axios from 'axios'; // Import axios

// API_URL will be passed as a prop from App.jsx or defined here if VIPDashboard is truly standalone
// For this example, let's assume it gets it via a prop if integrated into App.jsx,
// or define it directly if you plan to make it a top-level route later.
const API_URL = 'http://127.0.0.1:8000'; // Make sure this matches your web_ui/main.py FastAPI port

const VIPDashboard = () => {
  const [vipDocuments, setVipDocuments] = useState([]);
  const [vipContacts, setVipContacts] = useState([]);
  const [dashboardStats, setDashboardStats] = useState({}); // This endpoint is not yet in web_ui/main.py, but structure remains
  const [activeTab, setActiveTab] = useState('documents');
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [newContact, setNewContact] = useState({ email: '', name: '', role: '', department: '', vip_level: 'medium' }); // Corrected 'title' to 'role'
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null); // Added error state

  // Fetch VIP documents
  const fetchVIPDocuments = useCallback(async () => {
    try {
      setError(null);
      const response = await axios.get(`${API_URL}/vip-documents`); // Corrected API endpoint
      setVipDocuments(response.data || []);
    } catch (err) {
      console.error('Failed to fetch VIP documents:', err);
      setError('Failed to load VIP documents. Is the backend running?');
      setVipDocuments([]); // Clear documents on error
    }
  }, []);

  // Fetch VIP contacts
  const fetchVIPContacts = useCallback(async () => {
    try {
      setError(null);
      const response = await axios.get(`${API_URL}/vip-contacts`); // Corrected API endpoint
      setVipContacts(response.data || []);
    } catch (err) {
      console.error('Failed to fetch VIP contacts:', err);
      setError('Failed to load VIP contacts. Is the backend running?');
      setVipContacts([]); // Clear contacts on error
    }
  }, []);

  // Fetch dashboard stats (This endpoint needs to be added to web_ui/main.py if not already)
  const fetchDashboardStats = useCallback(async () => {
    // For now, let's mock some stats or derive from fetched data until API is ready
    // You would add a GET endpoint like /dashboard-stats to web_ui/main.py
    try {
        // Placeholder: If you add an API endpoint for stats later, use it here.
        // For now, calculate from fetched documents/contacts.
        const totalVipDocs = vipDocuments.length;
        const totalVipContacts = vipContacts.length;
        const urgentDocs = vipDocuments.filter(doc => doc.status === 'urgent').length;
        const recentDocs = vipDocuments.filter(doc => {
          const docDate = new Date(doc.last_updated);
          const sevenDaysAgo = new Date();
          sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
          return docDate >= sevenDaysAgo;
        }).length;

        setDashboardStats({
            total_vip_documents: totalVipDocs,
            total_vip_contacts: totalVipContacts,
            urgent_documents: urgentDocs,
            recent_documents: recentDocs,
        });
    } catch (err) {
        console.error('Failed to fetch dashboard stats:', err);
        // setError('Failed to load dashboard statistics.');
    }
  }, [vipDocuments, vipContacts]); // Depend on vipDocuments and vipContacts

  // Update document status
  const updateDocumentStatus = async (documentId, status) => {
    try {
      await axios.put(`${API_URL}/vip-documents/${documentId}`, { status }); // Corrected API endpoint
      fetchVIPDocuments(); // Refresh the list
      if (selectedDocument && selectedDocument.document_id === documentId) {
          setSelectedDocument(prev => ({ ...prev, status })); // Update modal state if open
      }
    } catch (err) {
      console.error('Failed to update document status:', err);
      setError('Failed to update document status.');
    }
  };

  // Add VIP contact
  const addVIPContact = async () => {
    try {
      const response = await axios.post(`${API_URL}/vip-contacts`, newContact); // Corrected API endpoint
      if (response.status === 200) { // Check for success status
        setNewContact({ email: '', name: '', role: '', department: '', vip_level: 'medium' });
        fetchVIPContacts();
      }
    } catch (err) {
      console.error('Failed to add VIP contact:', err);
      setError(err.response?.data?.detail || 'Failed to add VIP contact.');
    }
  };

  // Remove VIP contact
  const removeVIPContact = async (contactId) => {
    if (!window.confirm("Are you sure you want to remove this VIP contact?")) return;
    try {
      await axios.delete(`${API_URL}/vip-contacts/${contactId}`); // Corrected API endpoint
      fetchVIPContacts();
    } catch (err) {
      console.error('Failed to remove VIP contact:', err);
      setError('Failed to remove VIP contact.');
    }
  };

  // Download document (this assumes a new endpoint for VIP document download, which is not in web_ui/main.py yet)
  // For now, it will use the re-extract endpoint which returns the base64 content.
  // You might need a dedicated download endpoint that returns the file directly.
  const downloadDocument = async (documentId, filename) => {
    try {
      // This is a workaround assuming re-extract returns content directly or you add a /download endpoint
      const response = await axios.post(`${API_URL}/re-extract/${documentId}`);
      if (response.data.status === "success" && response.data.detail.file_content) {
        // Assuming re-extract's success detail contains the base64 content
        const fileContentBase64 = response.data.detail.file_content;
        const byteCharacters = atob(fileContentBase64);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: 'application/octet-stream' });

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a); // Append link to body
        a.click(); // Programmatically click the link
        a.remove(); // Remove link from body
        window.URL.revokeObjectURL(url); // Clean up the object URL
      } else {
        alert("Failed to get file content for download.");
      }
    } catch (err) {
      console.error('Failed to download document:', err);
      alert('Failed to download document. Ensure the re-extract endpoint can return file content.');
    }
  };

  useEffect(() => {
    const loadAllData = async () => {
      setLoading(true);
      setError(null);
      await Promise.all([fetchVIPDocuments(), fetchVIPContacts()]); // Fetch docs and contacts first
      setLoading(false);
    };
    loadAllData();
  }, [fetchVIPDocuments, fetchVIPContacts]); // Rerun when fetch functions change (unlikely but good practice)

  useEffect(() => {
    // Calculate stats after documents and contacts are fetched
    fetchDashboardStats();
  }, [vipDocuments, vipContacts, fetchDashboardStats]); // Recalculate stats when data changes


  const getVIPLevelColor = (level) => {
    switch (level?.toLowerCase()) { // Use optional chaining and toLowerCase for robustness
      case 'high': return 'text-red-600 bg-red-100';
      case 'medium': return 'text-yellow-600 bg-yellow-100';
      case 'low': return 'text-green-600 bg-green-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'urgent': return 'text-red-600 bg-red-100';
      case 'pending review': return 'text-yellow-600 bg-yellow-100'; // Match backend status
      case 'reviewed': return 'text-green-600 bg-green-100';
      case 'archived': return 'text-gray-600 bg-gray-100';
      case 'routed': return 'text-blue-600 bg-blue-100'; // Add routed status if relevant
      default: return 'text-blue-600 bg-blue-100';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-yellow-600"></div>
        <span className="ml-3 text-lg">Loading VIP Dashboard...</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 p-6 text-gray-900">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Crown className="h-8 w-8 text-yellow-600" />
              <div>
                <h1 className="text-3xl font-bold">VIP Document Management</h1>
                <p className="text-gray-600">Priority access for executive and critical documents</p>
              </div>
            </div>
            <div className="flex space-x-4">
              {dashboardStats.urgent_documents > 0 && (
                <div className="flex items-center px-4 py-2 bg-red-100 text-red-800 rounded-lg">
                  <AlertTriangle className="h-4 w-4 mr-2" />
                  {dashboardStats.urgent_documents} Urgent
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Stats Overview */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
          <div className="bg-white rounded-xl shadow-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Total VIP Documents</p>
                <p className="text-2xl font-bold">{dashboardStats.total_vip_documents || 0}</p>
              </div>
              <FileText className="h-10 w-10 text-blue-600" />
            </div>
          </div>
          
          <div className="bg-white rounded-xl shadow-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">VIP Contacts</p>
                <p className="text-2xl font-bold">{dashboardStats.total_vip_contacts || 0}</p>
              </div>
              <Users className="h-10 w-10 text-green-600" />
            </div>
          </div>
          
          <div className="bg-white rounded-xl shadow-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Recent (7 days)</p>
                <p className="text-2xl font-bold">{dashboardStats.recent_documents || 0}</p>
              </div>
              <TrendingUp className="h-10 w-10 text-purple-600" />
            </div>
          </div>
          
          <div className="bg-white rounded-xl shadow-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Needs Attention</p>
                <p className="text-2xl font-bold">{dashboardStats.urgent_documents || 0}</p>
              </div>
              <AlertTriangle className="h-10 w-10 text-red-600" />
            </div>
          </div>
        </div>

        {error && <p className="text-red-500 bg-red-100 p-3 rounded-lg mb-4">{error}</p>}

        {/* Tab Navigation */}
        <div className="bg-white rounded-xl shadow-lg mb-6">
          <div className="border-b border-gray-200">
            <nav className="flex space-x-8 px-6">
              {[
                { id: 'documents', name: 'VIP Documents', icon: FileText },
                { id: 'contacts', name: 'VIP Contacts', icon: Users }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 ${
                    activeTab === tab.id
                      ? 'border-yellow-500 text-yellow-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  <tab.icon className="h-4 w-4" />
                  <span>{tab.name}</span>
                </button>
              ))}
            </nav>
          </div>

          {/* VIP Documents Tab */}
          {activeTab === 'documents' && (
            <div className="p-6">
              <div className="space-y-4">
                {vipDocuments.length === 0 ? (
                    <p className="text-gray-500">No VIP documents found yet. Upload a document from a VIP contact or one containing VIP keywords.</p>
                ) : (
                    vipDocuments.map(doc => (
                    <div key={doc.document_id} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                        <div className="flex items-center justify-between">
                        <div className="flex-1">
                            <div className="flex items-center space-x-3 mb-2">
                            <Crown className={`h-5 w-5 ${doc.vip_level?.toLowerCase() === 'high' ? 'text-red-600' : doc.vip_level?.toLowerCase() === 'medium' ? 'text-yellow-600' : 'text-green-600'}`} />
                            <h3 className="text-lg font-medium">{doc.filename}</h3>
                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getVIPLevelColor(doc.vip_level)}`}>
                                {doc.vip_level?.toUpperCase()}
                            </span>
                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(doc.status)}`}>
                                {doc.status?.toUpperCase()}
                            </span>
                            </div>
                            <p className="text-sm text-gray-600 mb-2">From: {doc.sender || 'N/A'}</p>
                            <p className="text-sm text-gray-700 mb-2">{doc.summary || 'No summary available.'}</p>
                            <div className="flex items-center text-xs text-gray-500">
                            <Clock className="h-3 w-3 mr-1" />
                            {new Date(doc.last_updated).toLocaleString()}
                            </div>
                        </div>
                        
                        <div className="flex items-center space-x-2 ml-4">
                            <button
                            onClick={() => setSelectedDocument(doc)}
                            className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg"
                            title="View Details"
                            >
                            <Eye className="h-4 w-4" />
                            </button>
                            <button
                            onClick={() => downloadDocument(doc.document_id, doc.filename)}
                            className="p-2 text-green-600 hover:bg-green-50 rounded-lg"
                            title="Download"
                            >
                            <Download className="h-4 w-4" />
                            </button>
                            <select
                            value={doc.status}
                            onChange={(e) => updateDocumentStatus(doc.document_id, e.target.value)}
                            className="text-xs border border-gray-300 rounded px-2 py-1"
                            >
                            <option value="Pending Review">Pending Review</option>
                            <option value="Reviewed">Reviewed</option>
                            <option value="Urgent">Urgent</option>
                            <option value="Archived">Archived</option>
                            </select>
                        </div>
                        </div>

                        {/* Priority Content Preview */}
                        {doc.priority_content && Object.keys(doc.priority_content).length > 0 && (
                        <div className="mt-3 p-3 bg-yellow-50 rounded-lg">
                            <h4 className="text-sm font-medium text-yellow-800 mb-2">Priority Content:</h4>
                            <div className="text-xs text-yellow-700 space-y-1">
                            {doc.priority_content.deadlines && doc.priority_content.deadlines.length > 0 && (
                                <div><strong>Deadlines:</strong> {doc.priority_content.deadlines.slice(0, 2).join(', ')}</div>
                            )}
                            {doc.priority_content.financial_commitments && doc.priority_content.financial_commitments.length > 0 && (
                                <div><strong>Financial:</strong> {doc.priority_content.financial_commitments.slice(0, 2).join(', ')}</div>
                            )}
                            {doc.priority_content.urgency_level && (
                                <div><strong>Urgency:</strong> {doc.priority_content.urgency_level}</div>
                            )}
                            </div>
                        </div>
                        )}
                    </div>
                    ))
                )}
              </div>
            </div>
          )}

          {/* VIP Contacts Tab */}
          {activeTab === 'contacts' && (
            <div className="p-6">
              {/* Add New Contact Form */}
              <div className="bg-gray-50 rounded-lg p-4 mb-6">
                <h3 className="text-lg font-medium mb-4">Add New VIP Contact</h3>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                  <input
                    type="email"
                    placeholder="Email"
                    value={newContact.email}
                    onChange={(e) => setNewContact({...newContact, email: e.target.value})}
                    className="border border-gray-300 rounded-lg px-3 py-2"
                  />
                  <input
                    type="text"
                    placeholder="Name"
                    value={newContact.name}
                    onChange={(e) => setNewContact({...newContact, name: e.target.value})}
                    className="border border-gray-300 rounded-lg px-3 py-2"
                  />
                  <input
                    type="text"
                    placeholder="Role (e.g., CEO, VP)"
                    value={newContact.role}
                    onChange={(e) => setNewContact({...newContact, role: e.target.value})}
                    className="border border-gray-300 rounded-lg px-3 py-2"
                  />
                  <input
                    type="text"
                    placeholder="Department"
                    value={newContact.department}
                    onChange={(e) => setNewContact({...newContact, department: e.target.value})}
                    className="border border-gray-300 rounded-lg px-3 py-2"
                  />
                  <div className="flex space-x-2">
                    <select
                      value={newContact.vip_level}
                      onChange={(e) => setNewContact({...newContact, vip_level: e.target.value})}
                      className="border border-gray-300 rounded-lg px-3 py-2 flex-1"
                    >
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                    </select>
                    <button
                      onClick={addVIPContact}
                      className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 flex items-center"
                    >
                      <Plus className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>

              {/* VIP Contacts List */}
              <div className="space-y-3">
                {vipContacts.length === 0 ? (
                    <p className="text-gray-500">No VIP contacts added yet. Add new contacts above.</p>
                ) : (
                    vipContacts.map(contact => (
                    <div key={contact.id} className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:shadow-md transition-shadow">
                        <div className="flex items-center space-x-4">
                        <User className="h-8 w-8 text-gray-400" />
                        <div>
                            <h4 className="font-medium">{contact.name || 'N/A'}</h4>
                            <p className="text-sm text-gray-600">{contact.role || 'N/A'} - {contact.department || 'N/A'}</p>
                            <p className="text-sm text-gray-500">{contact.email}</p>
                        </div>
                        </div>
                        <div className="flex items-center space-x-3">
                        <span className={`px-3 py-1 rounded-full text-sm font-medium ${getVIPLevelColor(contact.vip_level)}`}>
                            {contact.vip_level?.toUpperCase()}
                        </span>
                        <button
                            onClick={() => removeVIPContact(contact.id)}
                            className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
                            title="Remove Contact"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                        </div>
                    </div>
                    ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Document Detail Modal */}
        {selectedDocument && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
              <div className="p-6 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <h2 className="text-xl font-bold">VIP Document Details</h2>
                  <button
                    onClick={() => setSelectedDocument(null)}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    ✕
                  </button>
                </div>
              </div>
              
              <div className="p-6 space-y-6">
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <h3 className="font-medium mb-2">Document Information</h3>
                    <div className="space-y-2 text-sm">
                      <p><strong>Filename:</strong> {selectedDocument.filename}</p>
                      <p><strong>Sender:</strong> {selectedDocument.sender || 'N/A'}</p>
                      <p><strong>VIP Level:</strong> 
                        <span className={`ml-2 px-2 py-1 rounded text-xs ${getVIPLevelColor(selectedDocument.vip_level)}`}>
                          {selectedDocument.vip_level?.toUpperCase()}
                        </span>
                      </p>
                      <p><strong>Status:</strong> 
                        <span className={`ml-2 px-2 py-1 rounded text-xs ${getStatusColor(selectedDocument.status)}`}>
                          {selectedDocument.status?.toUpperCase()}
                        </span>
                      </p>
                      <p><strong>Last Updated:</strong> {new Date(selectedDocument.last_updated).toLocaleString()}</p>
                    </div>
                  </div>
                  
                  <div>
                    <h3 className="font-medium mb-2">Quick Actions</h3>
                    <div className="space-y-2">
                      <button
                        onClick={() => downloadDocument(selectedDocument.document_id, selectedDocument.filename)}
                        className="w-full bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 flex items-center justify-center"
                      >
                        <Download className="h-4 w-4 mr-2" />
                        Download Document
                      </button>
                      <select
                        value={selectedDocument.status}
                        onChange={(e) => {
                          updateDocumentStatus(selectedDocument.document_id, e.target.value);
                          setSelectedDocument({...selectedDocument, status: e.target.value});
                        }}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2"
                      >
                        <option value="Pending Review">Mark as Pending Review</option>
                        <option value="Reviewed">Mark as Reviewed</option>
                        <option value="Urgent">Mark as Urgent</option>
                        <option value="Archived">Archive</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* Document Summary */}
                <div>
                  <h3 className="font-medium mb-2">Document Summary</h3>
                  <div className="bg-gray-50 rounded-lg p-4">
                    <p className="text-gray-700">{selectedDocument.summary || 'No summary available'}</p>
                  </div>
                </div>

                {/* Priority Content */}
                {selectedDocument.priority_content && Object.keys(selectedDocument.priority_content).length > 0 && (
                  <div>
                    <h3 className="font-medium mb-2">Priority Content Analysis</h3>
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                      {selectedDocument.priority_content.deadlines && selectedDocument.priority_content.deadlines.length > 0 && (
                        <div className="mb-3">
                          <h4 className="font-medium text-yellow-800 mb-1">Deadlines & Important Dates</h4>
                          <ul className="list-disc list-inside text-sm text-yellow-700">
                            {selectedDocument.priority_content.deadlines.map((deadline, idx) => (
                              <li key={idx}>{deadline}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {selectedDocument.priority_content.key_parties && selectedDocument.priority_content.key_parties.length > 0 && (
                        <div className="mb-3">
                          <h4 className="font-medium text-yellow-800 mb-1">Key Parties & Stakeholders</h4>
                          <ul className="list-disc list-inside text-sm text-yellow-700">
                            {selectedDocument.priority_content.key_parties.map((party, idx) => (
                              <li key={idx}>{party}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {selectedDocument.priority_content.financial_commitments && selectedDocument.priority_content.financial_commitments.length > 0 && (
                        <div className="mb-3">
                          <h4 className="font-medium text-yellow-800 mb-1">Financial Commitments</h4>
                          <ul className="list-disc list-inside text-sm text-yellow-700">
                            {selectedDocument.priority_content.financial_commitments.map((commitment, idx) => (
                              <li key={idx}>{commitment}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {selectedDocument.priority_content.action_items && selectedDocument.priority_content.action_items.length > 0 && (
                        <div className="mb-3">
                          <h4 className="font-medium text-yellow-800 mb-1">Action Items</h4>
                          <ul className="list-disc list-inside text-sm text-yellow-700">
                            {selectedDocument.priority_content.action_items.map((item, idx) => (
                              <li key={idx}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {selectedDocument.priority_content.urgency_level && (
                        <div className="mb-3">
                          <h4 className="font-medium text-yellow-800 mb-1">Urgency Level</h4>
                          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                            selectedDocument.priority_content.urgency_level?.toLowerCase() === 'high' ? 'bg-red-100 text-red-800' :
                            selectedDocument.priority_content.urgency_level?.toLowerCase() === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                            'bg-green-100 text-green-800'
                          }`}>
                            {selectedDocument.priority_content.urgency_level?.toUpperCase()}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Risk Assessment */}
                <div>
                  <h3 className="font-medium mb-2">Risk Assessment</h3>
                  <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-red-800">Risk Level:</span>
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                        selectedDocument.priority_content?.urgency_level?.toLowerCase() === 'high' || selectedDocument.status?.toLowerCase() === 'urgent'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}>
                        {selectedDocument.priority_content?.urgency_level?.toLowerCase() === 'high' || selectedDocument.status?.toLowerCase() === 'urgent'
                          ? 'HIGH RISK'
                          : 'MEDIUM RISK'
                        }
                      </span>
                    </div>
                    <p className="text-sm text-red-700">
                      {selectedDocument.priority_content?.urgency_level?.toLowerCase() === 'high' || selectedDocument.status?.toLowerCase() === 'urgent'
                        ? 'This document requires immediate attention due to high urgency or VIP status.'
                        : 'This document should be reviewed within 24-48 hours.'
                      }
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VIPDashboard;