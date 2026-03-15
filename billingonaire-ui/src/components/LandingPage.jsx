import React from 'react';
import { Container, Row, Col, Button } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import '../styles/professional.css';

const LandingPage = () => {
  return (
    <div className="landing-page">
      {/* Hero Section */}
      <section className="hero-section">
        <Container>
          <Row className="align-items-center">
            <Col lg={6} className="hero-content">
              <h1 className="hero-title">
                Professional Legal Billing Management
              </h1>
              <p className="hero-subtitle">
                Streamline your court matter tracking, AGP assignments, and billing generation with our comprehensive legal practice management system.
              </p>
              <div className="d-flex gap-3 flex-wrap">
                <Button
                  as={Link}
                  to="/login"
                  className="btn-professional btn-primary btn-lg"
                  style={{ minWidth: '150px' }}
                >
                  Get Started
                </Button>
                <Button
                  variant="outline-light"
                  size="lg"
                  className="btn-professional btn-outline"
                  style={{ minWidth: '150px' }}
                >
                  Learn More
                </Button>
              </div>
            </Col>
            <Col lg={6} className="text-center">
              <div className="hero-illustration">
                <div
                  style={{
                    width: '100%',
                    height: '300px',
                    background: 'rgba(255, 255, 255, 0.1)',
                    borderRadius: '1rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(255, 255, 255, 0.2)'
                  }}
                >
                  <div style={{ fontSize: '4rem', color: 'rgba(255, 255, 255, 0.8)' }}>
                    ⚖️
                  </div>
                </div>
              </div>
            </Col>
          </Row>
        </Container>
      </section>

      {/* Features Section */}
      <section style={{ padding: '4rem 0', backgroundColor: 'var(--gray-50)' }}>
        <Container>
          <Row>
            <Col lg={12} className="text-center mb-5">
              <h2 style={{ fontSize: '2.5rem', fontWeight: '700', color: 'var(--gray-900)', marginBottom: '1rem' }}>
                Powerful Features for Legal Professionals
              </h2>
              <p style={{ fontSize: '1.125rem', color: 'var(--gray-600)', maxWidth: '600px', margin: '0 auto' }}>
                Everything you need to manage court matters, track AGP assignments, and generate professional billing reports.
              </p>
            </Col>
          </Row>

          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon">
                📄
              </div>
              <h3 className="feature-title">Daily Board Processing</h3>
              <p className="feature-description">
                Upload and automatically process daily court board files to extract case details, AGP assignments, and matter information with intelligent parsing.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">
                📊
              </div>
              <h3 className="feature-title">Advanced Analytics</h3>
              <p className="feature-description">
                Get comprehensive insights with weekly status reports, AGP-wise statistics, and monthly averages to track your practice performance.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">
                🏛️
              </div>
              <h3 className="feature-title">Court Order Integration</h3>
              <p className="feature-description">
                Automatically fetch and classify high court orders as Adjournment, Disposal, or Heard & Adjourned with intelligent document processing.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">
                💼
              </div>
              <h3 className="feature-title">AGP Management</h3>
              <p className="feature-description">
                Efficiently track and manage Additional Government Pleader assignments with detailed matter categorization and billing tracking.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">
                🔐
              </div>
              <h3 className="feature-title">Secure & Reliable</h3>
              <p className="feature-description">
                Enterprise-grade security with Firebase authentication and cloud storage ensures your sensitive legal data is always protected.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">
                📱
              </div>
              <h3 className="feature-title">Responsive Design</h3>
              <p className="feature-description">
                Access your legal practice management system from any device with our fully responsive, mobile-friendly interface.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* CTA Section */}
      <section style={{ padding: '4rem 0', backgroundColor: 'var(--white)' }}>
        <Container>
          <Row>
            <Col lg={12} className="text-center">
              <div className="card-professional" style={{ maxWidth: '600px', margin: '0 auto' }}>
                <div className="card-body" style={{ padding: '3rem' }}>
                  <h2 style={{ fontSize: '2rem', fontWeight: '700', color: 'var(--gray-900)', marginBottom: '1rem' }}>
                    Ready to Streamline Your Legal Practice?
                  </h2>
                  <p style={{ fontSize: '1.125rem', color: 'var(--gray-600)', marginBottom: '2rem' }}>
                    Join legal professionals who trust Billingonaire for their court matter management and billing needs.
                  </p>
                  <Button
                    as={Link}
                    to="/login"
                    className="btn-professional btn-primary btn-lg"
                    style={{ minWidth: '200px', padding: '0.75rem 2rem' }}
                  >
                    Start Your Free Trial
                  </Button>
                </div>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </div>
  );
};

export default LandingPage;
