// Billing outcomes and their fees.
//
// The outcome is the fact — what the court actually did — and the fee follows
// from it. The bill screen used to work the other way round: you picked a rupee
// amount and the outcome text was back-derived from it (getResultFromFee).
// That inverted cause and effect, and it silently destroyed the "*ADJOURNED*"
// marker described below.
//
// The `result` strings and fee amounts here must match calculate_case_fee() in
// billingonaire_backend/main.py exactly — they are written verbatim into the
// exported Excel bill, so they are a data contract, not display text.

export const BILLING_OUTCOMES = [
  { result: 'ADJOURNED',      fee: 1250, label: 'Adjourned' },
  { result: 'HEARD & ADJN.',  fee: 1875, label: 'Heard & adjourned' },
  { result: 'WP DISPOSED OF', fee: 2500, label: 'Disposed of' },
];

// The backend writes "*ADJOURNED*" (asterisks included) when there is no
// analysed order for the hearing, i.e. the adjournment is assumed rather than
// confirmed. It bills the same as ADJOURNED but means something different, so
// it must survive editing rather than being flattened to plain "ADJOURNED".
export const UNVERIFIED_RESULT = '*ADJOURNED*';

export const isUnverifiedResult = (result) =>
  String(result || '').trim() === UNVERIFIED_RESULT;

export const DEFAULT_OUTCOME = BILLING_OUTCOMES[1]; // HEARD & ADJN.

/** Fee for an outcome. Unverified entries bill at the ADJOURNED rate. */
export const feeForResult = (result) => {
  if (isUnverifiedResult(result)) return 1250;
  const match = BILLING_OUTCOMES.find((o) => o.result === result);
  return match ? match.fee : DEFAULT_OUTCOME.fee;
};

/** Human label for an outcome, including the unverified marker. */
export const labelForResult = (result) => {
  if (isUnverifiedResult(result)) return 'Adjourned (assumed — no order on file)';
  const match = BILLING_OUTCOMES.find((o) => o.result === result);
  return match ? match.label : (result || '—');
};

export const formatFee = (fee) => `₹${Number(fee || 0).toLocaleString('en-IN')}`;
