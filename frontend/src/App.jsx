import { useState, useEffect } from 'react';
import './App.css'; // You can keep this import if you have other styles
import ChatComponent from './components/ChatComponent';
import AuthComponent from './components/AuthComponent'; 

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      setIsAuthenticated(true);
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role'); 
    setIsAuthenticated(false);
  };

  return (
    // We removed all the div containers, h1 tags, and the old logout button!
    // The empty <> tags just group the components without adding visual boxes.
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