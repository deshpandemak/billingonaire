// Shared config for all 13 lifecycle states and order statuses.
// Used by Table, CaseDetailModal, Dashboard, and nav badge.

export const LIFECYCLE_CONFIG = {
  board_ingested: {
    label: 'Board Uploaded', icon: '📋', variant: 'secondary',
    tooltip: 'Case added from daily board PDF.',
    next: 'Order fetch will be queued automatically.',
    group: 'pending',
  },
  fetch_not_due: {
    label: 'Not Due Yet', icon: '📅', variant: 'secondary',
    tooltip: 'Board date is in the future — the court has not heard this matter yet.',
    next: 'Order fetch will start once the board date arrives.',
    group: 'pending',
  },
  fetch_queued: {
    label: 'Awaiting Fetch', icon: '⏳', variant: 'primary',
    tooltip: 'Waiting to download order PDF from the BHC website.',
    next: 'Download will begin shortly.',
    group: 'pending',
  },
  fetch_in_progress: {
    label: 'Fetching', icon: '🔄', variant: 'primary',
    tooltip: 'Currently downloading order PDF from BHC website.',
    next: 'In progress…',
    group: 'active',
  },
  fetch_succeeded: {
    label: 'Fetched', icon: '📥', variant: 'info',
    tooltip: 'Order PDF downloaded. Queued for ML analysis.',
    next: 'Analysis will begin shortly.',
    group: 'active',
  },
  analysis_queued: {
    label: 'Awaiting Analysis', icon: '⏳', variant: 'info',
    tooltip: 'Order PDF downloaded. Waiting for ML analysis to start.',
    next: 'Analysis will begin shortly.',
    group: 'active',
  },
  analysis_in_progress: {
    label: 'Analysing', icon: '🔍', variant: 'info',
    tooltip: 'ML model is reading the order PDF.',
    next: 'In progress…',
    group: 'active',
  },
  analysed: {
    label: 'Analysed', icon: '✅', variant: 'success',
    tooltip: 'Order fully downloaded and analysed. Ready for billing.',
    next: null,
    group: 'done',
  },
  fetch_failed_retryable: {
    label: 'Fetch Failed', icon: '⚠️', variant: 'warning',
    tooltip: "Order not yet on BHC website — will retry automatically tonight.",
    next: 'Automatic retry scheduled.',
    group: 'warning',
  },
  fetch_failed_terminal: {
    label: 'Fetch Failed', icon: '❌', variant: 'danger',
    tooltip: 'Could not download order after all retries.',
    next: 'Please upload the order PDF manually.',
    group: 'error',
  },
  analysis_failed_retryable: {
    label: 'Analysis Failed', icon: '⚠️', variant: 'warning',
    tooltip: 'ML analysis failed — will retry automatically.',
    next: 'Automatic retry scheduled.',
    group: 'warning',
  },
  analysis_failed_terminal: {
    label: 'Cannot Read', icon: '❌', variant: 'danger',
    tooltip: "Order PDF couldn't be processed automatically.",
    next: 'Upload the order manually or flag for review.',
    group: 'error',
  },
  manual_review_required: {
    label: 'Needs Review', icon: '🔍', variant: 'warning',
    tooltip: 'Low-confidence ML result — human review needed.',
    next: 'Go to Review Queue to confirm or override.',
    group: 'warning',
  },
};

export const ORDER_STATUS_CONFIG = {
  not_linked:            { label: 'No Order',        variant: 'secondary', tooltip: 'Order not yet downloaded.' },
  linked:                { label: 'Order Linked',    variant: 'info',      tooltip: 'Order PDF downloaded. Click Analyse to extract details.' },
  analysed:              { label: 'Complete',        variant: 'success',   tooltip: 'Order downloaded and analysed. Ready for billing.' },
  order_failed:          { label: 'Download Failed', variant: 'danger',    tooltip: 'Order could not be downloaded from BHC website.' },
  order_analysis_failed: { label: 'Analysis Failed', variant: 'warning',   tooltip: 'Analysis failed — click Analyse to retry.' },
  manually_uploaded:     { label: 'Manual Upload',   variant: 'secondary', tooltip: 'Order was uploaded manually.' },
};

