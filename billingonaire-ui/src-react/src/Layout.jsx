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

  // Redirect to login if not logged in and not already on login page
  useEffect(() => {
    if (!user && !isLoginPage) {
      window.location.replace('/login');
    }
  }, [user, isLoginPage]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header/Banner */}
      <header style={{
        background: '#007bff',
        color: '#fff',
        padding: '1rem 0',
        textAlign: 'center',
        fontSize: '2rem',
        fontWeight: 700,
        letterSpacing: '2px',
        boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
        width: '100vw',
        position: 'relative',
        left: '50%',
        right: '50%',
        marginLeft: '-50vw',
        marginRight: '-50vw',
      }}>
        Billingonaire
      </header>
      {/* Main content and menu */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'stretch', justifyContent: 'center', width: '100vw', position: 'relative', left: '50%', right: '50%', marginLeft: '-50vw', marginRight: '-50vw' }}>
        {user && !isLoginPage && (
          <nav style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'center', background: '#f5f5f5', padding: '1rem', borderBottom: '1px solid #ccc', width: '100%' }}>
            <Link to="/dashboard">Dashboard</Link>
            <Link to="/table">Table</Link>
            <Link to="/upload">Upload</Link>
            <button onClick={handleLogout} style={{ marginLeft: 'auto', background: '#d32f2f', color: '#fff', border: 'none', borderRadius: 4, padding: '0.4rem 1rem', cursor: 'pointer' }}>Logout</button>
          </nav>
        )}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%' }}>
          <div style={{
            boxSizing: 'border-box',
            width: '100%',
            maxWidth: '1200px',
            margin: '0 auto',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'stretch',
            minHeight: '60vh',
          }}>
            {user || isLoginPage ? children : null}
          </div>
        </div>
      </div>
      {/* Footer */}
      <footer style={{
        background: '#f5f5f5',
        color: '#333',
        textAlign: 'center',
        padding: '0.75rem 0',
        borderTop: '1px solid #ccc',
        fontSize: '1rem',
        width: '100vw',
        position: 'relative',
        left: '50%',
        right: '50%',
        marginLeft: '-50vw',
        marginRight: '-50vw',
      }}>
        &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
      </footer>
      <style>{`
        @media (max-width: 900px) {
          header, footer {
            font-size: 1.2rem !important;
          }
          nav {
            flex-direction: column !important;
            align-items: flex-start !important;
          }
        }
        @media (max-width: 600px) {
          .dashboard-container, .table-container, .upload-container, .login-container {
            padding: 0.5rem !important;
            min-width: 0 !important;
          }
          header, footer {
            font-size: 1rem !important;
            padding: 0.5rem 0 !important;
          }
        }
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
