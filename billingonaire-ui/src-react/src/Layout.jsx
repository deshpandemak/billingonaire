import React, { useEffect, useState } from 'react';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { useNavigate } from 'react-router-dom';

const Layout = ({ children }) => {
  const navigate = useNavigate();
  const [userEmail, setUserEmail] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (user) {
        setUserEmail(user.email);
        setIsAuthenticated(true);
      } else {
        setIsAuthenticated(false);
        navigate('/login');
      }
    });
    return () => unsubscribe();
  }, [navigate]);

  const logout = async () => {
    try {
      await signOut(auth);
      navigate('/login');
    } catch (error) {
      console.error('Logout failed', error);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div>Billingonaire</div>
        {isAuthenticated && (
          <>
            <div className="user-email">{userEmail}</div>
            <button onClick={logout}>Logout</button>
          </>
        )}
      </header>
      {isAuthenticated && (
        <nav className="nav">
          <ul>
            <li><a href="/upload">Upload Board</a></li>
            <li><a href="/table">Search Board</a></li>
          </ul>
        </nav>
      )}
      <main className="main">{children}</main>
      <footer className="footer">
        <p>© billingonaire</p>
      </footer>
      <style>{`
        .app { display: flex; flex-direction: column; min-height: 100vh; }
        main { flex: 1; display: flex; flex-direction: column; padding: 1rem; width: 100%; max-width: 64rem; margin: 0 auto; box-sizing: border-box; }
        footer { display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 12px; }
        .header { background-color: #f8f8f8; border-bottom: 1px solid #ccc; }
      `}</style>
    </div>
  );
};

export default Layout;
