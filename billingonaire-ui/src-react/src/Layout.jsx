import React, { useEffect, useState } from 'react';
import { Container, Navbar, Nav, Button, Row, Col } from 'react-bootstrap';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom';
import { auth } from './lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import Dashboard from './Dashboard';
import Table from './Table';
import Upload from './Upload';
import Login from './Login';

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
    navigate('/login');
  };

  const isLoginPage = location.pathname === '/login';

  useEffect(() => {
    if (!user && !isLoginPage) {
      navigate('/login');
    }
  }, [user, isLoginPage, navigate]);

  return (
    <div className="d-flex flex-column min-vh-100">
      {/* Header/Navbar - full width */}
      <div style={{ width: '100%' }}>
        <Navbar bg="primary" variant="dark" expand="md" sticky="top">
          <Container fluid>
            <Navbar.Brand as={Link} to={user ? "/dashboard" : "/login"}>
              Billingonaire
            </Navbar.Brand>
            {user && !isLoginPage && (
              <>
                <Navbar.Toggle aria-controls="main-navbar-nav" />
                <Navbar.Collapse id="main-navbar-nav">
                  <Nav className="me-auto">
                    <Nav.Link as={Link} to="/dashboard">Dashboard</Nav.Link>
                    <Nav.Link as={Link} to="/table">Table</Nav.Link>
                    <Nav.Link as={Link} to="/upload">Upload</Nav.Link>
                  </Nav>
                  <Button variant="outline-light" onClick={handleLogout}>
                    Logout
                  </Button>
                </Navbar.Collapse>
              </>
            )}
          </Container>
        </Navbar>
      </div>

      {/* Main Content */}
      <div className="flex-grow-1 d-flex align-items-center justify-content-center py-4" style={{ width: '100%' }}>
        <Container>
          <Row className="justify-content-center">
            <Col xs={12} sm={10} md={8} lg={6} xl={5}>
              {(user || isLoginPage) ? children : null}
            </Col>
          </Row>
        </Container>
      </div>

      {/* Footer - full width */}
      <div style={{ width: '100%' }}>
        <footer className="bg-light text-center text-muted py-3 mt-auto border-top">
          &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
        </footer>
      </div>
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
