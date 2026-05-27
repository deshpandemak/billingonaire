import { describe, it, expect } from 'vitest';
import {
  LIFECYCLE_CONFIG,
  ORDER_STATUS_CONFIG,
  getLifecycleConfig,
  getOrderStatusConfig,
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
