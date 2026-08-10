import { describe, it, expect } from 'vitest';
import {
  LIFECYCLE_CONFIG,
  ORDER_STATUS_CONFIG,
  getLifecycleConfig,
  getOrderStatusConfig,
  STUCK_LIFECYCLE_STATUSES,
  STUCK_STATUS_FILTER_VALUE,
} from '../lib/lifecycleUtils';

describe('LIFECYCLE_CONFIG', () => {
  it('defines all expected lifecycle states', () => {
    const states = [
      'board_ingested',
      'fetch_queued',
      'fetch_in_progress',
      'fetch_succeeded',
      'analysis_queued',
      'analysis_in_progress',
      'analysed',
      'fetch_failed_retryable',
      'fetch_failed_terminal',
      'analysis_failed_retryable',
      'analysis_failed_terminal',
      'manual_review_required',
    ];
    states.forEach(state => {
      expect(LIFECYCLE_CONFIG[state], `missing entry for '${state}'`).toBeDefined();
    });
  });

  it('each entry has required label, variant, tooltip, and group fields', () => {
    Object.entries(LIFECYCLE_CONFIG).forEach(([state, cfg]) => {
      expect(cfg.label, `${state}.label`).toBeTruthy();
      expect(cfg.variant, `${state}.variant`).toBeTruthy();
      expect(cfg.tooltip, `${state}.tooltip`).toBeDefined();
      expect(cfg.group, `${state}.group`).toBeTruthy();
    });
  });
});

describe('getLifecycleConfig', () => {
  it('returns the correct config for board_ingested', () => {
    const cfg = getLifecycleConfig('board_ingested');
    expect(cfg.label).toBe('Board Uploaded');
    expect(cfg.variant).toBe('secondary');
    expect(cfg.group).toBe('pending');
  });

  it('returns null for the next step when status is analysed', () => {
    const cfg = getLifecycleConfig('analysed');
    expect(cfg.label).toBe('Analysed');
    expect(cfg.variant).toBe('success');
    expect(cfg.next).toBeNull();
  });

  it('returns correct config for manual_review_required', () => {
    const cfg = getLifecycleConfig('manual_review_required');
    expect(cfg.label).toBe('Needs Review');
    expect(cfg.variant).toBe('warning');
    expect(cfg.group).toBe('warning');
  });

  it('returns fallback object for an unknown status string', () => {
    const cfg = getLifecycleConfig('totally_unknown_state');
    expect(cfg.label).toBe('totally_unknown_state');
    expect(cfg.variant).toBe('secondary');
    expect(cfg.group).toBe('unknown');
    expect(cfg.next).toBeNull();
  });

  it('returns "Unknown" label for null input', () => {
    const cfg = getLifecycleConfig(null);
    expect(cfg.label).toBe('Unknown');
    expect(cfg.variant).toBe('secondary');
  });

  it('returns "Unknown" label for undefined input', () => {
    const cfg = getLifecycleConfig(undefined);
    expect(cfg.label).toBe('Unknown');
  });
});

describe('ORDER_STATUS_CONFIG', () => {
  it('defines entries for all standard order statuses', () => {
    const statuses = [
      'not_linked',
      'linked',
      'analysed',
      'order_failed',
      'order_analysis_failed',
    ];
    statuses.forEach(s => {
      expect(ORDER_STATUS_CONFIG[s], `missing entry for '${s}'`).toBeDefined();
    });
  });
});

describe('getOrderStatusConfig', () => {
  it('returns correct config for not_linked', () => {
    const cfg = getOrderStatusConfig('not_linked');
    expect(cfg.label).toBe('No Order');
    expect(cfg.variant).toBe('secondary');
  });

  it('returns correct config for analysed', () => {
    const cfg = getOrderStatusConfig('analysed');
    expect(cfg.label).toBe('Complete');
    expect(cfg.variant).toBe('success');
  });

  it('returns correct config for order_analysis_failed', () => {
    const cfg = getOrderStatusConfig('order_analysis_failed');
    expect(cfg.label).toBe('Analysis Failed');
    expect(cfg.variant).toBe('warning');
  });

  it('returns fallback for unknown status', () => {
    const cfg = getOrderStatusConfig('mystery_status');
    expect(cfg.label).toBe('mystery_status');
    expect(cfg.variant).toBe('secondary');
  });

  it('returns "Unknown" label for null', () => {
    const cfg = getOrderStatusConfig(null);
    expect(cfg.label).toBe('Unknown');
  });
});

// ─── Simple status + order vocabulary ───────────────────────────────────────

import {
  SIMPLE_STATUS,
  getSimpleStatus,
  ORDER_CATEGORY_LABELS,
  getOrderCategoryLabel,
  canonicalOrderCategory,
} from '../lib/lifecycleUtils';

