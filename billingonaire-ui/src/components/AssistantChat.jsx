import React, { useState, useRef, useEffect } from 'react';
import { Button, Form, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON } from '../lib/api';

/**
 * Roadmap #8: a natural-language front door over data that already exists
 * behind an API call -- "how many cases need my attention", "what would my
 * October bill look like" -- instead of navigating Table, filters, then
 * Bills to find the same answer. Read-only: the backend's tool set (see
 * assistant.py) can only look things up, never save a bill or change a
 * category, and the chat answer says so explicitly when relevant.
 *
 * Mounted globally in Layout so it's available from any authenticated
 * screen, matching the "front door" framing rather than living on one page.
 * Silently disables itself (button never shows) once the backend reports
 * 501 (GEMINI_API_KEY not configured) -- so this never becomes a dead
 * button in front of anyone using an install without a key.
 */
const AssistantChat = () => {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState(true);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages, open]);

  if (!available) return null;

  const send = async (e) => {
    e.preventDefault();
    const text = question.trim();
    if (!text || loading) return;

    const history = messages.map(m => ({ role: m.role, text: m.text }));
    setMessages(prev => [...prev, { role: 'user', text }]);
    setQuestion('');
    setError('');
    setLoading(true);

    try {
      const data = await authenticatedFetchJSON('/assistant/ask', {
        method: 'POST',
        body: JSON.stringify({ question: text, history }),
      });
      setMessages(prev => [...prev, { role: 'assistant', text: data.answer }]);
    } catch (err) {
      if (String(err.message || '').includes('501')) {
        setAvailable(false);
      } else {
        setError(err.message || 'Something went wrong asking that.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <Button
        onClick={() => setOpen(true)}
        aria-label="Open assistant"
        style={{
          position: 'fixed',
          bottom: '1.5rem',
          right: '1.5rem',
          borderRadius: '50%',
          width: '3.25rem',
          height: '3.25rem',
          zIndex: 1050,
          boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
        }}
        className="btn-professional btn-primary d-flex align-items-center justify-content-center p-0"
      >
        <span style={{ fontSize: '1.4rem', lineHeight: 1 }}>💬</span>
      </Button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Billingonaire assistant"
      style={{
        position: 'fixed',
        bottom: '1.5rem',
        right: '1.5rem',
        width: '360px',
        maxWidth: 'calc(100vw - 2rem)',
        height: '480px',
        maxHeight: 'calc(100vh - 3rem)',
        background: 'var(--white, #fff)',
        border: '1px solid var(--gray-200, #e5e7eb)',
        borderRadius: 'var(--radius-md, 8px)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
        zIndex: 1050,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--gray-200, #e5e7eb)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <strong style={{ fontSize: '0.9rem' }}>Ask Billingonaire</strong>
        <Button
          variant="link"
          size="sm"
          onClick={() => setOpen(false)}
          aria-label="Close assistant"
          style={{ padding: 0, textDecoration: 'none', fontSize: '1.1rem', lineHeight: 1 }}
        >
          &times;
        </Button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem 1rem' }}>
        {messages.length === 0 && (
          <p className="text-muted" style={{ fontSize: '0.82rem' }}>
            Ask things like &ldquo;how many cases need my attention&rdquo; or
            &ldquo;what would my October bill look like&rdquo;. Read-only --
            saving or exporting a bill still happens on the Bill Generation
            screen.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className="mb-2"
            style={{
              display: 'flex',
              justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div
              style={{
                maxWidth: '85%',
                padding: '0.5rem 0.75rem',
                borderRadius: '0.75rem',
                fontSize: '0.85rem',
                whiteSpace: 'pre-wrap',
                background: m.role === 'user' ? 'var(--primary-color, #3b82f6)' : 'var(--gray-100, #f3f4f6)',
                color: m.role === 'user' ? '#fff' : 'inherit',
              }}
            >
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="d-flex align-items-center gap-2 text-muted" style={{ fontSize: '0.82rem' }}>
            <Spinner animation="border" size="sm" /> Thinking…
          </div>
        )}
        {error && (
          <p className="text-danger" style={{ fontSize: '0.8rem' }}>{error}</p>
        )}
        <div ref={bottomRef} />
      </div>

      <Form onSubmit={send} className="d-flex gap-2 p-2" style={{ borderTop: '1px solid var(--gray-200, #e5e7eb)' }}>
        <Form.Control
          size="sm"
          type="text"
          placeholder="Ask a question…"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <Button type="submit" size="sm" className="btn-professional btn-primary" disabled={loading || !question.trim()}>
          Send
        </Button>
      </Form>
    </div>
  );
};

export default AssistantChat;
