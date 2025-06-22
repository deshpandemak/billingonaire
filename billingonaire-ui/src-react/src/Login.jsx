import React, { useState } from 'react';
import { auth } from './lib/firebase';
import { signInWithEmailAndPassword } from 'firebase/auth';
import { useNavigate } from 'react-router-dom';

const Login = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const login = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await signInWithEmailAndPassword(auth, email, password);
      localStorage.setItem('userEmail', email);
      navigate('/upload');
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="login-container">
      <form onSubmit={login} className="login-form">
        <h2>Login</h2>
        <div>
          <label htmlFor="email">Email</label>
          <input type="email" id="email" value={email} onChange={e => setEmail(e.target.value)} required />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input type="password" id="password" value={password} onChange={e => setPassword(e.target.value)} required />
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit">Login</button>
      </form>
      <style>{`
        .login-container {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #f5f5f5;
        }
        .login-form {
          background: #fff;
          padding: 2rem 2.5rem;
          border-radius: 8px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.08);
          display: flex;
          flex-direction: column;
          min-width: 320px;
        }
        .login-form h2 {
          text-align: center;
          margin-bottom: 1.5rem;
        }
        .login-form input {
          margin-bottom: 1rem;
          padding: 0.5rem;
          border: 1px solid #ccc;
          border-radius: 4px;
        }
        .login-form button {
          padding: 0.5rem;
          border: none;
          border-radius: 4px;
          background-color: #007bff;
          color: white;
          cursor: pointer;
        }
        .login-form button:hover {
          background-color: #0056b3;
        }
        .login-form .error {
          color: #d32f2f;
          margin-bottom: 1rem;
          text-align: center;
        }
      `}</style>
    </div>
  );
};

export default Login;