describe('getSimpleStatus', () => {
  it('maps every one of the 13 lifecycle states to exactly one simple status', () => {
    const valid = new Set(Object.keys(SIMPLE_STATUS));
    const states = Object.keys(LIFECYCLE_CONFIG);
    expect(states.length).toBe(13);
    states.forEach((s) => {
      const simple = getSimpleStatus(s);
      expect(simple, `no simple status for ${s}`).toBeTruthy();
      expect(valid.has(simple.key), `${s} -> ${simple.key}`).toBe(true);
    });
  });

  it('puts billable work in Ready and only analysed there', () => {
    expect(getSimpleStatus('analysed').key).toBe('ready');
    Object.keys(LIFECYCLE_CONFIG)
      .filter((s) => s !== 'analysed')
      .forEach((s) => expect(getSimpleStatus(s).key).not.toBe('ready'));
  });

  it('routes every failure and review state to Needs you', () => {
    [
      'fetch_failed_retryable',
      'fetch_failed_terminal',
      'analysis_failed_retryable',
      'analysis_failed_terminal',
      'manual_review_required',
    ].forEach((s) => expect(getSimpleStatus(s).key).toBe('attention'));
  });

  it('handles legacy/extra states that are absent from LIFECYCLE_CONFIG', () => {
    // These used to fall through and render as raw snake_case.
    expect(getSimpleStatus('fetch_not_due').key).toBe('waiting');
    expect(getSimpleStatus('order_failed').key).toBe('attention');
    expect(getSimpleStatus('order_analysis_failed').key).toBe('attention');
    expect(getSimpleStatus('not_linked').key).toBe('waiting');
    expect(getSimpleStatus('linked').key).toBe('working');
  });

  it('never returns a raw snake_case label', () => {
    ['fetch_not_due', 'analysis_failed', 'something_unknown', null, undefined].forEach(
      (s) => expect(getSimpleStatus(s).label).not.toMatch(/_/)
    );
  });
});

describe('order category vocabulary', () => {
  it('labels all three canonical categories', () => {
    ['ADJOURNED', 'HEARD_AND_ADJOURNED', 'DISPOSED_OFF'].forEach((c) => {
      expect(ORDER_CATEGORY_LABELS[c]).toBeTruthy();
      expect(getOrderCategoryLabel(c)).toBe(ORDER_CATEGORY_LABELS[c]);
    });
  });

  it('folds the legacy spellings onto the same three categories', () => {
    expect(canonicalOrderCategory('WP DISPOSED OF')).toBe('DISPOSED_OFF');
    expect(canonicalOrderCategory('DISPOSAL')).toBe('DISPOSED_OFF');
    expect(canonicalOrderCategory('HEARD & ADJN')).toBe('HEARD_AND_ADJOURNED');
    expect(canonicalOrderCategory('HEARD & ADJRN')).toBe('HEARD_AND_ADJOURNED');
    expect(canonicalOrderCategory('ADJOURNMENT')).toBe('ADJOURNED');
  });

  it('gives one display string per outcome regardless of input spelling', () => {
    ['DISPOSED_OFF', 'WP DISPOSED OF', 'DISPOSAL', 'Disposed of'].forEach((v) =>
      expect(getOrderCategoryLabel(v)).toBe('Disposed of')
    );
  });

  it('passes unknown values through rather than blanking them', () => {
    expect(getOrderCategoryLabel('SOMETHING_ELSE')).toBe('SOMETHING_ELSE');
    expect(getOrderCategoryLabel(null)).toBe('—');
  });
});

describe('STUCK_LIFECYCLE_STATUSES', () => {
  // Mirrors main.py's STUCK_LIFECYCLE_STATUSES -- the Dashboard's "N cases
  // could not be completed automatically" banner and its "See which cases"
  // link must agree on exactly this set, not the broader "attention" bucket
  // (which also includes manual_review_required, a separate queue).
  it('is exactly the four failure states, excluding manual_review_required', () => {
    expect(STUCK_LIFECYCLE_STATUSES).toEqual([
      'fetch_failed_retryable',
      'fetch_failed_terminal',
      'analysis_failed_retryable',
      'analysis_failed_terminal',
    ]);
    expect(STUCK_LIFECYCLE_STATUSES).not.toContain('manual_review_required');
  });

  it('every listed state is a real, known lifecycle state', () => {
    STUCK_LIFECYCLE_STATUSES.forEach((status) => {
      expect(LIFECYCLE_CONFIG[status]).toBeTruthy();
    });
  });

  it('STUCK_STATUS_FILTER_VALUE is the comma-joined list Board.getData expects', () => {
    expect(STUCK_STATUS_FILTER_VALUE).toBe(
      'fetch_failed_retryable,fetch_failed_terminal,analysis_failed_retryable,analysis_failed_terminal'
    );
  });
});
