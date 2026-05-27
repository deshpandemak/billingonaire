// Shared config for all 13 lifecycle states and order statuses.
// Used by Table, CaseDetailModal, Dashboard, and nav badge.

export const LIFECYCLE_CONFIG = {
  board_ingested: {
    label: 'Board Uploaded', icon: '📋', variant: 'secondary',
    tooltip: 'Case added from daily board PDF.',
    next: 'Order fetch will be queued automatically.',
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
