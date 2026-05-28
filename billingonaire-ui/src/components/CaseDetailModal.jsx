import React, { useEffect, useState } from 'react';
import { Modal, Table, Badge, Spinner, Alert } from 'react-bootstrap';
import { authenticatedFetchJSON, getApiUrl } from '../lib/api';
import { getLifecycleConfig } from '../lib/lifecycleUtils';

const ORDER_CATEGORY_CONFIG = {
  ADJOURNED:           { label: 'Adjourned',         bg: 'warning'  },
  HEARD_AND_ADJOURNED: { label: 'Heard & Adjourned', bg: 'info'     },
  DISPOSED_OFF:        { label: 'Disposed',          bg: 'success'  },
};

const CaseDetailModal = ({ caseRef, show, onHide }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeline, setTimeline] = useState(null);
  const [showEvents, setShowEvents] = useState(false);

  useEffect(() => {
    if (show && caseRef) {
      fetchTimeline();
    } else {
      setTimeline(null);
      setError('');
      setShowEvents(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show, caseRef]);

  const fetchTimeline = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await authenticatedFetchJSON(`/cases/${encodeURIComponent(caseRef)}/timeline`);
      setTimeline(data);
    } catch (e) {
      setError(`Could not load case timeline: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Build the appearances list from the orders array returned by the timeline endpoint.
  const getAppearances = () => {
    if (!timeline) return [];
    const orders = Array.isArray(timeline.orders) ? timeline.orders : [];
    const boardDates = Array.isArray(timeline.board_dates) ? timeline.board_dates : [];

    // Index board records by date for O(1) lookup
    const boardByDate = {};
    boardDates.forEach(bd => {
      if (bd.board_date) boardByDate[bd.board_date] = bd;
    });

    // Find the closest board record to a given date string (YYYY-MM-DD).
    // Tries exact match first; then picks the nearest date within 14 days.
    const findBoardRecord = (dateStr) => {
      if (!dateStr) return boardDates[0] || {};
      if (boardByDate[dateStr]) return boardByDate[dateStr];
      // Closest-date fallback
      const ts = new Date(dateStr).getTime();
      if (isNaN(ts)) return boardDates[0] || {};
      let best = null, bestDiff = Infinity;
      boardDates.forEach(bd => {
        const t = new Date(bd.board_date).getTime();
        if (!isNaN(t)) {
          const diff = Math.abs(t - ts);
          if (diff < bestDiff) { bestDiff = diff; best = bd; }
        }
      });
      // Accept if within 14 days; otherwise fall back to first board record
      return (best && bestDiff <= 14 * 86400000) ? best : (boardDates[0] || {});
    };

    // Top-level GP from case-details — used as fallback when per-order GP is absent
    const topLevelGP = Array.isArray(timeline.government_pleader)
      ? timeline.government_pleader
      : [];

    // Filter out status-only entries (no order_date, no order_link) — these
    // are internal processing markers that should not appear as table rows.
    const meaningfulOrders = orders.filter(o => o.order_date || o.order_link);

    return meaningfulOrders.map(order => {
      // Prefer board_date stored on the order (set by backend since fix),
      // fall back to order_date for matching against board records.
      const matchDate = order.board_date || order.order_date || null;
      const boardRecord = findBoardRecord(matchDate);

      const gpInBoard = [
        boardRecord.respondent_lawyer,
        ...(Array.isArray(boardRecord.additional_respondent_lawyers)
          ? boardRecord.additional_respondent_lawyers : [])
      ].filter(Boolean);

      const orderGP = Array.isArray(order.government_pleader)
        ? order.government_pleader
        : (order.government_pleader ? [order.government_pleader] : []);
      // Fall back to top-level GP when per-order GP not yet populated (old data)
      const gpInOrder = orderGP.length ? orderGP : topLevelGP;

      const rawLink = order.order_link || null;
      const boardDocId = boardRecord.board_doc_id || null;
      const orderPdfHref = rawLink
        ? (rawLink.startsWith('https://storage.googleapis.com')
            ? rawLink
            : boardDocId ? getApiUrl(`/orders/pdf/${boardDocId}`) : rawLink)
        : null;

      return {
        date: order.board_date || order.order_date || '-',
        orderDate: order.order_date || '-',
        orderPdf: orderPdfHref,
        orderAnalysis: order.order_category || null,
        gpInBoard: gpInBoard.length ? [...new Set(gpInBoard)].join(', ') : '-',
        gpInOrder: gpInOrder.length ? [...new Set(gpInOrder)].join(', ') : '-',
      };
    });
  };

  const appearances = getAppearances();
  const lifecycleEvents = Array.isArray(timeline?.lifecycle_events) ? timeline.lifecycle_events : [];
  const lifecycleStatus = timeline?.lifecycle_status;
  const lcCfg = lifecycleStatus ? getLifecycleConfig(lifecycleStatus) : null;

  return (
    <Modal show={show} onHide={onHide} size="xl" centered scrollable>
      <Modal.Header
        closeButton
        style={{ backgroundColor: 'var(--gray-50)', borderBottom: '1px solid var(--gray-200)' }}
      >
        <Modal.Title style={{ fontSize: '1rem', fontWeight: 600 }}>
          Case: <span style={{ color: 'var(--primary-color)' }}>{caseRef}</span>
          {lcCfg && (
            <Badge
              bg={lcCfg.variant}
              className="ms-2"
              style={{ fontSize: '0.7rem', verticalAlign: 'middle' }}
              title={lcCfg.tooltip}
            >
              {lcCfg.icon} {lcCfg.label}
            </Badge>
          )}
        </Modal.Title>
      </Modal.Header>

      <Modal.Body>
        {loading && (
          <div className="text-center py-5">
            <Spinner animation="border" variant="primary" />
            <p className="mt-3 text-muted">Loading case timeline…</p>
          </div>
        )}

        {error && (
          <Alert variant="danger" className="d-flex justify-content-between align-items-center">
            <span>{error}</span>
            <button
              className="btn btn-sm btn-outline-danger ms-3"
              onClick={fetchTimeline}
            >
              Retry
            </button>
          </Alert>
        )}

        {timeline && !loading && (
          <>
            {/* Case header */}
            <div
              className="mb-4 p-3"
              style={{ background: 'var(--gray-50)', borderRadius: 8, border: '1px solid var(--gray-200)' }}
            >
              <div className="row g-3">
                <div className="col-md-4">
                  <small className="text-muted d-block mb-1">Petitioner</small>
                  <strong style={{ fontSize: '0.9rem' }}>{timeline.petitioner || '—'}</strong>
                </div>
                <div className="col-md-4">
                  <small className="text-muted d-block mb-1">Respondent</small>
                  <strong style={{ fontSize: '0.9rem' }}>{timeline.respondent || '—'}</strong>
                </div>
                <div className="col-md-4">
                  <small className="text-muted d-block mb-1">Current Status</small>
                  {lcCfg ? (
                    <>
                      <Badge bg={lcCfg.variant} title={lcCfg.tooltip}>
                        {lcCfg.icon} {lcCfg.label}
                      </Badge>
                      {lcCfg.next && (
                        <small className="text-muted d-block mt-1">{lcCfg.next}</small>
                      )}
                    </>
                  ) : (
                    <strong style={{ fontSize: '0.9rem' }}>{timeline.lifecycle_status || '—'}</strong>
                  )}
                </div>
              </div>
            </div>

            {/* Appearances table */}
            <div className="d-flex justify-content-between align-items-center mb-2">
              <h6 className="mb-0">
                Appearances
                <Badge bg="secondary" className="ms-2">{appearances.length}</Badge>
              </h6>
            </div>

            <div className="table-responsive mb-4">
              <Table striped bordered hover size="sm" style={{ fontSize: '0.85rem' }}>
                <thead style={{ backgroundColor: 'var(--gray-100)' }}>
                  <tr>
                    <th style={{ whiteSpace: 'nowrap' }}>Date</th>
                    <th style={{ whiteSpace: 'nowrap' }}>GP in Board</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Order PDF</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Order Analysis</th>
                    <th style={{ whiteSpace: 'nowrap' }}>GP in Order</th>
                  </tr>
                </thead>
                <tbody>
                  {appearances.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="text-center text-muted py-4">
                        No appearances recorded yet.
                      </td>
                    </tr>
                  ) : (
                    appearances.map((app, i) => {
                      const catCfg = ORDER_CATEGORY_CONFIG[app.orderAnalysis];
                      return (
                        <tr key={i}>
                          <td style={{ whiteSpace: 'nowrap' }}>
                            {app.date}
                            {app.orderDate && app.orderDate !== app.date && (
                              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted, #6c757d)' }}>
                                Order: {app.orderDate}
                              </div>
                            )}
                          </td>
                          <td>{app.gpInBoard}</td>
                          <td>
                            {app.orderPdf ? (
                              <a
                                href={app.orderPdf}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: 'var(--primary-color)', fontWeight: 500 }}
                              >
                                View Order
                              </a>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                          <td>
                            {catCfg ? (
                              <Badge
                                bg={catCfg.bg}
                                text={catCfg.bg === 'warning' ? 'dark' : undefined}
                              >
                                {catCfg.label}
                              </Badge>
                            ) : (
                              <span className="text-muted">{app.orderAnalysis || '—'}</span>
                            )}
                          </td>
                          <td>{app.gpInOrder}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </Table>
            </div>

            {/* Lifecycle Event Timeline */}
            {lifecycleEvents.length > 0 && (
              <div>
                <button
                  className="btn btn-sm btn-outline-secondary mb-2"
                  onClick={() => setShowEvents(v => !v)}
                >
                  {showEvents ? '▲ Hide' : '▼ Show'} Lifecycle Event Log ({lifecycleEvents.length} events)
                </button>

                {showEvents && (
                  <div style={{ borderLeft: '3px solid var(--gray-200)', paddingLeft: '1rem' }}>
                    {[...lifecycleEvents].reverse().map((evt, i) => {
                      const cfg = getLifecycleConfig(evt.status || evt.to_status);
                      return (
                        <div
                          key={i}
                          className="mb-2 pb-2"
                          style={{ borderBottom: i < lifecycleEvents.length - 1 ? '1px solid var(--gray-100)' : 'none' }}
                        >
                          <div className="d-flex align-items-center gap-2 flex-wrap">
                            <Badge bg={cfg.variant} style={{ fontSize: '0.7rem' }}>
                              {cfg.icon} {cfg.label}
                            </Badge>
                            <small className="text-muted">
                              {evt.timestamp
                                ? new Date(evt.timestamp).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
                                : '—'}
                            </small>
                            {evt.error && (
                              <small className="text-danger" title={evt.error}>
                                Error: {evt.error.slice(0, 80)}{evt.error.length > 80 ? '…' : ''}
                              </small>
                            )}
                          </div>
                          {cfg.next && (
                            <small className="text-muted d-block mt-1" style={{ fontSize: '0.75rem' }}>
                              {cfg.next}
                            </small>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Modal.Body>
    </Modal>
  );
};

export default CaseDetailModal;
