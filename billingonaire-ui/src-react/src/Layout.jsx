import React, { useEffect, useState } from 'react';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { useNavigate } from 'react-router-dom';

const Layout = ({ children }) => {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setUser(user);
    });
    return () => unsubscribe();
  }, []);

  const handleLogout = async () => {
    await signOut(auth);
    setUser(null);
    window.location.reload();
  };

  return (
    <div className="app">
      {user && (
        <>
          <header className="header">
            <div>Billingonaire</div>
            <div className="user-email">{user.email}</div>
            <button onClick={handleLogout} style={{ float: 'right', background: '#d32f2f', color: '#fff', border: 'none', borderRadius: 4, padding: '0.4rem 1rem', cursor: 'pointer', margin: '1rem' }}>Logout</button>
          </header>
          <nav className="nav">
            <ul>
              <li><a href="/upload">Upload Board</a></li>
              <li><a href="/table">Search Board</a></li>
            </ul>
          </nav>
          <main className="main">{children}</main>
          <footer className="footer">
            <p>© billingonaire</p>
          </footer>
        </>
      )}
      {!user && <p style={{ color: '#d32f2f', textAlign: 'center', marginTop: '2rem' }}>Please log in to access the app.</p>}
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
