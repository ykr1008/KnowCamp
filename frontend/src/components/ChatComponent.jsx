import { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { Send, Loader2, Trash2, FileText, Plus, MessageSquare, User, LogOut, Menu, MoreVertical, Edit2, Users, X, UserCheck, Book, PlusCircle, LogIn, Hash, Home, ArrowLeft, Copy, Check, UploadCloud, CheckCircle, XCircle} from 'lucide-react';
import ReactMarkdown from 'react-markdown';

const ChatComponent = ({ onLogout }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [userRole, setUserRole] = useState(localStorage.getItem('role'));
  const [documents, setDocuments] = useState([]);
  
  const [activeDocument, setActiveDocument] = useState(null);
  const [aiMode, setAiMode] = useState(false); // false = Strict Doc Mode, true = General AI

  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [showDocs, setShowDocs] = useState(true);
  
  const [chatHistory, setChatHistory] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);

  const [hoveredChatId, setHoveredChatId] = useState(null);
  const [menuOpenId, setMenuOpenId] = useState(null);
  const [editingChatId, setEditingChatId] = useState(null);
  const [editTitle, setEditTitle] = useState("");

  // --- BULK UPLOAD QUEUE STATES ---
  const [uploadQueue, setUploadQueue] = useState([]);
  const [isDragging, setIsDragging] = useState(false);

  // ADMIN DASHBOARD STATES
  const [showAdminPanel, setShowAdminPanel] = useState(false);
  const [adminTab, setAdminTab] = useState('whitelist'); 
  const [whitelist, setWhitelist] = useState([]);
  const [activeUsers, setActiveUsers] = useState([]); 
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("student");

  // LMS CLASSROOM STATES
  const [activeView, setActiveView] = useState('global'); // 'global', 'dashboard', 'classroom'
  const [subjects, setSubjects] = useState([]);
  const [currentSubject, setCurrentSubject] = useState(null);
  
  const [showCreateClassModal, setShowCreateClassModal] = useState(false);
  const [newClassName, setNewClassName] = useState("");
  const [newClassYear, setNewClassYear] = useState("");

  const [showJoinClassModal, setShowJoinClassModal] = useState(false);
  const [joinCode, setJoinCode] = useState("");

  // --- NEW: CLASS ROSTER STATES ---
  const [showRosterModal, setShowRosterModal] = useState(false);
  const [classStudents, setClassStudents] = useState([]);

  // --- NEW: COPY TO CLIPBOARD STATE ---
  const [copiedSubjectId, setCopiedSubjectId] = useState(null);

  // --- NEW: EXTRACT USERNAME FROM JWT TOKEN ---
  const currentUsername = useMemo(() => {
    try {
      const token = localStorage.getItem('token');
      if (!token) return null;
      // Decode the middle part of the JWT where the data lives
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub; // In your backend, 'sub' is the username!
    } catch (e) {
      return null;
    }
  }, []);

  const handleCopyCode = (e, code, subjectId) => {
    e.stopPropagation(); // CRITICAL: Stops the click from opening the classroom!
    navigator.clipboard.writeText(code);
    setCopiedSubjectId(subjectId);
    
    // Change back to the copy icon after 2 seconds
    setTimeout(() => {
      setCopiedSubjectId(null);
    }, 2000);
  };

  // Fetch the students for the current class
  const fetchClassStudents = async (subjectId) => {
    try {
      const token = localStorage.getItem('token');
      // Note: Make sure you have this GET endpoint in your FastAPI backend!
      const response = await axios.get(`http://127.0.0.1:8000/subjects/${subjectId}/students`, { 
        headers: { Authorization: `Bearer ${token}` } 
      });
      setClassStudents(response.data.students || []);
      setShowRosterModal(true);
    } catch (error) { 
      console.error("Failed to fetch students"); 
    }
  };

  // Trigger the backend deletion endpoint we built
  const removeUserFromClass = async (targetUser) => {
    if (!window.confirm(`Remove ${targetUser.username} from the class?`)) return;
    
    try {
      const token = localStorage.getItem('token');
      
      // If the target is the instructor, hit the faculty endpoint
      if (targetUser.role === 'instructor') {
         await axios.put(`http://127.0.0.1:8000/subjects/${currentSubject.id}/remove_faculty`, {}, { 
           headers: { Authorization: `Bearer ${token}` } 
         });
      } else {
         // Otherwise, hit the student enrollment endpoint
         await axios.delete(`http://127.0.0.1:8000/subjects/${currentSubject.id}/students/${targetUser.id}`, { 
           headers: { Authorization: `Bearer ${token}` } 
         });
      }
      
      // Refresh the list instantly!
      fetchClassStudents(currentSubject.id);
    } catch (error) { 
      alert(error.response?.data?.detail || "Failed to remove user."); 
    }
  };

  const handleLeaveClass = async () => {
    if (!window.confirm("Are you sure you want to exit this class?")) return;
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`http://127.0.0.1:8000/subjects/${currentSubject.id}/leave`, { 
        headers: { Authorization: `Bearer ${token}` } 
      });
      alert("You have left the class.");
      setShowRosterModal(false);
      goDashboard(); // Kick them out to the dashboard
    } catch (error) { 
      alert(error.response?.data?.detail || "Failed to leave class."); 
    }
  };

  // --- NEW: SMART ROSTER SORTING LOGIC ---
  const sortedClassStudents = useMemo(() => {
    if (!classStudents.length) return [];

    const myUserId = parseInt(localStorage.getItem('user_id') || 0);

    // 1. Find the key players
    const me = classStudents.find(user => user.id === myUserId);
    const instructor = classStudents.find(user => user.role === "instructor" && user.id !== myUserId);

    // 2. Filter out me and the instructor, then alphabetize the rest
    const otherStudents = classStudents
      .filter(user => user.id !== myUserId && user.role !== "instructor")
      .sort((a, b) => a.username.localeCompare(b.username));

    // 3. Construct the array based on WHO is looking at it
    if (userRole === "student") {
      // Students see themselves first, then the instructor
      return [me, instructor, ...otherStudents].filter(Boolean);
    } else {
      // Admins and Faculty see the Instructor first, then themselves (if they aren't the instructor)
      return [instructor, me, ...otherStudents].filter(Boolean);
    }
  }, [classStudents, userRole]);
  // ----------------------------------------

  // --- DELETE CLASSROOM ---
  const handleDeleteClass = async () => {
    if (!window.confirm("🚨 WARNING: Are you sure you want to delete this class? This will PERMANENTLY wipe all documents, chat history, and enrollments. This cannot be undone.")) return;
    
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`http://127.0.0.1:8000/subjects/${currentSubject.id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert("Class deleted successfully.");
      goDashboard(); // Kick them back to the dashboard after deletion
    } catch (error) {
      alert(error.response?.data?.detail || "Failed to delete class.");
    }
  };

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); };
  useEffect(() => { scrollToBottom(); }, [messages, isLoading]);

  // RE-FETCH DATA WHENEVER WE CHANGE ROOMS (Global vs Classroom)
  useEffect(() => {
    fetchDocuments();
    fetchChats(); 
    if (activeView === 'dashboard') fetchSubjects();
  }, [activeView, currentSubject]);

  // ================= LMS LOGIC =================
  const fetchSubjects = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('http://127.0.0.1:8000/subjects/', { headers: { Authorization: `Bearer ${token}` } });
      setSubjects(response.data.subjects);
    } catch (error) { console.error("Failed to fetch subjects"); }
  };

  const handleCreateClass = async (e) => {
    e.preventDefault();
    if (!newClassName.trim() || !newClassYear.trim()) return;
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post('http://127.0.0.1:8000/subjects/', 
        { name: newClassName, year: newClassYear }, { headers: { Authorization: `Bearer ${token}` } }
      );
      alert(`Class created! The invite code is: ${response.data.invite_code}`);
      setShowCreateClassModal(false); setNewClassName(""); setNewClassYear(""); fetchSubjects();
    } catch (error) { alert(error.response?.data?.detail || "Failed to create class"); }
  };

  const handleJoinClass = async (e) => {
    e.preventDefault();
    if (!joinCode.trim()) return;
    try {
      const token = localStorage.getItem('token');
      await axios.post('http://127.0.0.1:8000/subjects/join/', { invite_code: joinCode }, { headers: { Authorization: `Bearer ${token}` } });
      alert("Successfully joined the class!");
      setShowJoinClassModal(false); setJoinCode(""); fetchSubjects();
    } catch (error) { alert(error.response?.data?.detail || "Failed to join class. Check the code."); }
  };

  // NAVIGATION FUNCTIONS
  const goGlobalHome = () => {
    setCurrentSubject(null);
    setActiveView('global');
    startNewChat();
  };

  const goDashboard = () => {
    setActiveView('dashboard');
  };

  const openClassroom = (subject) => {
    setCurrentSubject(subject);
    setActiveView('classroom');
    startNewChat(); 
  };

  // ================= STANDARD CHAT & DOC LOGIC =================
  const fetchDocuments = async () => {
    try {
      const token = localStorage.getItem('token');
      
      // Build smart query parameters
      const queryParams = { 
        t: Date.now() // THE CACHE BUSTER: Forces Chrome to make a fresh request!
      }; 
      
      if (currentSubject) {
        queryParams.subject_id = currentSubject.id;
      }

      const response = await axios.get('http://127.0.0.1:8000/documents/', {
        headers: { 
          Authorization: `Bearer ${token}`,
          'Cache-Control': 'no-cache' // Extra instruction telling browsers not to lie to us
        },
        params: queryParams
      });
      
      setDocuments(response.data.documents);
    } catch (error) { 
      console.error("Failed to fetch docs"); 
    }
  };

  const fetchChats = async () => {
    try {
      const token = localStorage.getItem('token');
      let url = 'http://127.0.0.1:8000/my_chats/';
      if (currentSubject) url += `?subject_id=${currentSubject.id}`; // Only fetch chats for this room!

      const response = await axios.get(url, { headers: { Authorization: `Bearer ${token}` } });
      setChatHistory(response.data.chats);
    } catch (error) { console.error("Failed to fetch chat history"); }
  };

  const loadChat = async (sessionId) => {
    if (menuOpenId === sessionId || editingChatId === sessionId) return;
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`http://127.0.0.1:8000/chat_history/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      setMessages(response.data.messages);
      setCurrentSessionId(sessionId);
    } catch (error) { console.error("Failed to load chat"); }
  };

  const startNewChat = () => { setMessages([]); setCurrentSessionId(null); };

  const deleteChat = async (e, sessionId) => {
    e.stopPropagation(); setMenuOpenId(null); 
    if (!window.confirm("Delete this conversation?")) return;
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`http://127.0.0.1:8000/my_chats/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      fetchChats(); 
      if (currentSessionId === sessionId) startNewChat();
    } catch (error) { alert("Failed to delete chat."); }
  };

  const startEditing = (e, chat) => {
    e.stopPropagation(); 
    setMenuOpenId(null); 
    setEditingChatId(chat.id); 
    setEditTitle(chat.title);
  };

  const saveChatTitle = async (sessionId) => {
    if (!editTitle.trim()) { 
      setEditingChatId(null); 
      return; 
    }
    try {
      const token = localStorage.getItem('token');
      await axios.put(`http://127.0.0.1:8000/my_chats/${sessionId}`, 
        { title: editTitle }, 
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setEditingChatId(null); 
      fetchChats(); 
    } catch (error) { 
      setEditingChatId(null); 
    }
  };

  // 1. Handles the Drag & Drop OR the File Selection
  const handleFileDrop = async (e) => {
    e.preventDefault();
    setIsDragging(false);
    
    // Grab files from either a drop event or a click event
    const files = Array.from(e.dataTransfer ? e.dataTransfer.files : e.target.files);
    if (!files.length) return;
    if (e.target) e.target.value = null; // Reset input

    // Create tracking objects for each file
    const newQueueItems = files.map(file => ({
      id: Math.random().toString(36).substring(7), // Unique ID
      file: file,
      progress: 0,
      status: 'pending', // 'pending' | 'uploading' | 'success' | 'error'
      errorMessage: ''
    }));

    // Add them to the visual UI queue
    setUploadQueue(prev => [...prev, ...newQueueItems]);

    // 2. PROCESS SEQUENTIALLY (Protects your AI Parser & Database from crashing!)
    for (const item of newQueueItems) {
      await processSingleUpload(item.id, item.file);
    }
  };

  // 3. The Actual Axios Request for a single file
  const processSingleUpload = async (fileId, file) => {
    // Update this specific file's status to 'uploading'
    setUploadQueue(prev => prev.map(item => item.id === fileId ? { ...item, status: 'uploading' } : item));

    const formData = new FormData();
    formData.append('file', file);
    if (currentSubject) formData.append('subject_id', currentSubject.id);

    try {
      const token = localStorage.getItem('token');
      await axios.post('http://127.0.0.1:8000/upload_document/', formData, {
        headers: { 'Content-Type': 'multipart/form-data', 'Authorization': `Bearer ${token}` },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          // Update the progress bar for THIS specific file
          setUploadQueue(prev => prev.map(item => item.id === fileId ? { ...item, progress: percentCompleted } : item));
        }
      });
      
      // Mark as success!
      setUploadQueue(prev => prev.map(item => item.id === fileId ? { ...item, status: 'success', progress: 100 } : item));
      fetchDocuments(); // Refresh the sidebar list instantly so they see it appear
      setShowDocs(true);
    } catch (error) {
      // Mark as error and show the exact API failure message
      setUploadQueue(prev => prev.map(item => item.id === fileId ? { ...item, status: 'error', errorMessage: error.response?.data?.detail || "Upload failed" } : item));
    }
  };

  const deleteDocument = async (docId) => {
    if (!window.confirm("Remove this document?")) return;
    try {
      const token = localStorage.getItem('token'); // 1. Get the token
      await axios.delete(`http://127.0.0.1:8000/documents/${docId}/`, {
        headers: { Authorization: `Bearer ${token}` } // 2. Send the token!
      });
      fetchDocuments(); 
    } catch (error) { 
      console.error(error);
      alert("Delete failed. Check console for details."); 
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token'); localStorage.removeItem('role');
    window.location.reload(); 
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    const userMessage = { role: 'user', content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    
    try {
      const token = localStorage.getItem('token'); 
      // 👇 NEW: Added ai_mode to the URL
      let url = `http://127.0.0.1:8000/chat/?question=${encodeURIComponent(input)}&ai_mode=${aiMode}`;      if (currentSessionId) url += `&session_id=${currentSessionId}`;
      if (currentSubject) url += `&subject_id=${currentSubject.id}`; // Tell AI which room to search!
      
      if (activeDocument) url += `&filename=${encodeURIComponent(activeDocument.filename)}`;

      const response = await axios.get(url, { headers: { Authorization: `Bearer ${token}` } });
      if (response.data.session_id && !currentSessionId) {
        setCurrentSessionId(response.data.session_id);
        fetchChats(); 
      }
      const aiMessage = { role: 'ai', content: response.data.answer, sources: response.data.sources };
      setMessages((prev) => [...prev, aiMessage]);
    } catch (error) {
      setMessages((prev) => [...prev, { role: 'ai', content: "Server error.", sources: [] }]);
    } finally {
      setIsLoading(false);
    }
  };

  // --- NEW: QUICK ACTION HELPER ---
  const triggerQuickAction = async (actionText) => {
    if (isLoading) return;
    
    // 1. Add the user's "hidden" prompt to the screen
    const userMessage = { role: 'user', content: actionText };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    
    try {
      const token = localStorage.getItem('token'); 
      // 👇 NEW: Added ai_mode to the URL
      let url = `http://127.0.0.1:8000/chat/?question=${encodeURIComponent(actionText)}&ai_mode=${aiMode}`;      if (currentSessionId) url += `&session_id=${currentSessionId}`;
      if (currentSubject) url += `&subject_id=${currentSubject.id}`;
      if (activeDocument) url += `&filename=${encodeURIComponent(activeDocument.filename)}`;

      const response = await axios.get(url, { headers: { Authorization: `Bearer ${token}` } });
      
      if (response.data.session_id && !currentSessionId) {
        setCurrentSessionId(response.data.session_id);
        fetchChats(); 
      }
      
      const aiMessage = { role: 'ai', content: response.data.answer, sources: response.data.sources };
      setMessages((prev) => [...prev, aiMessage]);
    } catch (error) {
      setMessages((prev) => [...prev, { role: 'ai', content: "Server error.", sources: [] }]);
    } finally {
      setIsLoading(false);
    }
  };

  // ================= ADMIN PANEL LOGIC =================
  const fetchWhitelist = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('http://127.0.0.1:8000/admin/whitelist/', { headers: { Authorization: `Bearer ${token}` } });
      setWhitelist(response.data.whitelist || []);
    } catch (error) { console.error("Failed to fetch whitelist"); }
  };

  const addToWhitelist = async (e) => {
    e.preventDefault();
    if (!newEmail.trim()) return;
    try {
      const token = localStorage.getItem('token');
      await axios.post('http://127.0.0.1:8000/admin/whitelist/', 
        { email: newEmail, assigned_role: newRole }, 
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert(`${newEmail} has been whitelisted as ${newRole}!`);
      setNewEmail(""); // Clear the input box
      fetchWhitelist(); // Refresh the list so it shows up instantly
    } catch (error) { 
      alert(error.response?.data?.detail || "Failed to add to whitelist."); 
    }
  };

  const removeFromWhitelist = async (id) => {
    if (!window.confirm("Remove this email from the whitelist?")) return;
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`http://127.0.0.1:8000/admin/whitelist/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      fetchWhitelist(); // Refresh the list
    } catch (error) { alert("Failed to remove from whitelist."); }
  };

  // --- NEW: Fetch all active users from database ---
  const fetchActiveUsers = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('http://127.0.0.1:8000/admin/users/', { headers: { Authorization: `Bearer ${token}` } });
      setActiveUsers(response.data.users || []);
    } catch (error) { console.error("Failed to fetch users"); }
  };

  // --- NEW: Delete active users ---
  const deleteActiveUser = async (id) => {
    if (!window.confirm("PERMANENTLY delete this user and all their chats?")) return;
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`http://127.0.0.1:8000/admin/users/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      fetchActiveUsers(); // Refresh the list!
    } catch (error) { alert("Failed to delete user."); }
  };

  // --- UPGRADED: Fetch the correct data depending on which tab the Admin clicks ---
  useEffect(() => {
    if (showAdminPanel) {
      if (adminTab === 'whitelist') fetchWhitelist();
      if (adminTab === 'users') fetchActiveUsers();
    }
  }, [showAdminPanel, adminTab]);

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%', backgroundColor: '#ffffff', fontFamily: 'sans-serif', overflow: 'hidden' }}>
      
      {/* ================= MODALS ================= */}
      {/* ADMIN, CREATE CLASS, JOIN CLASS MODALS GO HERE (Same as previous step) */}
      {showCreateClassModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: '#fff', width: '400px', borderRadius: '12px', padding: '25px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h2 style={{ margin: 0, color: '#1f1f1f', display: 'flex', alignItems: 'center', gap: '10px' }}><PlusCircle size={24} color="#007bff" /> Create New Class</h2>
              <button onClick={() => setShowCreateClassModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#5f6368' }}><X size={24} /></button>
            </div>
            <form onSubmit={handleCreateClass} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="Subject Name" value={newClassName} onChange={(e) => setNewClassName(e.target.value)} required style={{ padding: '12px', borderRadius: '6px', border: '1px solid #ccc' }} />
              <input type="text" placeholder="Year / Section" value={newClassYear} onChange={(e) => setNewClassYear(e.target.value)} required style={{ padding: '12px', borderRadius: '6px', border: '1px solid #ccc' }} />
              <button type="submit" style={{ padding: '12px', borderRadius: '6px', backgroundColor: '#007bff', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold', marginTop: '10px' }}>Create</button>
            </form>
          </div>
        </div>
      )}

      {showJoinClassModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: '#fff', width: '400px', borderRadius: '12px', padding: '25px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h2 style={{ margin: 0, color: '#1f1f1f', display: 'flex', alignItems: 'center', gap: '10px' }}><LogIn size={24} color="#007bff" /> Join a Class</h2>
              <button onClick={() => setShowJoinClassModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#5f6368' }}><X size={24} /></button>
            </div>
            <form onSubmit={handleJoinClass} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="6-Digit Code" value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())} required maxLength={6} style={{ padding: '12px', borderRadius: '6px', border: '1px solid #ccc', textTransform: 'uppercase', letterSpacing: '2px' }} />
              <button type="submit" style={{ padding: '12px', borderRadius: '6px', backgroundColor: '#007bff', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold', marginTop: '10px' }}>Join</button>
            </form>
          </div>
        </div>
      )}
      {/* ================= ADMIN MANAGE USERS MODAL ================= */}
      {showAdminPanel && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: '#fff', width: '600px', maxHeight: '80vh', borderRadius: '12px', padding: '25px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h2 style={{ margin: 0, color: '#1f1f1f', display: 'flex', alignItems: 'center', gap: '10px' }}><Users size={24} color="#007bff" /> Admin Panel</h2>
              <button onClick={() => setShowAdminPanel(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#5f6368' }}><X size={24} /></button>
            </div>
            
            {/* Admin Tabs */}
            <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', borderBottom: '1px solid #e1e5ea', paddingBottom: '10px' }}>
              <button onClick={() => setAdminTab('whitelist')} style={{ padding: '8px 16px', border: 'none', background: adminTab === 'whitelist' ? '#e8f0fe' : 'transparent', color: adminTab === 'whitelist' ? '#1967d2' : '#5f6368', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>Whitelist Emails</button>
              <button onClick={() => setAdminTab('users')} style={{ padding: '8px 16px', border: 'none', background: adminTab === 'users' ? '#e8f0fe' : 'transparent', color: adminTab === 'users' ? '#1967d2' : '#5f6368', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>Manage Users</button>
            </div>

            {/* Whitelist Tab Content */}
            {adminTab === 'whitelist' && (
              <div style={{ overflowY: 'auto', flex: 1 }}>
                <form onSubmit={addToWhitelist} style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                  <input type="email" placeholder="Email address" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required style={{ flex: 1, padding: '10px', borderRadius: '6px', border: '1px solid #ccc' }} />
                  <select value={newRole} onChange={(e) => setNewRole(e.target.value)} style={{ padding: '10px', borderRadius: '6px', border: '1px solid #ccc' }}>
                    <option value="student">Student</option>
                    <option value="faculty">Faculty</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button type="submit" style={{ padding: '10px 15px', borderRadius: '6px', backgroundColor: '#007bff', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>Add</button>
                </form>
                
                {/* Your mapped whitelist items usually go here */}
                {whitelist.map((item, index) => (
                   <div key={index} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px', borderBottom: '1px solid #f0f0f0' }}>
                     <span style={{color: '#5f6368'}}>{item.email} ({item.role})</span>
                     <button onClick={() => removeFromWhitelist(item.id)} style={{ color: 'red', border: 'none', background: 'none', cursor: 'pointer' }}><Trash2 size={16} /></button>
                   </div>
                ))}
              </div>
            )}

            {/* Active Users Tab Content */}
            {adminTab === 'users' && (
              <div style={{ overflowY: 'auto', flex: 1 }}>
                {/* Your mapped active users usually go here */}
                {activeUsers.map((u, index) => (
                   <div key={index} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px', borderBottom: '1px solid #f0f0f0' }}>
                     <span style={{color: '#000000'}}><strong>{u.username}</strong> <span style={{color: '#5f6368'}}>({u.role})</span></span>
                     <button onClick={() => deleteActiveUser(u.id)} style={{ color: 'red', border: 'none', background: 'none', cursor: 'pointer' }}><Trash2 size={16} /></button>
                   </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      {/* ================= SIDEBAR ================= */}
      {isSidebarOpen && (
        <div style={{ width: '280px', flexShrink: 0, backgroundColor: '#f9fafd', display: 'flex', flexDirection: 'column', padding: '15px', borderRight: '1px solid #e1e5ea', boxSizing: 'border-box' }}>
          
          {/* NAVIGATION BUTTONS */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '20px' }}>
            <button 
              onClick={goGlobalHome}
              style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px', backgroundColor: activeView === 'global' ? '#e8f0fe' : '#ffffff', border: '1px solid #dcdfe3', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', color: activeView === 'global' ? '#1967d2' : '#1f1f1f' }}
            >
              <Home size={18} /> KnowCamp AI
            </button>
            
            <button 
              onClick={goDashboard}
              style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px', backgroundColor: activeView === 'dashboard' ? '#e8f0fe' : '#ffffff', border: '1px solid #dcdfe3', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', color: activeView === 'dashboard' ? '#1967d2' : '#1f1f1f' }}
            >
              <Book size={18} /> My Classes
            </button>
          </div>

          {/* DYNAMIC NEW CHAT & UPLOAD BUTTONS */}
          {activeView !== 'dashboard' && (
            <>
              <button onClick={startNewChat} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px', backgroundColor: '#ffffff', border: '1px solid #dcdfe3', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', color: '#1f1f1f', marginBottom: '15px' }}>
                <Plus size={18} color="#007bff" /> New Chat
              </button>

              {/* Strict Upload Check: Admins upload anywhere. Faculty ONLY upload if they own the current class. */}
              {((userRole === 'admin') || 
                (userRole === 'faculty' && activeView === 'classroom' && currentSubject?.faculty_id === parseInt(localStorage.getItem('user_id') || 0))) && (
                <>
                  {/* --- 1. THE DROPZONE --- */}
                  <label 
                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={handleFileDrop}
                    style={{ 
                      cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '20px 10px', 
                      backgroundColor: isDragging ? '#e8f0fe' : '#ffffff', 
                      border: isDragging ? '2px dashed #1967d2' : '2px dashed #007bff', 
                      borderRadius: '8px', color: isDragging ? '#1967d2' : '#007bff', fontWeight: 'bold', marginBottom: '15px', transition: 'all 0.2s', textAlign: 'center' 
                    }}
                  >
                    <UploadCloud size={28} />
                    <span style={{ fontSize: '14px' }}>{isDragging ? 'Drop files here!' : 'Drag & Drop or Click to Upload'}</span>
                    <span style={{ fontSize: '11px', color: '#5f6368', fontWeight: 'normal' }}>Supports bulk PDF, DOCX, CSV</span>
                    <input type="file" multiple onChange={handleFileDrop} style={{ display: 'none' }} />
                  </label>

                  {/* --- 2. THE QUEUE LIST --- */}
                  {uploadQueue.length > 0 && (
                    <div style={{ marginBottom: '20px', display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '250px', overflowY: 'auto', paddingRight: '5px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', color: '#5f6368' }}>
                        <span>Upload Queue ({uploadQueue.length})</span>
                        <button onClick={() => setUploadQueue([])} style={{ background: 'none', border: 'none', color: '#1967d2', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}>Clear</button>
                      </div>

                      {uploadQueue.map(item => (
                        <div key={item.id} style={{ padding: '10px', backgroundColor: '#ffffff', border: '1px solid #dcdfe3', borderRadius: '8px', fontSize: '12px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontWeight: 'bold', color: '#1f1f1f' }}>
                            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '140px' }} title={item.file.name}>{item.file.name}</span>
                            
                            {/* Status Indicators */}
                            {item.status === 'pending' && <span style={{ color: '#5f6368' }}>Waiting...</span>}
                            {item.status === 'uploading' && <span style={{ color: '#007bff' }}>{item.progress < 100 ? `${item.progress}%` : 'Parsing AI...'}</span>}
                            {item.status === 'success' && <CheckCircle size={14} color="#10b981" />}
                            {item.status === 'error' && <XCircle size={14} color="#ff4d4d" />}
                          </div>

                          {/* Progress Bar or Error Message */}
                          {item.status === 'error' ? (
                            <div style={{ color: '#ff4d4d', fontSize: '11px', lineHeight: '1.2' }}>{item.errorMessage}</div>
                          ) : (
                            <div style={{ width: '100%', backgroundColor: '#e1e5ea', borderRadius: '4px', height: '4px', overflow: 'hidden' }}>
                              <div style={{ 
                                height: '100%', 
                                backgroundColor: item.status === 'success' ? '#10b981' : '#007bff', 
                                width: `${item.progress}%`, 
                                transition: 'width 0.3s ease' 
                              }}></div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}


          
          {/* DYNAMIC MEMORY & CHAT HISTORY */}
          <div style={{ flex: 1, overflowY: 'auto', marginBottom: '15px' }}>
            {activeView !== 'dashboard' && (
              <>
                <div onClick={() => setShowDocs(!showDocs)} style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', color: '#444746', fontSize: '12px', fontWeight: 'bold', marginBottom: '10px' }}>
                  <span>📚 {activeView === 'global' ? 'GLOBAL DOCS' : 'CLASS MAT'} ({documents.length})</span>
                  <span>{showDocs ? '▼' : '▶'}</span>
                </div>
                
                {showDocs && (
                  <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 20px 0', gap: '2px', display: 'flex', flexDirection: 'column' }}>
                    {documents.map((doc) => (
                      <li 
                        key={doc.id} 
                        style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', padding: '8px', borderRadius: '6px' }}
                        
                        // 1. UPDATED HOVER LOGIC: We use querySelectorAll('.doc-btn') to show/hide ALL buttons at once
                        onMouseEnter={(e) => { 
                          e.currentTarget.style.backgroundColor = '#e1e5ea'; 
                          e.currentTarget.querySelectorAll('.doc-btn').forEach(btn => btn.style.display = 'block'); 
                        }}
                        onMouseLeave={(e) => { 
                          e.currentTarget.style.backgroundColor = 'transparent'; 
                          e.currentTarget.querySelectorAll('.doc-btn').forEach(btn => btn.style.display = 'none'); 
                        }}
                      >
                        
                        {/* 2. DYNAMIC COLORS: Highlights blue if this file is actively focused */}
                        <FileText size={14} color={activeDocument?.id === doc.id ? "#007bff" : "#5f6368"} />
                        <span style={{ flex: 1, color: activeDocument?.id === doc.id ? '#007bff' : '#1f1f1f', fontWeight: activeDocument?.id === doc.id ? 'bold' : 'normal', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {doc.filename}
                        </span>
                        
                        {/* 3. NEW FOCUS BUTTON: Everyone gets this button! Note the class is "doc-btn" */}
                        <button className="doc-btn" onClick={() => setActiveDocument(doc)} style={{ display: 'none', background: 'none', border: 'none', color: '#007bff', cursor: 'pointer', padding: '2px' }} title="Chat with only this file">
                          <MessageSquare size={14} />
                        </button>

                        {/* 4. EXISTING DELETE BUTTON: Note the class changed to "doc-btn" so hover works for both */}
                        {(userRole === 'admin' || (userRole === 'faculty' && doc.uploaded_by === localStorage.getItem('sub'))) && (
                          <button className="doc-btn" onClick={() => deleteDocument(doc.id)} style={{ display: 'none', background: 'none', border: 'none', color: '#ff4d4d', cursor: 'pointer', padding: '2px' }} title="Delete File">
                            <Trash2 size={14} />
                          </button>
                        )}

                      </li>
                    ))}
                  </ul>
                )}
                
                <div style={{ color: '#444746', fontSize: '12px', fontWeight: 'bold', marginBottom: '5px' }}>⏱️ RECENT CHATS</div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, gap: '2px', display: 'flex', flexDirection: 'column' }}>
                  {chatHistory.map((chat) => (
                    <li 
                      key={chat.id} 
                      onClick={() => loadChat(chat.id)} 
                      onMouseEnter={() => setHoveredChatId(chat.id)}
                      onMouseLeave={() => setHoveredChatId(null)}
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', padding: '8px', borderRadius: '6px', cursor: 'pointer', position: 'relative', backgroundColor: currentSessionId === chat.id || menuOpenId === chat.id ? '#e1e5ea' : 'transparent', fontWeight: currentSessionId === chat.id ? 'bold' : 'normal' }}
                    >
                      <MessageSquare size={14} color="#5f6368" />
                      
                      {/* Edit Input or Normal Text */}
                      {editingChatId === chat.id ? (
                        <input 
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onBlur={() => saveChatTitle(chat.id)} 
                          onKeyDown={(e) => { if (e.key === 'Enter') saveChatTitle(chat.id); }}
                          autoFocus
                          style={{ flex: 1, border: '1px solid #007bff', borderRadius: '4px', padding: '2px 4px', outline: 'none' }}
                        />
                      ) : (
                        <span style={{ flex: 1, color: '#1f1f1f', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{chat.title}</span>
                      )}
                      
                      {/* The 3-Dots Menu Logic */}
                      {(hoveredChatId === chat.id || menuOpenId === chat.id) && editingChatId !== chat.id && (
                        <div style={{ position: 'relative' }}>
                          <button 
                            onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === chat.id ? null : chat.id); }} 
                            style={{ background: 'none', border: 'none', color: '#5f6368', cursor: 'pointer', padding: '2px', display: 'flex', alignItems: 'center' }}
                          >
                            <MoreVertical size={16} />
                          </button>
                          
                          {menuOpenId === chat.id && (
                            <div style={{ position: 'absolute', right: 0, top: '25px', backgroundColor: '#ffffff', border: '1px solid #dcdfe3', borderRadius: '6px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', padding: '5px', display: 'flex', flexDirection: 'column', width: '120px', zIndex: 101 }}>
                              <button onClick={(e) => startEditing(e, chat)} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px', fontSize: '13px', cursor: 'pointer', borderRadius: '4px', color: '#1f1f1f' }}><Edit2 size={14} /> Rename</button>
                              <button onClick={(e) => deleteChat(e, chat.id)} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px', fontSize: '13px', cursor: 'pointer', borderRadius: '4px', color: '#ff4d4d' }}><Trash2 size={14} /> Delete</button>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          <div style={{ borderTop: '1px solid #dcdfe3', paddingTop: '15px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px',color: '#1f1f1f', fontSize: '14px', padding: '8px', fontWeight: 'bold' }}>
              <User size={18} color="#5f6368" /> {userRole === 'admin' ? 'Admin User' : userRole === 'faculty' ? 'Faculty User' : 'Student User'}
            </div>
            
            {/* RESTORED ADMIN MANAGE USERS BUTTON */}
            {userRole === 'admin' && (
              <button onClick={() => setShowAdminPanel(true)} style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'none', border: 'none', color: '#1f1f1f', cursor: 'pointer', fontSize: '14px', padding: '8px', textAlign: 'left', borderRadius: '6px' }} onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#e1e5ea'} onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                <Users size={18} /> Manage Users
              </button>
            )}

            <button onClick={handleLogout} style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'none', border: 'none', color: '#ff4d4d', cursor: 'pointer', fontSize: '14px', padding: '8px', textAlign: 'left', borderRadius: '6px' }} onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#fce8e6'} onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
              <LogOut size={18} /> Logout
            </button>
          </div>
        </div>
      )}

      {/* ================= MANAGE CLASS ROSTER MODAL ================= */}
      {showRosterModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: '#fff', width: '500px', maxHeight: '80vh', borderRadius: '12px', padding: '25px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)', display: 'flex', flexDirection: 'column' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid #e1e5ea', paddingBottom: '15px' }}>
              <div>
                <h2 style={{ margin: 0, color: '#1f1f1f', display: 'flex', alignItems: 'center', gap: '10px' }}><UserCheck size={24} color="#007bff" /> Class Roster</h2>
                <p style={{ margin: '5px 0 0 0', color: '#5f6368', fontSize: '14px' }}>{currentSubject?.name}</p>
              </div>
              <button onClick={() => setShowRosterModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#5f6368' }}><X size={24} /></button>
            </div>
            
            <div style={{ overflowY: 'auto', flex: 1 }}>
              {sortedClassStudents.length === 0 ? (
                <p style={{ textAlign: 'center', color: '#888' }}>No students enrolled yet.</p>
              ) : (
                // Use the NEW sorted array instead of classStudents
                sortedClassStudents.map((student, index) => {
                  
                  const myUserId = parseInt(localStorage.getItem('user_id') || 0);
                  
                  // LOGIC 1: Is this my own row?
                  const isMe = student.id === myUserId;
                  
                  // LOGIC 2: Can I remove this person?
                  // An Admin can remove ANYONE (except themselves).
                  // A Faculty member can only remove STUDENTS (if they own the class).
                  const canRemove = 
                    !isMe && (
                      userRole === 'admin' || 
                      (userRole === 'faculty' && currentSubject?.faculty_id === myUserId && student.role !== "instructor")
                    );

                  return (
                    <div key={index} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', borderBottom: '1px solid #f0f0f0', backgroundColor: isMe ? '#f8f9fa' : 'transparent' }}>
                      
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span style={{ color: '#1f1f1f', fontWeight: isMe ? 'bold' : '500' }}>
                          {student.username} {isMe && "(You)"}
                        </span>
                        {/* Add the Crown Badge for the Instructor! */}
                        {student.role === "instructor" && (
                          <span style={{ backgroundColor: '#fff3cd', color: '#856404', padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 'bold', border: '1px solid #ffeeba' }}>
                            Instructor 👑
                          </span>
                        )}
                      </div>
                      
                      <div style={{ display: 'flex', gap: '10px' }}>
                        {/* RENDER EXIT BUTTON (If it's me) */}
                        {isMe && (
                          <button 
                            onClick={handleLeaveClass} 
                            style={{ color: '#5f6368', backgroundColor: '#e1e5ea', border: 'none', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}
                            onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#d3d7dc'} 
                            onMouseOut={(e) => e.currentTarget.style.backgroundColor = '#e1e5ea'}
                          >
                            Exit Class
                          </button>
                        )}

                        {/* RENDER REMOVE BUTTON (If I have permission) */}
                        {canRemove && (
                          <button 
                            onClick={() => removeUserFromClass(student)} 
                            style={{ color: '#ff4d4d', backgroundColor: '#fce8e6', border: 'none', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}
                            onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#fad2cf'} 
                            onMouseOut={(e) => e.currentTarget.style.backgroundColor = '#fce8e6'}
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ================= MAIN CONTENT */}

      {/* ================= MAIN CONTENT AREA ================= */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: activeView === 'dashboard' ? '#f0f4f9' : '#ffffff', position: 'relative' }}>
        
        <div style={{ height: '60px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', backgroundColor: '#ffffff', zIndex: 10, borderBottom: '1px solid #e1e5ea' }}>
          
          {/* LEFT SIDE: Menu, Back Button, and Title */}
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '5px', borderRadius: '50%' }}><Menu size={24} color="#5f6368" /></button>
            
            {activeView === 'classroom' && (
              <button onClick={goDashboard} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'none', border: 'none', cursor: 'pointer', marginLeft: '15px', color: '#007bff', fontWeight: 'bold' }}>
                <ArrowLeft size={18} /> Back to Classes
              </button>
            )}

            <h2 style={{ marginLeft: activeView === 'classroom' ? '15px' : '15px', fontSize: '18px', color: '#1f1f1f', margin: 0 }}>
              {activeView === 'dashboard' ? 'My Dashboard' : activeView === 'global' ? 'KnowCamp AI' : `${currentSubject?.name}`}
            </h2>
          </div>

          {/* RIGHT SIDE: Manage & Delete Buttons */}
          {activeView === 'classroom' && (
            <div style={{ display: 'flex', gap: '10px' }}>
              
              {/* Roster Button (Visible to Everyone) */}
                <button 
                  onClick={() => fetchClassStudents(currentSubject.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', backgroundColor: '#e8f0fe', color: '#1967d2', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}
                >
                  <Users size={18} /> Manage Class
                </button>
              

              {/* NEW DELETE BUTTON (Strict RBAC applied) */}
              {(userRole === 'admin' || (userRole === 'faculty' && currentSubject?.faculty_id === parseInt(localStorage.getItem('user_id') || 0))) && (
                <button 
                  onClick={handleDeleteClass}
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', backgroundColor: '#fce8e6', color: '#d93025', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}
                  onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#fad2cf'} 
                  onMouseOut={(e) => e.currentTarget.style.backgroundColor = '#fce8e6'}
                >
                  <Trash2 size={18} /> Delete Class
                </button>
              )}

            </div>
          )}
        </div>

        {/* --- ORPHANED CLASS BANNER (Faculty AND Admins see this if the class is empty) --- */}
        {activeView === 'classroom' && !currentSubject?.faculty_id && (userRole === 'faculty' || userRole === 'admin') && (
          <div style={{ backgroundColor: '#fff3cd', color: '#856404', padding: '12px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #ffeeba', fontSize: '14px' }}>
            <span style={{ fontWeight: 'bold' }}>⚠️ This class currently has no instructor.</span>
            <button 
              onClick={async () => {
                try {
                  const token = localStorage.getItem('token');
                  await axios.post(`http://127.0.0.1:8000/subjects/${currentSubject.id}/claim`, {}, { headers: { Authorization: `Bearer ${token}` } });
                  alert("You have successfully claimed this class!");
                  
                  // Force React to completely clear the cache and reload
                  window.location.reload(); 
                } catch (err) { alert(err.response?.data?.detail || "Failed to claim class."); }
              }}
              style={{ backgroundColor: '#ffc107', color: '#212529', border: 'none', padding: '6px 16px', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' }}
            >
              Claim Class
            </button>
          </div>
        )}
        
        {/* --- DASHBOARD VIEW --- */}
        {activeView === 'dashboard' && (
          <div style={{ padding: '40px', flex: 1, overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '30px', maxWidth: '1000px', margin: '0 auto 30px auto' }}>
              <h1 style={{ fontSize: '2rem', color: '#1f1f1f', margin: 0 }}>My Classes</h1>
              
              {/* Group the buttons in a flex container so they sit side-by-side */}
              <div style={{ display: 'flex', gap: '15px' }}>
                
                {/* 1. CREATE BUTTON: Only for Admin and Faculty */}
                {(userRole?.toLowerCase() === 'admin' || userRole?.toLowerCase() === 'faculty') && (
                  <button onClick={() => setShowCreateClassModal(true)} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', backgroundColor: '#007bff', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}>
                    <PlusCircle size={20} /> Create Class
                  </button>
                )}

                {/* 2. JOIN BUTTON: For everyone EXCEPT Admin */}
                {userRole?.toLowerCase() !== 'admin' && (
                  <button onClick={() => setShowJoinClassModal(true)} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', backgroundColor: '#28a745', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}>
                    <LogIn size={20} /> Join Class
                  </button>
                )}
                
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '25px', maxWidth: '1000px', margin: '0 auto' }}>
              {subjects.map((subject) => (
                <div key={subject.id} onClick={() => openClassroom(subject)} style={{ backgroundColor: '#ffffff', borderRadius: '12px', overflow: 'hidden', border: '1px solid #e1e5ea', cursor: 'pointer', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ backgroundColor: '#1967d2', height: '100px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
                    <h2 style={{ color: '#ffffff', margin: 0, fontSize: '1.2rem' }}>{subject.name}</h2>
                    
                    {/* The new flex container for Year and Creator Name */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '5px' }}>
                      <p style={{ color: '#e8f0fe', margin: 0, fontSize: '0.9rem' }}>{subject.year}</p>
                      <p style={{ color: '#a8c7fa', margin: 0, fontSize: '0.8rem', fontStyle: 'italic' }}>
                        Created by: {subject.creator_name || "Admin"}
                      </p>
                    </div>
                  </div>
                  <div style={{ padding: '15px 20px', backgroundColor: '#fff', borderTop: '1px solid #f0f4f9', display: 'flex', alignItems: 'center' }}>
                    {(userRole === 'admin' || userRole === 'faculty') && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: '#f8f9fa', padding: '6px 12px', borderRadius: '6px', border: '1px solid #e1e5ea' }}>
                        <Hash size={14} color="#5f6368" /> 
                        <span style={{ color: '#5f6368', fontSize: '0.85rem' }}>
                          Code: <strong style={{ color: '#1f1f1f', letterSpacing: '1px' }}>{subject.invite_code}</strong>
                        </span>
                        
                        {/* The Smart Copy Button */}
                        <button 
                          onClick={(e) => handleCopyCode(e, subject.invite_code, subject.id)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px', display: 'flex', alignItems: 'center', color: copiedSubjectId === subject.id ? '#10b981' : '#007bff', marginLeft: '5px' }}
                          title="Copy Invite Code"
                        >
                          {copiedSubjectId === subject.id ? <Check size={16} /> : <Copy size={16} />}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* --- CHAT INTERFACE (Used for Global AND Classrooms) --- */}
        {activeView !== 'dashboard' && (
          <>
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{ width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {/* --- 🎯 UPGRADED FOCUS MODE BANNER WITH QUICK ACTIONS --- */}
                {activeDocument && activeView !== 'dashboard' && (
                  <div style={{ backgroundColor: '#e8f0fe', color: '#1967d2', padding: '15px', fontSize: '13px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', borderBottom: '1px solid #dcdfe3', borderRadius: '8px' }}>
                    
                    {/* Top Row: Info and Exit */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px', fontWeight: 'bold' }}>
                      <span>🎯 Focus Mode: Chatting exclusively with "{activeDocument.filename}"</span>
                      <button onClick={() => setActiveDocument(null)} style={{ background: '#fff', border: '1px solid #1967d2', color: '#1967d2', borderRadius: '6px', cursor: 'pointer', padding: '4px 12px', fontSize: '12px', fontWeight: 'bold' }}>
                        Exit Focus
                      </button>
                    </div>

                    {/* Bottom Row: The Magic Buttons */}
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <button 
                        disabled={isLoading} 
                        onClick={() => triggerQuickAction("Extract the 5 most important concepts and definitions from this document.")} 
                        style={{ background: '#1967d2', color: '#fff', border: 'none', borderRadius: '20px', padding: '8px 16px', fontSize: '12px', cursor: isLoading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '5px', fontWeight: 'bold', opacity: isLoading ? 0.6 : 1 }}
                      >
                        ✨ Extract Key Concepts
                      </button>
                      
                      <button 
                        disabled={isLoading} 
                        onClick={() => triggerQuickAction("Generate a 3-question multiple choice quiz based entirely on this document. Provide the answer key at the very end.")} 
                        style={{ background: '#1967d2', color: '#fff', border: 'none', borderRadius: '20px', padding: '8px 16px', fontSize: '12px', cursor: isLoading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '5px', fontWeight: 'bold', opacity: isLoading ? 0.6 : 1 }}
                      >
                        📝 Generate Practice Quiz
                      </button>
                    </div>

                  </div>
                )}
                {messages.length === 0 && (
                  <div style={{ textAlign: 'center', color: '#888', marginTop: '100px' }}>
                    <h1 style={{ fontSize: '2.5rem', color: '#c4c7c5', margin: '0 0 10px 0' }}>{activeView === 'global' ? 'Hello, ' + userRole : currentSubject?.name}</h1>
                    <p style={{ fontSize: '1.2rem' }}>{activeView === 'global' ? 'Ask questions about the campus.' : 'Ask questions about materials in this class.'}</p>
                  </div>
                )}
                {messages.map((msg, index) => (
                  <div key={index} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', backgroundColor: msg.role === 'user' ? '#f0f4f9' : 'transparent', color: '#1f1f1f', padding: msg.role === 'user' ? '12px 20px' : '0', borderRadius: '20px', maxWidth: '85%' }}>
                    <div style={{ fontSize: '1rem', lineHeight: '1.6' }}><ReactMarkdown>{msg.content || ""}</ReactMarkdown></div>
                    {/* NEW RICH SOURCES RENDERING */}
                    {/* NEW RICH SOURCES RENDERING - WITH CLICKABLE LINKS */}
                    {msg.role === 'ai' && msg.sources?.length > 0 && (
                      <div style={{ marginTop: '10px', fontSize: '12px', color: '#5f6368', borderTop: '1px solid #e0e0e0', paddingTop: '8px' }}>
                        <strong>📄 Sources:</strong>
                        <ul style={{ listStyle: 'none', padding: 0, margin: '5px 0 0 0', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {msg.sources.map((src, i) => {
                            // 1. Extract the actual filename string
                            const rawFileNameStr = src.filename || src;
                            
                            // 2. THE FIX: Chop off the "uploads/" folder path!
                            const cleanFileName = rawFileNameStr.split('/').pop().split('\\').pop();
                            
                            return (
                              <li key={i} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                {activeView === 'global' && src.classname && src.classname !== 'Global Docs' ? (
                                  <>
                                    <span style={{ backgroundColor: '#e8f0fe', color: '#1967d2', padding: '2px 6px', borderRadius: '4px', fontWeight: 'bold' }}>
                                      {src.classname}
                                    </span>
                                    <span style={{ color: '#5f6368' }}>/</span>
                                    
                                    {/* CLICKABLE LINK (Global View) - NOW USES cleanFileName */}
                                    <a 
                                      href={`http://127.0.0.1:8000/files/${cleanFileName}`} 
                                      target="_blank" 
                                      rel="noopener noreferrer"
                                      style={{ color: '#1a0dab', textDecoration: 'none' }}
                                      onMouseOver={(e) => e.target.style.textDecoration = 'underline'}
                                      onMouseOut={(e) => e.target.style.textDecoration = 'none'}
                                    >
                                      {cleanFileName}
                                    </a>
                                  </>
                                ) : (
                                  /* CLICKABLE LINK (Class View / Global Docs) - NOW USES cleanFileName */
                                  <a 
                                    href={`http://127.0.0.1:8000/files/${cleanFileName}`} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    style={{ color: '#1a0dab', textDecoration: 'none' }}
                                    onMouseOver={(e) => e.target.style.textDecoration = 'underline'}
                                    onMouseOut={(e) => e.target.style.textDecoration = 'none'}
                                  >
                                    {cleanFileName}
                                  </a>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
                {isLoading && <div style={{ color: '#888', display: 'flex', alignItems: 'center', gap: '8px' }}><Loader2 className="animate-spin" size={18} color="#007bff" /> Thinking...</div>}
                <div ref={messagesEndRef} />
              </div>
            </div>

            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              
              {/* --- 🧠 AI MODE TOGGLE --- */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px', marginBottom: '15px', padding: '10px 20px', backgroundColor: '#f8f9fa', borderRadius: '12px', border: '1px solid #e1e5ea' }}>
                <span style={{ fontSize: '13px', fontWeight: 'bold', color: !aiMode ? '#1967d2' : '#5f6368', transition: 'color 0.3s' }}>
                  📚 Strict Doc Mode
                </span>
                
                {/* Custom CSS Toggle Switch */}
                <div 
                  onClick={() => setAiMode(!aiMode)}
                  style={{ width: '46px', height: '24px', backgroundColor: aiMode ? '#10b981' : '#1967d2', borderRadius: '12px', position: 'relative', cursor: 'pointer', transition: 'background-color 0.3s' }}
                >
                  <div style={{ width: '18px', height: '18px', backgroundColor: '#fff', borderRadius: '50%', position: 'absolute', top: '3px', left: aiMode ? '25px' : '3px', transition: 'left 0.3s', boxShadow: '0 2px 4px rgba(0,0,0,0.2)' }} />
                </div>

                <span style={{ fontSize: '13px', fontWeight: 'bold', color: aiMode ? '#10b981' : '#5f6368', transition: 'color 0.3s' }}>
                  🧠 General AI Mode
                </span>
              </div>
              {/* ------------------------ */}

              <form onSubmit={sendMessage} style={{ display: 'flex', gap: '10px', width: '100%', maxWidth: '800px', backgroundColor: '#f0f4f9', borderRadius: '24px', padding: '8px 16px' }}>
                <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(e); } }} placeholder={`Ask ${activeView === 'global' ? 'Global AI' : currentSubject?.name}...`} rows="1" style={{ flex: 1, padding: '12px 0', border: 'none', outline: 'none', color: '#1f1f1f', fontSize: '1rem', fontFamily: 'inherit', backgroundColor: 'transparent', resize: 'none' }} disabled={isLoading} />
                <button type="submit" disabled={isLoading || !input.trim()} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#007bff', padding: '10px' }}><Send size={20} /></button>
              </form>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ChatComponent;