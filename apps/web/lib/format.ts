export const ROLE_LABELS: Record<string, string> = {
  presales: 'Presales Engineer',
  architect: 'Solution Architect',
  aieng: 'AI Engineer',
  ea: 'Enterprise Architect',
  finance: 'Finance / Commercial',
  pmo: 'PMO / Delivery',
  reviewer: 'Governance Reviewer',
  admin: 'Platform Administrator',
};

export function money(v: string | number | undefined | null, currency = 'INR'): string {
  const n = Number(v ?? 0);
  if (!isFinite(n)) return '—';
  if (currency === 'INR') {
    if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
    return `₹${Math.round(n).toLocaleString('en-IN')}`;
  }
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

export function when(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export const STATUS_TONE: Record<string, string> = {
  succeeded: 'good', Approved: 'good', approved: 'good', prod: 'good',
  running: 'acc', queued: 'info', staging: 'info',
  awaiting_approval: 'gold', approval: 'gold', Pending: 'warn', in_review: 'warn', dev: 'plain',
  failed: 'bad', Rejected: 'bad', cancelled: 'plain', skipped: 'plain', simulation: 'info',
};
