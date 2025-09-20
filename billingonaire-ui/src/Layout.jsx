import React, { useEffect, useState } from 'react';
import { Container, Navbar, Nav, Button } from 'react-bootstrap';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import Dashboard from './Dashboard';
import Table from './Table';
import Upload from './Upload';
import Login from './Login';
import LandingPage from './components/LandingPage';
import './styles/professional.css';

const Layout = ({ children }) => {
  const location = useLocation();
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
    navigate('/');
  };

  const isLoginPage = location.pathname === '/login';
  const isLandingPage = location.pathname === '/';
  const isPublicPage = isLoginPage || isLandingPage;

  useEffect(() => {
    if (!user && !isPublicPage) {
      navigate('/login');
    }
  }, [user, isPublicPage, navigate]);

  // For login page, render without navigation
  if (isLoginPage) {
    return children;
  }

  // For landing page, show simplified navigation
  if (isLandingPage) {
    return (
      <>
        <Navbar className="navbar-professional" expand="lg" sticky="top">
          <Container>
            <Navbar.Brand as={Link} to="/" className="navbar-brand">
              ⚖️ Billingonaire
            </Navbar.Brand>
            <Navbar.Toggle aria-controls="landing-navbar-nav" />
            <Navbar.Collapse id="landing-navbar-nav">
              <Nav className="ms-auto">
                <Button 
                  as={Link} 
                  to="/login" 
                  className="btn-professional btn-primary"
                >
                  Sign In
                </Button>
              </Nav>
            </Navbar.Collapse>
          </Container>
        </Navbar>
        {children}
      </>
    );
  }

  // For authenticated pages, show full navigation
  return (
    <>
      <Navbar className="navbar-professional" expand="lg" sticky="top">
        <Container>
          <Navbar.Brand as={Link} to="/dashboard" className="navbar-brand">
            ⚖️ Billingonaire
          </Navbar.Brand>
          {user && (
            <>
              <Navbar.Toggle aria-controls="main-navbar-nav" />
              <Navbar.Collapse id="main-navbar-nav">
                <Nav className="me-auto">
                  <Nav.Link 
                    as={Link} 
                    to="/dashboard"
                    className={location.pathname === '/dashboard' ? 'active' : ''}
                  >
                    Dashboard
                  </Nav.Link>
                  <Nav.Link 
                    as={Link} 
                    to="/upload"
                    className={location.pathname === '/upload' ? 'active' : ''}
                  >
                    Upload Files
                  </Nav.Link>
                  <Nav.Link 
                    as={Link} 
                    to="/table"
                    className={location.pathname === '/table' ? 'active' : ''}
                  >
                    Search Data
                  </Nav.Link>
                </Nav>
                <div className="d-flex align-items-center gap-3">
                  <span style={{ color: 'var(--gray-600)', fontSize: '0.875rem' }}>
                    {user.email}
                  </span>
                  <Button 
                    className="btn-professional btn-secondary"
                    onClick={handleLogout}
                  >
                    Sign Out
                  </Button>
                </div>
              </Navbar.Collapse>
            </>
          )}
        </Container>
      </Navbar>

      {/* Main Content */}
      <main style={{ minHeight: 'calc(100vh - 120px)', backgroundColor: 'var(--gray-50)' }}>
        {user ? children : null}
      </main>

      {/* Footer */}
      <footer style={{ 
        backgroundColor: 'var(--white)', 
        borderTop: '1px solid var(--gray-200)',
        padding: '1.5rem 0',
        marginTop: 'auto'
      }}>
        <Container>
          <div className="text-center">
            <p style={{ 
              color: 'var(--gray-600)', 
              margin: 0, 
              fontSize: '0.875rem' 
            }}>
              &copy; {new Date().getFullYear()} Billingonaire. Professional Legal Practice Management.
            </p>
          </div>
        </Container>
      </footer>
    </>
  );
};

const App = () => (
  <Router>
    <Layout>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/table" element={<Table />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  </Router>
);

export default App;
