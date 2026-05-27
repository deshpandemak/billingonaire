import React, { useEffect, useState } from 'react';
import { Container, Navbar, Nav, Button, NavDropdown } from 'react-bootstrap';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import Dashboard from './Dashboard';
import Table from './Table';
import Upload from './Upload';
import BillGeneration from './BillGeneration';
import UserProfile from './UserProfile';
import AdminUserManagement from './AdminUserManagement';
import AdminOrderManagement from './AdminOrderManagement';
import ManualReviewQueue from './components/ManualReviewQueue';
import Login from './Login';
import LandingPage from './components/LandingPage';
import './styles/professional.css';
import { getApiUrl, authenticatedFetchJSON } from './lib/api';

const Layout = ({ children }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [userProfile, setUserProfile] = useState(null);
  const [reviewCount, setReviewCount] = useState(0);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setUser(user);
      if (user) {
        try {
          const idToken = await user.getIdToken();
          const response = await fetch(getApiUrl('/user/profile'), {
            headers: { 'Authorization': `Bearer ${idToken}` }
          });
          if (response.ok) {
            const profile = await response.json();
            setUserProfile(profile);
          } else {
            setUserProfile(null);
          }
        } catch {
          setUserProfile(null);
        }
      } else {
        setUserProfile(null);
      }
    });
    return () => unsubscribe();
  }, []);

  // Poll for manual_review_required count (admin only)
  useEffect(() => {
    if (!userProfile || userProfile.role !== 'admin') return;

    const fetchReviewCount = async () => {
      try {
        const data = await authenticatedFetchJSON('/orders/overview-stats');
        const count = data?.status_counts?.manual_review_required
          || data?.lifecycle_counts?.manual_review_required
          || 0;
        setReviewCount(Number(count));
      } catch {
        // non-critical; silently ignore
      }
    };

    fetchReviewCount();
    const interval = setInterval(fetchReviewCount, 60_000);
    return () => clearInterval(interval);
  }, [userProfile]);

  // Keyboard shortcuts: Ctrl+U → upload, Ctrl+B → bills
  useEffect(() => {
    if (!user) return;
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey) {
        if (e.key === 'u' || e.key === 'U') { e.preventDefault(); navigate('/upload'); }
        if (e.key === 'b' || e.key === 'B') { e.preventDefault(); navigate('/bills'); }
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [user, navigate]);

  const handleLogout = async () => {
    await signOut(auth);
    setUser(null);
    navigate('/');
  };

  const isLoginPage = location.pathname === '/login';
  const isLandingPage = location.pathname === '/';
  const isPublicPage = isLoginPage || isLandingPage;

  useEffect(() => {
    if (!user && !isPublicPage) navigate('/login');
  }, [user, isPublicPage, navigate]);

  if (isLoginPage) return children;

  if (isLandingPage) {
    return (
      <>
        <Navbar className="navbar-professional" expand="lg" sticky="top">
          <Container>
            <Navbar.Brand as={Link} to="/" className="navbar-brand">
              Billingonaire
            </Navbar.Brand>
            <Navbar.Toggle aria-controls="landing-navbar-nav" />
            <Navbar.Collapse id="landing-navbar-nav">
              <Nav className="ms-auto">
                <Button as={Link} to="/login" className="btn-professional btn-primary">
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

  const isActive = (...paths) => paths.includes(location.pathname) ? 'active' : '';

  return (
    <>
      <Navbar className="navbar-professional" expand="lg" sticky="top">
        <Container>
          <Navbar.Brand as={Link} to="/dashboard" className="navbar-brand">
            Billingonaire
          </Navbar.Brand>
          {user && (
            <>
              <Navbar.Toggle aria-controls="main-navbar-nav" />
              <Navbar.Collapse id="main-navbar-nav">
                <Nav className="me-auto">
                  <Nav.Link as={Link} to="/dashboard" className={isActive('/dashboard')}>
                    Dashboard
                  </Nav.Link>
                  <Nav.Link as={Link} to="/upload" className={isActive('/upload')} title="Ctrl+U">
                    Upload Files
                  </Nav.Link>
                  <Nav.Link as={Link} to="/table" className={isActive('/table', '/order-center')}>
                    Search & Orders
                  </Nav.Link>
                  <Nav.Link as={Link} to="/bills" className={isActive('/bills')} title="Ctrl+B">
                    Bill Generation
                  </Nav.Link>
                  <Nav.Link as={Link} to="/profile" className={isActive('/profile')}>
                    My Profile
                  </Nav.Link>

                  {userProfile?.role === 'admin' && (
                    <NavDropdown
                      title={
                        <span>
                          Admin
                          {reviewCount > 0 && (
                            <span
                              className="badge bg-danger ms-1"
                              style={{ fontSize: '0.65rem', verticalAlign: 'middle' }}
                              title={`${reviewCount} cases need manual review`}
                            >
                              {reviewCount}
                            </span>
                          )}
                        </span>
                      }
                      id="admin-nav-dropdown"
                      className={isActive('/admin/users', '/admin/orders', '/admin/review')}
                    >
                      <NavDropdown.Item as={Link} to="/admin/users">
                        User Management
                      </NavDropdown.Item>
                      <NavDropdown.Item as={Link} to="/admin/orders">
                        Order Management
                      </NavDropdown.Item>
                      <NavDropdown.Item as={Link} to="/admin/review">
                        Review Queue
                        {reviewCount > 0 && (
                          <span className="badge bg-danger ms-2" style={{ fontSize: '0.65rem' }}>
                            {reviewCount}
                          </span>
                        )}
                      </NavDropdown.Item>
                    </NavDropdown>
                  )}
                </Nav>
                <div className="d-flex align-items-center gap-3">
                  <span style={{ color: 'var(--gray-600)', fontSize: '0.875rem' }}>
                    {user.email}
                  </span>
                  <Button className="btn-professional btn-secondary" onClick={handleLogout}>
                    Sign Out
                  </Button>
                </div>
              </Navbar.Collapse>
            </>
          )}
        </Container>
      </Navbar>

      <main style={{ minHeight: 'calc(100vh - 120px)', backgroundColor: 'var(--gray-50)' }}>
        {user ? children : null}
      </main>

      <footer style={{
        backgroundColor: 'var(--white)',
        borderTop: '1px solid var(--gray-200)',
        padding: '1.5rem 0',
        marginTop: 'auto'
      }}>
        <Container>
          <div className="text-center">
            <p style={{ color: 'var(--gray-600)', margin: 0, fontSize: '0.875rem' }}>
              &copy; {new Date().getFullYear()} Billingonaire — Professional Legal Practice Management.
              <span style={{ marginLeft: '1rem', color: 'var(--gray-400)', fontSize: '0.75rem' }}>
                Ctrl+U Upload · Ctrl+B Bills
              </span>
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
        <Route path="/order-center" element={<Navigate to="/table" replace />} />
        <Route path="/bills" element={<BillGeneration />} />
        <Route path="/profile" element={<UserProfile />} />
        <Route path="/admin/users" element={<AdminUserManagement />} />
        <Route path="/admin/orders" element={<AdminOrderManagement />} />
        <Route path="/admin/review" element={<ManualReviewQueue />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  </Router>
);

export default App;
