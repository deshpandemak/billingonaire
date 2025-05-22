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
      <h1>Login</h1>
      <form onSubmit={login}>
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
        .login-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 50vh; max-width: 400px; margin: 0 auto; padding: 1rem; border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .header { font-size: 2.5rem; font-weight: bold; text-align: center; margin-bottom: 2rem; }
        h1 { text-align: center; }
        form { display: flex; flex-direction: column; }
        label { margin-bottom: 0.5rem; }
        input { margin-bottom: 1rem; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; }
        .error { color: red; margin-bottom: 1rem; }
        button { padding: 0.5rem; border: none; border-radius: 4px; background-color: #007bff; color: white; cursor: pointer; }
      `}</style>
    </div>
  );
};

export default Login;
