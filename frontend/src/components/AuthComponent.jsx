import { useState } from 'react';
import axios from 'axios';
// 1. Added the Eye and EyeOff icons
import { Eye, EyeOff, Building2} from 'lucide-react';

const AuthComponent = ({ onLoginSuccess }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [formData, setFormData] = useState({ email: '', password: '', institution_name: '', secretKey: '' });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  
  // 2. Added state to track if password is shown or hidden
  const [showPassword, setShowPassword] = useState(false);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      if (isLogin) {
        const formBody = new URLSearchParams();
        formBody.append('username', formData.email);
        formBody.append('password', formData.password);

        const response = await axios.post('http://127.0.0.1:8000/login', formBody);
        localStorage.setItem('token', response.data.access_token);
        localStorage.setItem('role', response.data.role); 
        localStorage.setItem('user_id', response.data.user_id);
        if(response.data.institution_id) {
            localStorage.setItem('institution_id', response.data.institution_id);
        }
        onLoginSuccess(); 

      } else {
        // REGISTER LOGIC
        await axios.post('http://127.0.0.1:8000/create_user/', {
          username: formData.email,
          password: formData.password,
          institution_name: formData.institution_name,
          secret_key: formData.secretKey || "" 
        });
        
        alert("Registration successful! Please log in.");
        setIsLogin(true);
      }
    } catch (err) {
      console.error(err);
      const errorDetail = err.response?.data?.detail;
      if (typeof errorDetail === 'string') {
          setError(errorDetail);
      } else if (Array.isArray(errorDetail)) {
          setError(errorDetail[0]?.msg || "Validation error occurred.");
      } else {
          setError("Authentication failed. Check your connection.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '400px', margin: '50px auto', padding: '30px', border: '1px solid #ddd', borderRadius: '10px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', fontFamily: 'sans-serif', backgroundColor: '#ffffff' }}>
      <h2 style={{ textAlign: 'center', marginBottom: '20px', color: '#333333' }}>
        {isLogin ? 'Welcome Back to KnowCamp' : 'Create an Account'}
      </h2>

      {error && <div style={{ color: 'red', marginBottom: '15px', textAlign: 'center', fontSize: '14px', padding: '10px', backgroundColor: '#ffe6e6', borderRadius: '5px' }}>{error}</div>}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>

      {/* 3. NEW INSTITUTION FIELD (Only shows on Registration) */}
        {!isLogin && (
          <div style={{ position: 'relative', width: '100%' }}>
            <Building2 color="#888" size={20} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }} />
            <input 
              type="text" 
              name="institution_name" 
              placeholder="Institution Name (e.g., MIT, Stanford)" 
              value={formData.institution_name} 
              onChange={handleChange} 
              required={!isLogin} // Only required when registering
              style={{ padding: '12px 12px 12px 40px', borderRadius: '5px', border: '1px solid #ccc', color: '#333', backgroundColor: '#fff', width: '100%', boxSizing: 'border-box' }} 
            />
          </div>
        )}
        <input 
          type="text" 
          name="email" 
          placeholder="Username" 
          value={formData.email} 
          onChange={handleChange} 
          required 
          style={{ padding: '12px', borderRadius: '5px', border: '1px solid #ccc', color: '#333', backgroundColor: '#fff' }} 
        />
        
        {/* 3. UPDATED PASSWORD FIELD WITH EYE ICON */}
        <div style={{ position: 'relative', width: '100%' }}>
          <input 
            type={showPassword ? "text" : "password"} 
            name="password" 
            placeholder="Password" 
            value={formData.password} 
            onChange={handleChange} 
            required 
            style={{ 
              padding: '12px', 
              borderRadius: '5px', 
              border: '1px solid #ccc', 
              color: '#333', 
              backgroundColor: '#fff', 
              width: '100%', 
              boxSizing: 'border-box' 
            }} 
          />
          <button 
            type="button" 
            onClick={() => setShowPassword(!showPassword)}
            style={{ 
              position: 'absolute', 
              right: '10px', 
              top: '50%', 
              transform: 'translateY(-50%)', 
              background: 'none', 
              border: 'none', 
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center'
            }}
          >
            {showPassword ? <Eye color="#888" size={20}/>: <EyeOff color="#888" size={20} />   }
          </button>
        </div>
        
        {!isLogin && (
          <input 
            type="password" 
            name="secretKey" 
            placeholder="Admin Secret Key (Optional)" 
            value={formData.secretKey} 
            onChange={handleChange} 
            style={{ padding: '12px', borderRadius: '5px', border: '1px dashed #007bff', backgroundColor: '#f0f8ff', color: '#333' }}
          />
        )}
        
        <button type="submit" disabled={isLoading} style={{ padding: '12px', borderRadius: '5px', backgroundColor: '#007bff', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>
          {isLoading ? 'Processing...' : (isLogin ? 'Login' : 'Register')}
        </button>
      </form>

      <p style={{ textAlign: 'center', marginTop: '20px', fontSize: '14px', color: '#666' }}> 
        {isLogin ? "Don't have an account? " : "Already have an account? "}
        <span onClick={() => { setIsLogin(!isLogin); setError(''); }} style={{ color: '#007bff', cursor: 'pointer', textDecoration: 'underline' }}>
          {isLogin ? 'Register here' : 'Login here'}
        </span>
      </p>
    </div>
  );
};

export default AuthComponent;