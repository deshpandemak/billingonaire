import React, { useEffect, useState } from 'react';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import Dashboard from './Dashboard';
import Table from './Table';
import Upload from './Upload';
import Login from './Login';

const Layout = ({ children }) => {
  const location = useLocation();
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

  // Only show menu/header if logged in and not on login page
  const isLoginPage = location.pathname === '/login';

  return (
    <div className="app">
      {user && !isLoginPage && (
        <>
          <header className="header">
            <div>Billingonaire</div>
            <div className="user-email">{user.email}</div>
            <button onClick={handleLogout} style={{ float: 'right', background: '#d32f2f', color: '#fff', border: 'none', borderRadius: 4, padding: '0.4rem 1rem', cursor: 'pointer', margin: '1rem' }}>Logout</button>
          </header>
          <nav className="nav">
            <ul>
              <li><Link to="/dashboard">Dashboard</Link></li>
              <li><Link to="/table">Table</Link></li>
              <li><Link to="/upload">Upload Board</Link></li>
            </ul>
          </nav>
          <main className="main">{children}</main>
          <footer className="footer">
            <p>© billingonaire</p>
          </footer>
        </>
      )}
      {user || isLoginPage ? children : <p style={{ color: '#d32f2f', textAlign: 'center', marginTop: '2rem' }}>Please log in to access the app.</p>}
      <style>{`
        .app { display: flex; flex-direction: column; min-height: 100vh; }
        main { flex: 1; display: flex; flex-direction: column; padding: 1rem; width: 100%; max-width: 64rem; margin: 0 auto; box-sizing: border-box; }
        footer { display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 12px; }
        .header { background-color: #f8f8f8; border-bottom: 1px solid #ccc; }
      `}</style>
    </div>
  );
};

const App = () => (
  <Router>
    <Layout>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/table" element={<Table />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  </Router>
);

export default App;
