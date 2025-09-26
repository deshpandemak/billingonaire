import React, { useEffect, useState } from 'react';
import { Container, Navbar, Nav, Button } from 'react-bootstrap';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import Dashboard from './Dashboard';
import Table from './Table';
import Upload from './Upload';
import OrderManagement from './OrderManagement';
import OrderAnalysis from './OrderAnalysis';
import UserProfile from './UserProfile';
import AdminUserManagement from './AdminUserManagement';
import Login from './Login';
import LandingPage from './components/LandingPage';
import './styles/professional.css';

const Layout = ({ children }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [userProfile, setUserProfile] = useState(null);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setUser(user);
      if (user) {
        try {
          // Get user profile to check role
          const response = await fetch('/api/user/profile', {
            headers: {
              'Authorization': `Bearer ${await user.getIdToken()}`
            }
          });
          if (response.ok) {
            const profile = await response.json();
            console.log('✅ User profile loaded:', profile);
            setUserProfile(profile);
          } else {
            console.error('❌ Failed to load user profile, response not ok:', response.status);
            // Set basic profile structure for fallback
            setUserProfile({ email: user.email, role: 'user' });
          }
        } catch (error) {
          console.error('❌ Error loading user profile:', error);
          // Set basic profile structure for fallback
          setUserProfile({ email: user.email, role: 'user' });
        }
      } else {
        setUserProfile(null);
      }
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
                  {userProfile?.role === 'admin' && (
                    <Nav.Link 
                      as={Link} 
                      to="/admin/users"
                      className={location.pathname === '/admin/users' ? 'active' : ''}
                    >
                      User Management
                    </Nav.Link>
                  )}
                  <Nav.Link 
                    as={Link} 
                    to="/orders"
                    className={location.pathname === '/orders' ? 'active' : ''}
                  >
                    Order Management
                  </Nav.Link>
                  <Nav.Link 
                    as={Link} 
                    to="/order-analysis"
                    className={location.pathname === '/order-analysis' ? 'active' : ''}
                  >
                    AI Order Analysis
                  </Nav.Link>
                  <Nav.Link 
                    as={Link} 
                    to="/profile"
                    className={location.pathname === '/profile' ? 'active' : ''}
                  >
                    My Profile
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
        <Route path="/orders" element={<OrderManagement />} />
        <Route path="/order-analysis" element={<OrderAnalysis />} />
        <Route path="/profile" element={<UserProfile />} />
        <Route path="/admin/users" element={<AdminUserManagement />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  </Router>
);

export default App;
