import React, { useState } from 'react';
import { auth } from './lib/firebase';
import { signInWithEmailAndPassword } from 'firebase/auth';
import { useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert, Card } from 'react-bootstrap';

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
    <Container
      fluid
      className="d-flex align-items-center justify-content-center min-vh-100 bg-light"
      style={{ padding: 0 }}
    >
      <Row className="w-100 justify-content-center">
        <Col xs={12} sm={10} md={8} lg={5} xl={4}>
          <Card className="shadow-sm" style={{ borderRadius: 12 }}>
            <Card.Body>
              <h2 className="text-center mb-4">Login</h2>
              <Form onSubmit={login}>
                <Form.Group className="mb-3" controlId="email">
                  <Form.Label>Email</Form.Label>
                  <Form.Control
                    type="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                    placeholder="Enter your email"
                    size="lg"
                  />
                </Form.Group>
                <Form.Group className="mb-4" controlId="password">
                  <Form.Label>Password</Form.Label>
                  <Form.Control
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    placeholder="Enter your password"
                    size="lg"
                  />
                </Form.Group>
                {error && <Alert variant="danger" className="text-center">{error}</Alert>}
                <Button
                  variant="primary"
                  type="submit"
                  className="w-100"
                  size="lg"
                  style={{ fontWeight: 500, letterSpacing: 1 }}
                >
                  Login
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
};

export default Login;
