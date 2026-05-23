import { useState } from 'react';
import './App.css';
import ChatComponent from './components/ChatComponent';
import AuthComponent from './components/AuthComponent'; 

// Checks if token exists AND is not expired
const isTokenValid = () => {
  const token = localStorage.getItem('token');
  
  // No token at all
  if (!token) return false;
  
  try {
    // Decode the middle part of the JWT
    const payload = JSON.parse(atob(token.split('.')[1]));
    
    // exp is in seconds, Date.now() is milliseconds
    if (payload.exp * 1000 < Date.now()) {
      // Token expired — clean up localStorage
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      localStorage.removeItem('user_id');
      localStorage.removeItem('institution_id');
      return false;
    }
    
    return true;
    
  } catch (e) {
    // Token is malformed or corrupted
    localStorage.clear();
    return false;
  }
};

function App() {
  // Runs isTokenValid() immediately on load
  // instead of useEffect which runs after render
  const [isAuthenticated, setIsAuthenticated] = useState(isTokenValid());

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    localStorage.removeItem('user_id');
    localStorage.removeItem('institution_id');
    setIsAuthenticated(false);
  };

  return (
    <>
      {isAuthenticated ? (
        <ChatComponent onLogout={handleLogout} />
      ) : (
        <AuthComponent onLoginSuccess={() => setIsAuthenticated(true)} />
      )}
    </>
  );
}

export default App;