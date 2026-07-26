import { describe, it, expect } from 'vitest';
import {
  BILLING_OUTCOMES,
  DEFAULT_OUTCOME,
  UNVERIFIED_RESULT,
  feeForResult,
  isUnverifiedResult,
  labelForResult,
  formatFee,
} from '../lib/billing';

// These strings and amounts are written verbatim into the exported Excel bill
// and must match calculate_case_fee() in billingonaire_backend/main.py.
describe('billing contract', () => {
  it('keeps the exact result strings the backend and export use', () => {
    expect(BILLING_OUTCOMES.map((o) => o.result)).toEqual([
      'ADJOURNED',
      'HEARD & ADJN.',
      'WP DISPOSED OF',
    ]);
  });

  it('keeps the exact fee amounts', () => {
    expect(feeForResult('ADJOURNED')).toBe(1250);
    expect(feeForResult('HEARD & ADJN.')).toBe(1875);
    expect(feeForResult('WP DISPOSED OF')).toBe(2500);
  });

  it('pairs each outcome with its own fee', () => {
    BILLING_OUTCOMES.forEach((o) => expect(feeForResult(o.result)).toBe(o.fee));
  });
});

describe('outcome drives fee, not the reverse', () => {
  it('derives the fee from the outcome', () => {
    // Previously the user picked a fee and the outcome was back-derived.
    expect(feeForResult('WP DISPOSED OF')).toBe(2500);
    expect(feeForResult('ADJOURNED')).toBe(1250);
  });

  it('falls back to the default outcome fee for an unknown result', () => {
    expect(feeForResult('SOMETHING ELSE')).toBe(DEFAULT_OUTCOME.fee);
    expect(feeForResult(undefined)).toBe(DEFAULT_OUTCOME.fee);
  });
});

describe('unverified (*ADJOURNED*) entries', () => {
  it('recognises the backend marker', () => {
    expect(isUnverifiedResult('*ADJOURNED*')).toBe(true);
    expect(isUnverifiedResult('ADJOURNED')).toBe(false);
    expect(isUnverifiedResult(null)).toBe(false);
  });

  it('bills at the adjourned rate', () => {
    expect(feeForResult(UNVERIFIED_RESULT)).toBe(1250);
  });

  it('is NOT flattened into a plain confirmed ADJOURNED', () => {
    // Regression: the old fee->result mapping turned 1250 into "ADJOURNED",
    // so touching the dropdown silently marked an unverified entry confirmed.
    expect(UNVERIFIED_RESULT).not.toBe('ADJOURNED');
    expect(labelForResult(UNVERIFIED_RESULT)).toMatch(/assumed/i);
    expect(labelForResult('ADJOURNED')).not.toMatch(/assumed/i);
  });

  it('is not offered as a choice in the standard outcome list', () => {
    expect(BILLING_OUTCOMES.some((o) => o.result === UNVERIFIED_RESULT)).toBe(false);
  });
});

describe('labels and formatting', () => {
  it('labels every outcome', () => {
    BILLING_OUTCOMES.forEach((o) => expect(labelForResult(o.result)).toBe(o.label));
  });

  it('passes unknown results through rather than blanking them', () => {
    expect(labelForResult('CUSTOM')).toBe('CUSTOM');
    expect(labelForResult(null)).toBe('—');
  });

  it('formats fees in Indian digit grouping', () => {
    expect(formatFee(1250)).toBe('₹1,250');
    expect(formatFee(250000)).toBe('₹2,50,000');
  });
});