export const getLifecycleConfig = (status) =>
  LIFECYCLE_CONFIG[status] || { label: status || 'Unknown', icon: '?', variant: 'secondary', tooltip: '', next: null, group: 'unknown' };

export const getOrderStatusConfig = (status) =>
  ORDER_STATUS_CONFIG[status] || { label: status || 'Unknown', variant: 'secondary', tooltip: '' };

// ─── Simple status ──────────────────────────────────────────────────────────
// The 13 lifecycle states are an engineering model. Users only need to know
// whether a case is waiting, moving, billable, or stuck — four buckets, derived
// from the `group` field already on every LIFECYCLE_CONFIG entry so there is
// one source of truth. The full state (and its timeline) stays visible in the
// case detail modal and the Admin area.
//
// These four keys are also the values the Search Orders status filter sends to
// the backend; Board.getData() matches on the same names.

export const SIMPLE_STATUS = {
  waiting:  { key: 'waiting',  label: 'Waiting',     icon: '🕐', variant: 'secondary', tooltip: 'The court has not published this order yet.' },
  working:  { key: 'working',  label: 'In progress', icon: '🔄', variant: 'info',      tooltip: 'Downloading or reading the order now.' },
  ready:    { key: 'ready',    label: 'Ready',       icon: '✅', variant: 'success',   tooltip: 'Order read and categorised — ready to bill.' },
  attention:{ key: 'attention',label: 'Needs you',   icon: '⚠️', variant: 'warning',   tooltip: 'Could not be completed automatically — needs a person.' },
};

// group (from LIFECYCLE_CONFIG) → simple status key
const GROUP_TO_SIMPLE = {
  pending: 'waiting',
  active:  'working',
  done:    'ready',
  warning: 'attention',
  error:   'attention',
};

// States that predate LIFECYCLE_CONFIG or are written by older code paths.
// Mapping them here stops them rendering as raw snake_case.
const EXTRA_STATE_TO_SIMPLE = {
  fetch_not_due:   'waiting',
  fetch_failed:    'attention',
  analysis_failed: 'attention',
  not_linked:      'waiting',
  linked:          'working',
  order_failed:    'attention',
  order_analysis_failed: 'attention',
  manually_uploaded: 'working',
};

export const getSimpleStatus = (lifecycleStatus) => {
  if (!lifecycleStatus) return SIMPLE_STATUS.waiting;
  const direct = EXTRA_STATE_TO_SIMPLE[lifecycleStatus];
  if (direct) return SIMPLE_STATUS[direct];
  const group = LIFECYCLE_CONFIG[lifecycleStatus]?.group;
  return SIMPLE_STATUS[GROUP_TO_SIMPLE[group]] || SIMPLE_STATUS.waiting;
};

// ─── Order outcome vocabulary ───────────────────────────────────────────────
// The same three outcomes were previously spelled four different ways across
// Table.jsx and BillGeneration.jsx. Canonical values on the wire are unchanged;
// this map is display-only.

export const ORDER_CATEGORY_LABELS = {
  ADJOURNED:           'Adjourned',
  HEARD_AND_ADJOURNED: 'Heard & adjourned',
  DISPOSED_OFF:        'Disposed of',
};

// Legacy/display spellings that mean the same three things.
const CATEGORY_ALIASES = {
  'HEARD & ADJN': 'HEARD_AND_ADJOURNED',
  'HEARD & ADJN.': 'HEARD_AND_ADJOURNED',
  'HEARD & ADJRN': 'HEARD_AND_ADJOURNED',
  'HEARD AND ADJOURNED': 'HEARD_AND_ADJOURNED',
  'WP DISPOSED OF': 'DISPOSED_OFF',
  'DISPOSED OF': 'DISPOSED_OFF',
  'DISPOSAL': 'DISPOSED_OFF',
  'ADJOURNMENT': 'ADJOURNED',
};

export const canonicalOrderCategory = (value) => {
  if (!value) return null;
  const raw = String(value).trim().toUpperCase();
  if (ORDER_CATEGORY_LABELS[raw]) return raw;
  return CATEGORY_ALIASES[raw] || null;
};

export const getOrderCategoryLabel = (value) => {
  const canonical = canonicalOrderCategory(value);
  return canonical ? ORDER_CATEGORY_LABELS[canonical] : (value || '—');
};
