import React, { useState, useEffect, useCallback } from 'react';
import { Alert, Badge, Button, Spinner } from 'react-bootstrap';
import { authenticatedFetchJSON } from '../lib/api';

/**
 * Roadmap #9: "ask, don't silently threshold" on ambiguous AGP name
 * matches. A match that fell just short of the auto-accept confidence
 * threshold used to be discarded with no trace at all -- this surfaces it
 * as a one-tap "is this you?" instead of a matter assignment quietly
 * going missing. Renders nothing when there's nothing pending, so it
 * never adds noise to a dashboard everyone sees.
 */
const PendingMatterConfirmations = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(null);
  const [error, setError] = useState('');

  const fetchPending = useCallback(async () => {
    try {
      const data = await authenticatedFetchJSON('/user-matters/pending-confirmations');
      setItems(data.pending || []);
    } catch {
      // Non-critical: a personal "is this you?" prompt failing to load
      // shouldn't put an error banner on a dashboard everyone sees.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  const respond = async (item, action) => {
    const key = item.id;
    setResolving(key);
    setError('');
    try {
      await authenticatedFetchJSON(`/user-matters/pending-confirmations/${encodeURIComponent(key)}/${action}`, {
        method: 'POST',
      });
      setItems(prev => prev.filter(i => i.id !== key));
    } catch (e) {
      setError(e.message || `Failed to ${action} this match.`);
    } finally {
      setResolving(null);
    }
  };

  if (loading || items.length === 0) return null;

  return (
    <div className="dashboard-section">
      <div
        style={{
          padding: '0.9rem 1rem',
          background: 'rgba(59,130,246,0.06)',
          border: '1px solid var(--primary-color, #3b82f6)',
          borderRadius: 'var(--radius-md)',
        }}
      >
        <strong style={{ fontSize: '0.92rem' }}>
          Is this you? {items.length} possible {items.length > 1 ? 'matters' : 'matter'} found a close-but-not-certain name match.
        </strong>
        {error && <Alert variant="danger" className="mt-2 mb-0 py-1 px-2" style={{ fontSize: '0.82rem' }}>{error}</Alert>}
        <div className="mt-2 d-flex flex-column gap-2">
          {items.map(item => (
            <div key={item.id} className="d-flex flex-wrap align-items-center gap-2" style={{ fontSize: '0.85rem' }}>
              <Badge bg="secondary">{item.case_ref || item.case_id}</Badge>
              <span className="text-muted">matched via "{item.matched_text}"</span>
              {resolving === item.id ? (
                <Spinner animation="border" size="sm" />
              ) : (
                <>
                  <Button size="sm" variant="outline-success" onClick={() => respond(item, 'confirm')}>
                    Yes, that's me
                  </Button>
                  <Button size="sm" variant="outline-secondary" onClick={() => respond(item, 'reject')}>
                    Not me
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default PendingMatterConfirmations;
